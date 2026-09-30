# -*- coding: utf-8 -*-
"""
Los iconos SVG: comprobarlos, limpiarlos y dejarlos listos para el croquis.

POR QUE SVG
-----------
Un PNG se guarda a 160 px de lado. Los iconos del mapa miden 24.4 unidades en
un lienzo de 1224, y con el zoom se amplian hasta cuatro veces: un PNG de 160
px estirado a 3800 px se ve pixelado. Un SVG no: son ordenes de dibujar, y se
ven igual de nitidos a cualquier tamano. Un logo subido en SVG sale perfecto
tanto en la vista general como ampliado a tope.

ESTO NO EJECUTA NADA
--------------------
El SVG se dibuja con `<image href="data:image/svg+xml;...">`, que es contexto de
imagen, como un `<img src>`. El navegador NO ejecuta scripts, NO carga recursos
de fuera y NO aplica hojas de estilo en ese contexto. Un `<script>` dentro del
SVG, ahi, es una etiqueta ignorada.

Aun asi se limpia, por dos razones. Una, que el archivo no se dibuja solo en el
`<image>`: alguien puede abrir la data URL directamente, o un lector de pantalla
puede tratarla de otra forma, y un SVG que viaja dentro de un documento ajeno no
deberia llevar segun que. Y dos, porque es barato: quitar lo que un icono no
necesita no cuesta nada y el dia que el SVG se dibuje de otra manera, la
limpieza ya esta hecha.

La limpieza es conservadora: se quitan los elementos que existen para ejecutar
o traer cosas de fuera, y los atributos que empiezan por `on`. Todo lo que
dibuja —formas, degradados, filtros, mascaras, texto— se queda tal cual.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET

# El tope vive en validar.py, con todos los demas: es una regla sobre que cabe
# en el croquis, no una decision de este archivo. Aqui solo se aplica.
from validar import MAX_VECTOR

NS = "http://www.w3.org/2000/svg"
NS_XLINK = "http://www.w3.org/1999/xlink"

# Lo que un SVG de icono no tiene por que llevar nunca. Son los elementos que
# existen para ejecutar codigo o para incrustar cosas de otro sitio; quitarlos
# no rompe ningun dibujo, porque ninguno dibuja.
#
# No se tocan las animaciones propias del SVG (`<animate>` y compania). Si el
# dibujo trae la suya, es cosa de quien lo hizo, y quitarala cambiaria el
# archivo sin avisar.
PROHIBIDOS = {"script", "foreignobject", "iframe", "embed", "object",
              "handler", "listener"}

# Los atributos que pueden traer algo de fuera. Se dejan pasar los que apuntan
# dentro del propio SVG (`#degradado`), que son la mayoria y son inofensivos.
ATRIBUTOS_URL = {"href", "src", "xlink:href", "action", "formaction", "data",
                 "poster", "background", "cite"}


class SvgInvalido(Exception):
    """Un SVG que no se puede usar, con el motivo ya escrito para ensenarlo."""


def parece_svg(crudo: bytes) -> bool:
    """Si esto es un SVG.

    No se mira la extension del archivo ni el tipo que declara el navegador,
    que los dos mienten: se mira el contenido. Un SVG empieza por `<svg` o por
    una declaracion XML, y esa pista no la da un PNG ni una foto.
    """
    cabeza = crudo[:600].lstrip()
    if cabeza.startswith(b"\xef\xbb\xbf"):
        cabeza = cabeza[3:].lstrip()
    if cabeza.startswith(b"<?xml"):
        return b"<svg" in crudo[:4000]
    return cabeza.startswith(b"<svg")


def _local(etiqueta: str) -> str:
    """El nombre de una etiqueta sin su espacio de nombres."""
    return etiqueta.rsplit("}", 1)[-1].lower() if etiqueta else ""


def _externa(valor: str) -> bool:
    """Si una URL apunta fuera del propio archivo.

    Se dejan pasar las que van a un `#ancla` de dentro, que son las que usan
    los degradados y las mascaras para referirse a otro elemento del mismo
    dibujo.
    """
    limpio = (valor or "").strip().lstrip("\"'").strip()
    if not limpio or limpio.startswith("#"):
        return False
    bajo = limpio.lower()
    return (bajo.startswith(("http:", "https:", "//", "javascript:", "file:"))
            or (bajo.startswith("data:") and "," not in bajo)
            or bajo.startswith("data:text/html"))


def _limpia(raiz: ET.Element) -> list[str]:
    """Quita del arbol lo que no tiene nada que hacer en un icono.

    Devuelve la lista de lo que se quito, para poder decirlo. Si el icono
    venia con un `<script>` hay que enterarse: casi siempre significa que el
    archivo salio de un sitio raro.
    """
    quitado: list[str] = []

    # De abajo arriba, para poder quitar un padre y sus hijos sin recorrer
    # ramas ya muertas. El parentesco no lo guarda ElementTree, asi que se
    # arma un mapa antes.
    padre = {hijo: p for p in raiz.iter() for hijo in p}
    for nodo in list(raiz.iter()):
        nombre = _local(nodo.tag)
        if nombre in PROHIBIDOS:
            p = padre.get(nodo)
            if p is not None:
                p.remove(nodo)
                quitado.append(f"<{nombre}>")
            continue

        seFueSuUrl = False
        for atributo in list(nodo.attrib):
            llave = _local(atributo)
            valor = nodo.attrib[atributo]
            if llave.startswith("on"):
                del nodo.attrib[atributo]
                quitado.append(f"{llave}=")
            elif llave in ATRIBUTOS_URL and _externa(valor):
                del nodo.attrib[atributo]
                quitado.append(f"{llave}= (a {valor[:20]}…)")
                seFueSuUrl = True
            elif "url(" in valor.lower():
                # Un `url(...)` puede estar en `fill`, en `style`, en `filter`
                # o en `mask`, y es la otra puerta por la que entra algo de
                # otro sitio. Si alguna apunta a fuera, se va el atributo.
                if any(_externa(u) for u in re.findall(r"url\(([^)]*)\)", valor)):
                    del nodo.attrib[atributo]
                    quitado.append(f"{llave}=url(…)")

        # Un <image> o un <use> sin su href no dibujan nada: son un hueco que
        # ocupa sitio en el archivo y no se ve. Se van con su referencia.
        if seFueSuUrl and nombre in ("image", "use"):
            p = padre.get(nodo)
            if p is not None:
                p.remove(nodo)
                quitado.append(f"<{nombre}> (se quedó sin a qué apuntar)")

    return quitado


def _minifica(raiz: ET.Element) -> bytes:
    """El SVG en una linea, sin espacios que sobren.

    Un SVG exportado de Illustrator o de Figma viene con la indentacion puesta
    y con comentarios, y eso puede ser un tercio del archivo. Se quitan los
    comentarios y los espacios entre etiquetas; los que van dentro de un texto
    se quedan, que ahi si significan algo.
    """
    ET.register_namespace("", NS)
    ET.register_namespace("xlink", NS_XLINK)
    crudo = ET.tostring(raiz, encoding="unicode")
    # Los comentarios no los toca ElementTree: se quitan a mano.
    crudo = re.sub(r"<!--.*?-->", "", crudo, flags=re.S)
    # Espacios entre etiquetas: `>   <` pasa a `><`. Los que hay dentro de un
    # <text> van entre caracteres, no entre `>` y `<`, asi que no se tocan.
    crudo = re.sub(r">\s+<", "><", crudo)
    return crudo.strip().encode("utf-8")


def _arregla_xlink(crudo: bytes) -> bytes:
    """Le pone la declaracion de `xlink` si el SVG la usa sin declararla.

    Un navegador tolera `xlink:href` sin `xmlns:xlink`, pero un lector de XML
    estricto no: falla con «unbound prefix». Pasa con archivos exportados por
    programas que se saltan la declaracion, y rechazarlos por eso seria
    rechazar SVGs que en el navegador se ven perfectos.

    Se le añade la declaracion en vez de quitarle el prefijo: cambiarlo por
    `href` a secas seria reescribir el dibujo, y algunos lectores viejos solo
    entienden `xlink:href`.
    """
    if b"xlink:" not in crudo or b"xmlns:xlink" in crudo:
        return crudo
    # Solo se toca la etiqueta de apertura del <svg>.
    m = re.search(rb"<svg\b[^>]*>", crudo)
    if not m:
        return crudo
    apertura = m.group(0)
    arreglada = apertura[:-1] + b' xmlns:xlink="http://www.w3.org/1999/xlink">'
    return crudo[:m.start()] + arreglada + crudo[m.end():]


def prepara(crudo: bytes) -> tuple[str, bytes]:
    """Comprueba y limpia un SVG. Devuelve el SVG y como se llama su tamano.

    Lo que se comprueba, y por que:

      - Que sea XML bien formado. Un SVG roto no se dibuja y el navegador no
        dice nada: sale un hueco y ya.
      - Que traiga con que escalar, o sea un `viewBox` o un ancho y un alto.
        Sin eso el navegador no sabe que proporcion tiene y el icono sale del
        tamano que le apetezca.
      - Que no pase del tope de peso. La pagina la abre un movil escaneando un
        QR.

    Lo que se limpia: ver el comentario de arriba del archivo.
    """
    if len(crudo) > MAX_VECTOR * 2:
        raise SvgInvalido(
            f"El SVG pesa {len(crudo) // 1024} KB y el tope son "
            f"{MAX_VECTOR // 1024} KB. Un icono no necesita tanto: seguramente "
            f"lleve dentro un mapa o una foto convertida a trazados.")

    try:
        raiz = ET.fromstring(_arregla_xlink(crudo))
    except ET.ParseError as e:
        raise SvgInvalido(
            f"El SVG no está bien formado: {e}.\n"
            f"Si lo has exportado de un programa, prueba a volver a exportarlo.") from None

    if _local(raiz.tag) != "svg":
        raise SvgInvalido(
            f"El dibujo de dentro es un <{_local(raiz.tag)}>, no un <svg>. "
            f"Parece un archivo que envuelve al SVG; abre el de dentro.")

    ancho = raiz.get("width") or ""
    alto = raiz.get("height") or ""
    caja = raiz.get("viewBox") or ""
    if not caja and not (ancho and alto):
        raise SvgInvalido(
            "Al SVG le falta el viewBox, o un ancho y un alto. Sin eso no se "
            "sabe qué proporción tiene y el icono sale del tamaño que le "
            "apetezca al navegador. Se arregla abriéndolo en un editor de "
            "vectores y volviéndolo a exportar.")

    quitado = _limpia(raiz)
    if not list(raiz):
        raise SvgInvalido(
            "Al SVG no le quedó nada después de limpiarlo. Lo que traía era "
            "justo lo que un icono no puede llevar.")

    limpio = _minifica(raiz)
    if len(limpio) > MAX_VECTOR:
        raise SvgInvalido(
            f"El SVG pesa {len(limpio) // 1024} KB después de limpiarlo y el "
            f"tope son {MAX_VECTOR // 1024} KB. Un icono no necesita tanto: "
            f"seguramente lleve dentro un mapa o una foto convertida a trazados.")

    return limpio.decode("utf-8"), quitado


def a_data_url(svg: str) -> str:
    """El SVG como data URL, en base64.

    Se usa base64 y no el SVG en texto con los caracteres escapados porque el
    SVG va dentro de un atributo entre comillas dobles, y ahi un `"` suelto lo
    parte. Base64 solo tiene letras, numeros y `+/=`, asi que no puede romper
    nada por mucho raro que sea el dibujo.
    """
    return ("data:image/svg+xml;base64,"
            + base64.b64encode(svg.encode("utf-8")).decode("ascii"))


def de_data_url(datos_url: str) -> bytes:
    """Los bytes de un SVG que viene en data URL."""
    trozo = re.match(r"data:image/svg\+xml;base64,(.+)$", datos_url or "",
                     re.S | re.I)
    if not trozo:
        raise SvgInvalido("Eso no es un SVG en data URL.")
    try:
        return base64.b64decode(trozo.group(1), validate=False)
    except (ValueError, TypeError):
        raise SvgInvalido("El SVG viene mal codificado.") from None
