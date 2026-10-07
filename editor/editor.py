# -*- coding: utf-8 -*-
"""
Editor local del croquis. Es el unico que puede modificar el mapa.

POR QUE EXISTE ESTE ARCHIVO
---------------------------
El croquis que se publica en GitHub Pages es un HTML suelto, sin servidor y
sin backend: quien lo abre solo puede mirarlo. Eso no se toca. Lo que hace
falta es una herramienta aparte, para la persona que organiza el evento, que
pueda mover las zonas y los iconos sin editar el HTML a mano.

Esta es esa herramienta, y vive en tu maquina:

  - Escucha solo en 127.0.0.1, no en la red. Desde otro equipo no se llega.
  - Rechaza las peticiones cuyo Host no sea localhost, para que una pagina
    web abierta en este equipo no pueda apuntar un dominio a 127.0.0.1 y
    colarse por el navegador.
  - No sirve archivos por ruta: solo responde a las direcciones de la lista.
  - Nada de esto se sube a GitHub Pages. Lo que se publica es croquis.html,
    que es solo lectura.

Si el archivo del editor acabara publicado por accidente, no pasaria nada
grave: no puede escribir en el croquis sin este servidor, y el servidor solo
existe mientras tu lo tengas abierto.

USO
---
    python editor/editor.py            (abre el navegador solo)
    python editor/editor.py --no-abrir
    python editor/editor.py --puerto 8730
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CROQUIS = RAIZ / "plantilla" / "croquis.html"
MAPA = RAIZ / "plantilla" / "rectoria.webp"
EDITOR_HTML = Path(__file__).resolve().parent / "editor.html"
RESPALDO = Path(__file__).resolve().parent / "_respaldo"
# Los PNG ya preparados, uno por icono propio. Es lo que permite volver a
# poner un icono que se quito del mapa sin tener que buscar otra vez la imagen
# original: la que se subio ya no esta en ningun sitio, asi que se guarda aqui.
BIBLIOTECA = Path(__file__).resolve().parent / "iconos"

# Los modelos: iconos guardados enteros, con su tamano, su giro, su animacion
# y su informacion, listos para estampar varios iguales de un clic.
#
# Viven en un archivo aparte y NO dentro del croquis. El croquis solo lleva lo
# que se ve en el mapa, y un modelo no se ve: es la plantilla con la que se
# hacen los iconos. Meterlos ahi engordaria la pagina que abre el QR con datos
# que el movil no usa.
MODELOS = Path(__file__).resolve().parent / "modelos.json"

# validar.py vive junto a este archivo, pero cuando el proyecto se importa
# desde fuera (test_qr.py lo hace) el paquete se llama editor. Se admiten las
# dos formas para que funcione igual ejecutado que importado.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validar import (  # noqa: E402  (va despues del sys.path a proposito)
    ALTO,
    ANCHO,
    ANIMACIONES,
    ANIMACIONES_BORDE,
    ANIMACIONES_SIN_INTENSIDAD,
    ANIMACIONES_ZONA,
    INTENSIDAD,
    MAX_BOTON,
    MAX_ICONO,
    MAX_ICONOS_PROPIOS,
    MAX_INTENSIDAD,
    MAX_MODELOS,
    MAX_NOMBRE_MODELO,
    MAX_REDONDEO,
    MAX_ROT,
    MAX_TAM_ICONO,
    MAX_TEXTO,
    MAX_TITULO,
    MAX_URL,
    MAX_VECTOR,
    MIN_INTENSIDAD,
    MIN_ROT,
    MIN_TAM_ICONO,
    NOMBRE_PROPIO,
    SIMBOLOS,
    limpiar_adornos,
    limpiar_ajustes,
    revisar,
    revisar_ajustes,
    revisar_modelos,
)
import vector  # noqa: E402  (los iconos en SVG)

# ---------------------------------------------------------------------------
# La huella del codigo
# ---------------------------------------------------------------------------
# El servidor carga los .py UNA vez, al arrancar. Si despues se editan, el
# proceso que sigue respondiendo es el viejo, y desde fuera no hay forma de
# notarlo: la pagina se sirve nueva del disco, asi que todo parece al dia
# mientras las reglas que deciden el guardado son las de antes.
#
# Paso de verdad con el redondeo de las esquinas: se anadio al editor, el que
# estaba abierto no conocia la clave, la tiro en silencio al limpiar los
# adornos y el archivo salio sin ella. Lo que llegaba a GitHub eran las zonas
# sin redondear y no hubo un solo error por ningun lado. Es el fallo mas caro
# que puede tener esta herramienta, porque lo perdido no se puede recuperar:
# nadie sabe que se perdio.
#
# Se guarda la huella con la que arranco el proceso y se compara con la que hay
# en el disco. Si no cuadran, la pagina avisa y no deja guardar hasta reiniciar.
def huella_del_codigo() -> str:
    """El sha1 de los .py del editor, que son los que deciden como se guarda."""
    h = hashlib.sha1()
    for ruta in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(ruta.name.encode("utf-8"))
        h.update(ruta.read_bytes())
    return h.hexdigest()[:12]


HUELLA_ARRANQUE = huella_del_codigo()

HOSTS_LOCALES = {"127.0.0.1", "localhost", "::1", "[::1]"}

# Lo que mide un icono propio, en pixeles de lado. Con 160 px sobra para la
# pantalla de un movil, incluso acercando, y mantiene la imagen en unos pocos
# KB: cada byte acaba dos veces en el croquis, una en los datos y otra en el
# texto base64.
LADO_ICONO = 160


class ErrorEditor(Exception):
    """Un problema que se le puede contar a quien esta usando el editor."""


# ---------------------------------------------------------------------------
# Lectura y escritura del croquis
# ---------------------------------------------------------------------------
# El croquis lleva marcadores alrededor de los dos bloques que el editor
# reescribe. Se usan marcadores y no expresiones regulares sobre el codigo
# porque el dia que alguien reformatee el archivo, una expresion regular
# falla en silencio o, peor, se lleva por delante el bloque de al lado.
def _marcadores(nombre: str) -> tuple[str, str]:
    return f"/* === INICIO {nombre} === */", f"/* === FIN {nombre} === */"


def _tramos(texto: str, nombre: str) -> tuple[int, int, str]:
    """Posicion del bloque y su contenido, marcadores aparte."""
    ini, fin = _marcadores(nombre)
    a = texto.find(ini)
    b = texto.find(fin)
    if a < 0 or b < 0:
        raise ErrorEditor(
            f"No encuentro los marcadores de {nombre} en {CROQUIS.name}.\n"
            f"Tienen que estar estas dos lineas, y no se pueden borrar:\n"
            f"    {ini}\n    {fin}")
    if b < a:
        raise ErrorEditor(f"Los marcadores de {nombre} estan al reves.")
    return a, b, texto[a + len(ini):b]


def _valor(cuerpo: str, nombre: str):
    """El array de dentro del bloque, leido como JSON.

    El bloque es JavaScript, pero un array de numeros y textos con comillas
    dobles es JSON valido, asi que se lee con json en vez de con expresiones
    regulares. Un fallo de sintaxis aqui se convierte en un mensaje claro en
    lugar de en un croquis a medias.
    """
    a, b = cuerpo.find("["), cuerpo.rfind("]")
    if a < 0 or b < a:
        raise ErrorEditor(f"El bloque de {nombre} no tiene ningun array dentro.")
    return _json(cuerpo[a:b + 1], nombre)


def _objeto(cuerpo: str, nombre: str):
    """El objeto de dentro del bloque, leido como JSON. Para PROPIOS."""
    a, b = cuerpo.find("{"), cuerpo.rfind("}")
    if a < 0 or b < a:
        raise ErrorEditor(f"El bloque de {nombre} no tiene ningun objeto dentro.")
    return _json(cuerpo[a:b + 1], nombre)


def _json(trozo: str, nombre: str):
    try:
        return json.loads(trozo)
    except json.JSONDecodeError as e:
        raise ErrorEditor(
            f"El bloque de {nombre} no se puede leer como JSON: {e}.\n"
            f"Si lo has editado a mano, revisa comas y comillas.") from None


def leer_croquis() -> dict:
    """Las zonas, los iconos y el encuadre por defecto que hay ahora mismo."""
    if not CROQUIS.is_file():
        raise ErrorEditor(f"No existe {CROQUIS}.")
    texto = CROQUIS.read_text(encoding="utf-8")
    _, _, cuerpo_zonas = _tramos(texto, "ZONAS")
    _, _, cuerpo_iconos = _tramos(texto, "ICONOS")
    _, _, cuerpo_propios = _tramos(texto, "PROPIOS")
    vista = re.search(r"var VISTA = \[([-\d,\s]+)\]", texto)
    mapa = re.search(r'<image[^>]+href="([^"]+)"', texto)
    return {
        "zonas": _valor(cuerpo_zonas, "ZONAS"),
        "iconos": _valor(cuerpo_iconos, "ICONOS"),
        "propios": _objeto(cuerpo_propios, "PROPIOS"),
        "vista": [int(v) for v in vista.group(1).split(",")] if vista else [0, 0, ANCHO, ALTO],
        "mapa": mapa.group(1) if mapa else "rectoria.webp",
    }


def formas_simbolos() -> dict:
    """Las formas SVG de los iconos, leidas del propio croquis.

    El editor dibuja la paleta con esto y no con una copia propia, para que no
    haya dos listas de iconos: lo que se ve en la paleta es exactamente lo que
    el croquis va a dibujar.

    Los simbolos estan escritos como trozos de texto encadenados con +, para
    que las lineas no se hagan kilometricas. Aqui se vuelven a pegar. Si
    alguien reformatea ese bloque y la lectura falla, se avisa en vez de
    dejar la paleta vacia sin decir por que.
    """
    texto = CROQUIS.read_text(encoding="utf-8")
    _, _, cuerpo = _tramos(texto, "SIMBOLOS")
    formas = {}
    for clave, trozos in re.findall(
            r"^\s*(\w+):\s*((?:\s*'[^']*'\s*\+?)+)", cuerpo, flags=re.M):
        formas[clave] = "".join(re.findall(r"'([^']*)'", trozos))
    if not formas:
        raise ErrorEditor(
            "No se pudo leer ningun simbolo del bloque SIMBOLOS de croquis.html.\n"
            "Cada uno tiene que verse asi, en una linea que empiece por su nombre:\n"
            "    bano: '<circle .../>' + '<path .../>',")
    return formas


def tipos_coinciden(formas: dict) -> list[str]:
    """Avisa si la lista de simbolos del croquis y la de validar.py se separaron.

    Son dos listas que tienen que decir lo mismo: validar.py decide que tipos
    se pueden guardar y croquis.html sabe dibujarlos. Si se separan, se puede
    guardar un icono que luego no se dibuja, y eso no da ningun error.
    """
    faltan_en_croquis = sorted(set(SIMBOLOS) - set(formas))
    sobran_en_croquis = sorted(set(formas) - set(SIMBOLOS))
    avisos = []
    if faltan_en_croquis:
        avisos.append(
            "Estos tipos estan en editor/validar.py pero el croquis no sabe "
            "dibujarlos: " + ", ".join(faltan_en_croquis))
    if sobran_en_croquis:
        avisos.append(
            "El croquis dibuja estos tipos, pero validar.py no deja usarlos: "
            + ", ".join(sobran_en_croquis))
    return avisos


def _n(v) -> str:
    return str(int(round(float(v))))


def _texto_zonas(zonas: list) -> str:
    """El array de zonas, formateado como estaba: una zona por parrafo.

    Los puntos van pegados con coma y sin espacio ([[330,108],[592,108]], no
    [[330,108], [592,108]]) para que al guardar sin mover una zona su linea no
    cambie y el diff de git ensene solo lo que de verdad se toco.

    Los adornos solo se escriben cuando la zona tiene alguno. Una zona sin
    relleno, sin linea y sin animacion se escribe con sus cuatro campos de
    siempre, igual que antes de que los adornos existieran, asi que guardar sin
    tocar nada no ensucia el diff.
    """
    trozos = []
    for z in zonas:
        nombre, corto, poligono, desc = z[:4]
        pts = ",".join(f"[{_n(x)},{_n(y)}]" for x, y in poligono)
        cola = ""
        if len(z) > 4 and z[4]:
            cola = ", " + _texto_adornos(z[4])
        trozos.append(
            f"  [{json.dumps(nombre, ensure_ascii=False)}, "
            f"{json.dumps(corto, ensure_ascii=False)},\n"
            f"   [{pts}],\n"
            f"   {json.dumps(desc, ensure_ascii=False)}{cola}]")
    return "var ZONAS = [\n" + ",\n\n".join(trozos) + "\n];"


def _texto_adornos(adornos: dict) -> str:
    """El objeto de adornos de una zona, en el orden en que se lee.

    El orden es f, l, p, rd, a, b, m: primero lo que se ve (relleno y linea),
    despues como se pinta la linea (punteada y redondeo), y al final el
    movimiento. Se omite lo que no esta, para que una zona con solo un color
    ocupe lo minimo.
    """
    trozos = []
    for clave in ("f", "l"):
        if adornos.get(clave):
            trozos.append(f'"{clave}": {json.dumps(adornos[clave], ensure_ascii=False)}')
    if adornos.get("p"):
        trozos.append('"p": 1')
    if adornos.get("rd"):
        trozos.append(f'"rd": {round(float(adornos["rd"]), 2):g}')
    for clave in ("a", "b"):
        if adornos.get(clave):
            trozos.append(f'"{clave}": {json.dumps(adornos[clave], ensure_ascii=False)}')
    if adornos.get("m"):
        trozos.append(f'"m": {round(float(adornos["m"]), 2):g}')
    return "{" + ", ".join(trozos) + "}"


def _limpia_zonas(zonas: list) -> list:
    """Las zonas con los adornos ya limpios, y sin el quinto campo si sobra.

    Se limpia antes de validar y antes de escribir, por el mismo motivo que en
    los iconos: el editor manda lo que tiene en pantalla, que incluye los
    campos vacios de los formularios. Una zona a la que no se le ha puesto nada
    tiene que quedar exactamente como estaba.
    """
    salida = []
    for z in zonas:
        if not isinstance(z, (list, tuple)) or len(z) < 5:
            salida.append(z)
            continue
        adornos = limpiar_adornos(z[4])
        salida.append(list(z[:4]) + [adornos] if adornos else list(z[:4]))
    return salida


def _campos_icono(ic: dict) -> list[str]:
    """Los campos de un icono, en orden y solo los que hacen falta.

    El orden es t, x, y, n, s, r, a, m, c, i, u: de lo que mas se usa a lo que
    menos. Con nombres en vez de posiciones, el dia que haga falta un campo
    nuevo se añade al final y ningun icono guardado se entera.

    Se omite lo que vale por defecto, para que un icono normal ocupe una linea
    corta y el diff de git ensene lo que de verdad se toco.
    """
    partes = [f'"t": {json.dumps(ic.get("t", ""), ensure_ascii=False)}']
    if "x" in ic:
        partes.append(f'"x": {_n(ic["x"])}')
    if "y" in ic:
        partes.append(f'"y": {_n(ic["y"])}')
    if ic.get("n"):
        partes.append(f'"n": {json.dumps(ic["n"], ensure_ascii=False)}')
    if ic.get("s"):
        partes.append(f'"s": {_n(ic["s"])}')
    if ic.get("r"):
        partes.append(f'"r": {_n(ic["r"])}')
    if ic.get("a"):
        partes.append(f'"a": {json.dumps(ic["a"], ensure_ascii=False)}')
    # La intensidad se escribe con un decimal como mucho: 1.4 y no 1.3999999.
    # Y se omite cuando vale 1, que es lo normal.
    if ic.get("m") and float(ic["m"]) != INTENSIDAD:
        partes.append(f'"m": {round(float(ic["m"]), 2):g}')
    # El circulo solo se escribe cuando se quita. Se mira con `in` y no por
    # lo que valga, porque 0 es un valor legitimo y `if ic.get("c")` lo
    # tomaria por ausencia.
    if "c" in ic:
        partes.append(f'"c": {_n(ic["c"])}')
    if ic.get("i"):
        titulo, texto = ic["i"]
        partes.append('"i": [' + json.dumps(titulo, ensure_ascii=False)
                      + ", " + json.dumps(texto, ensure_ascii=False) + "]")
    # El boton con enlace, como [texto, direccion]. Va despues de `i` porque
    # sin la informacion no sirve de nada: el boton sale dentro de esa ventana.
    if ic.get("u"):
        texto, url = ic["u"]
        partes.append('"u": [' + json.dumps(texto, ensure_ascii=False)
                      + ", " + json.dumps(url, ensure_ascii=False) + "]")
    return partes


def _texto_iconos(iconos: list) -> str:
    """El array de iconos, un objeto por linea."""
    if not iconos:
        return "var ICONOS = [];"
    # Cada objeto en una linea, separados por coma. Si alguno es largo (los
    # que llevan informacion) la linea se pasa de ancho, pero partirla por
    # campos daria un archivo mucho mas largo y mas dificil de leer en
    # conjunto. Se prefiere la linea larga.
    return ("var ICONOS = [\n"
            + ",\n".join("  {" + ", ".join(_campos_icono(ic)) + "}" for ic in iconos)
            + "\n];")


def _texto_propios(propios: dict) -> str:
    """El objeto de iconos propios, con un nombre por linea.

    Cada imagen es una data URL larguisima que va en una sola linea, porque
    JSON no deja partir un texto. Se ordenan por nombre para que al guardar
    dos veces lo mismo el archivo salga igual.
    """
    if not propios:
        return "var PROPIOS = {};"
    lineas = [f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v)}"
              for k, v in sorted(propios.items())]
    return "var PROPIOS = {\n" + ",\n".join(lineas) + "\n};"


def preparar_icono(datos_url: str, nombre: str, ocupados: set,
                   lado: int = LADO_ICONO) -> tuple[str, str, bytes, str, list]:
    """Convierte una imagen subida en un icono listo para el croquis.

    Devuelve `(nombre, data URL, bytes para la biblioteca, extensión, quitado)`.

    Hay dos caminos y no se parecen en nada:

    - **Mapa de bits** (PNG, JPG, WebP, GIF, BMP): se recorta a lo que no es
      transparente, se encaja en un cuadro de lado x lado sin deformarlo, se
      reduce a 160 px y se guarda en PNG. Con el cuadro y el recorte, una
      imagen con margenes de sobra ocupa el icono entero, y una foto alargada
      no sale aplastada.

    - **Vector** (SVG): no se toca el dibujo. Solo se limpia de lo que un icono
      no necesita y se guarda tal cual. Reducir un SVG seria destruir
      justamente lo que lo hace bueno: los iconos del mapa se amplian hasta
      cuatro veces con el zoom, y un vector no se pixela.

    `quitado` es la lista de lo que se le quito al SVG, para poder decirlo. En
    un mapa de bits va vacia.
    """
    if not isinstance(datos_url, str):
        raise ErrorEditor("Falta la imagen.")
    trozo = re.match(r"data:image/[a-z0-9.+-]+;base64,(.+)$",
                     datos_url, re.S | re.I)
    if not trozo:
        raise ErrorEditor(
            "Eso no es una imagen. Sirven PNG, JPG, WebP, GIF, BMP y SVG.")
    try:
        crudo = base64.b64decode(trozo.group(1), validate=False)
    except (ValueError, TypeError):
        raise ErrorEditor("La imagen viene mal codificada.") from None
    if len(crudo) > 12_000_000:
        raise ErrorEditor("La imagen pasa de 12 MB. Súbela más pequeña.")

    # El SVG se reconoce por el contenido y no por la extension ni por el tipo
    # que declara el navegador, que los dos mienten.
    if vector.parece_svg(crudo):
        return _preparar_vector(crudo, nombre, ocupados)

    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ErrorEditor(
            "Hace falta Pillow para preparar las imagenes.\n"
            "En el equipo del proyecto ya esta: usa .venv\\Scripts\\python.exe") from None

    try:
        with Image.open(io.BytesIO(crudo)) as original:
            original.load()
            # Los moviles guardan la orientacion en los metadatos, no en los
            # pixeles: sin esto, una foto vertical sale tumbada.
            imagen = ImageOps.exif_transpose(original).convert("RGBA")
    except Exception:
        raise ErrorEditor(
            "No se pudo abrir la imagen. Prueba a guardarla como PNG, JPG o SVG.") from None

    # Fuera los margenes vacios: una imagen con mucho aire alrededor saldria
    # diminuta dentro del circulo.
    caja = imagen.getbbox()
    if caja:
        imagen = imagen.crop(caja)

    imagen.thumbnail((lado, lado), Image.LANCZOS)
    lienzo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    lienzo.paste(imagen, ((lado - imagen.width) // 2, (lado - imagen.height) // 2),
                 imagen)

    guardado = io.BytesIO()
    lienzo.save(guardado, "PNG", optimize=True)
    png = guardado.getvalue()
    salida = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    if len(salida) > MAX_ICONO:
        raise ErrorEditor(
            f"La imagen queda en {len(salida) // 1024} KB y el tope son "
            f"{MAX_ICONO // 1024} KB. Prueba con una más sencilla o más pequeña, "
            f"o súbela en SVG: un vector pesa poco y no se pixela.")

    return _nombre_libre(nombre, ocupados), salida, png, "png", []


def _preparar_vector(crudo: bytes, nombre: str,
                     ocupados: set) -> tuple[str, str, bytes, str, list]:
    """El camino del SVG: limpiarlo y guardarlo tal cual, sin reducir."""
    try:
        limpio, quitado = vector.prepara(crudo)
    except vector.SvgInvalido as e:
        raise ErrorEditor(str(e)) from None

    salida = vector.a_data_url(limpio)
    if len(salida) > MAX_VECTOR:
        raise ErrorEditor(
            f"El SVG queda en {len(salida) // 1024} KB y el tope son "
            f"{MAX_VECTOR // 1024} KB. Súbelo más simple.")

    return _nombre_libre(nombre, ocupados), salida, limpio.encode("utf-8"), "svg", quitado


def guarda_en_biblioteca(nombre: str, contenido: bytes, extension: str,
                         ajustes: dict) -> None:
    """Deja el icono preparado en la biblioteca del editor, con sus ajustes.

    Se guarda el archivo ya preparado —el PNG recortado y reducido, o el SVG
    limpiado—, no lo que subio el usuario: asi volver a poner el icono es
    instantaneo y no hay que repetir el trabajo. Vive fuera de git, como el
    respaldo: el croquis ya lleva dentro las imagenes que usa, y esto es solo
    la despensa.

    Los ajustes van en un JSON al lado. Son el tamano, la animacion y el
    circulo con los que se configuro al subirlo: lo que hace que al volver a
    poner ese icono salga como se dejo, y no con los valores de fabrica.
    """
    BIBLIOTECA.mkdir(exist_ok=True)
    (BIBLIOTECA / f"{nombre}.{extension}").write_bytes(contenido)
    (BIBLIOTECA / f"{nombre}.json").write_text(
        json.dumps(ajustes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Los archivos que puede tener un icono en la biblioteca. El PNG y el SVG son
# el mismo icono en dos formatos distintos: si se sube uno encima del otro, el
# nuevo reemplaza al viejo en vez de quedarse los dos.
EXTENSIONES = ("png", "svg")


def _archivo_de(nombre: str) -> Path | None:
    """La ruta del icono en la biblioteca, busque donde busque. None si no esta."""
    for ext in EXTENSIONES:
        ruta = BIBLIOTECA / f"{nombre}.{ext}"
        if ruta.is_file():
            return ruta
    return None


def _ajustes_de(nombre: str) -> dict:
    """Los ajustes guardados de un icono de la biblioteca. Vacio si no hay.

    Si el JSON esta roto se devuelve vacio en vez de fallar: unos ajustes que
    no se pueden leer no son motivo para no poder usar el icono, que es lo que
    de verdad importa.
    """
    ruta = BIBLIOTECA / f"{nombre}.json"
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return datos if isinstance(datos, dict) else {}


def lista_biblioteca(propios: dict) -> list[dict]:
    """Los iconos guardados que ahora mismo NO estan en el croquis.

    Los que ya estan no se listan: aparecen en la paleta, y ofrecerlos otra
    vez en dos sitios distintos solo confunde.

    Cada uno lleva sus ajustes y si es vector, para que la lista pueda decir
    con que se configuro y al recuperarlo vuelvan.
    """
    if not BIBLIOTECA.is_dir():
        return []
    fuera = []
    for ext in EXTENSIONES:
        for ruta in sorted(BIBLIOTECA.glob(f"*.{ext}")):
            if ruta.stem in propios:
                continue
            # Un nombre puede tener el PNG y el SVG a la vez si se subieron
            # los dos. Se enseña una vez, con el que se vaya a usar: el SVG,
            # que se ve mejor a cualquier tamaño.
            if any(o["nombre"] == ruta.stem for o in fuera):
                continue
            fuera.append({"nombre": ruta.stem, "bytes": ruta.stat().st_size,
                          "vector": ext == "svg",
                          "ajustes": _ajustes_de(ruta.stem)})
    return sorted(fuera, key=lambda o: o["nombre"])


def lee_de_biblioteca(nombre: str) -> dict:
    """Lo que hace falta para volver a poner un icono de la biblioteca."""
    if not NOMBRE_PROPIO.fullmatch(nombre or ""):
        raise ErrorEditor(f"«{nombre}» no es un nombre de icono valido.")
    ruta = _archivo_de(nombre)
    if ruta is None:
        raise ErrorEditor(f"En la biblioteca no hay ningun icono «{nombre}».")
    datos = ruta.read_bytes()
    es_vector = ruta.suffix.lower() == ".svg"
    tope = MAX_VECTOR if es_vector else MAX_ICONO
    # El data URL ocupa mas que el archivo, asi que se comprueba el data URL.
    if es_vector:
        url = vector.a_data_url(datos.decode("utf-8"))
    else:
        url = "data:image/png;base64," + base64.b64encode(datos).decode("ascii")
    if len(url) > tope:
        raise ErrorEditor(
            f"«{nombre}» ocupa {len(url) // 1024} KB y el tope son "
            f"{tope // 1024} KB, asi que no cabe en el croquis.")
    return {"datos": url, "vector": es_vector, "ajustes": _ajustes_de(nombre)}


def borra_de_biblioteca(nombre: str) -> None:
    """Quita un icono de la biblioteca, con sus ajustes. No toca el croquis.

    Se llevan tanto el PNG como el SVG: si el mismo nombre tuviera los dos,
    borrar solo uno dejaria el icono a medias.
    """
    if not NOMBRE_PROPIO.fullmatch(nombre or ""):
        raise ErrorEditor(f"«{nombre}» no es un nombre de icono valido.")
    for ext in (*EXTENSIONES, "json"):
        ruta = BIBLIOTECA / f"{nombre}.{ext}"
        if ruta.is_file():
            ruta.unlink()


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
# Un modelo es un icono guardado entero menos la posicion. Se estampa en el
# mapa tal cual, con su tamano, su giro, su animacion, su circulo y su
# informacion. Es lo que hace que poner veinte puestos de comida iguales sea
# veinte clics y no veinte veces de configurarlos a mano.
def lee_modelos() -> list:
    """Los modelos guardados. Lista vacia si todavia no hay ninguno."""
    if not MODELOS.is_file():
        return []
    try:
        datos = json.loads(MODELOS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ErrorEditor(
            f"El archivo de modelos ({MODELOS.name}) no se puede leer: {e}.\n"
            f"Si lo has editado a mano, revisa las comas y las comillas. "
            f"Puedes borrarlo para empezar de cero: no toca el croquis.") from None
    return datos if isinstance(datos, list) else []


def _escribe_modelos(modelos: list) -> None:
    """Guarda los modelos. Es lo unico que escribe este archivo."""
    MODELOS.write_text(json.dumps(modelos, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")


def guarda_modelo(nombre: str, icono: dict, propios: dict) -> dict:
    """Añade un modelo, o reemplaza el que tenga el mismo nombre.

    Reemplazar en vez de acumular es lo que uno espera al volver a guardar con
    el mismo nombre («Puesto de comida» de antes pasa a ser el de ahora). Si
    se acumularan, la lista se llenaria de variantes y no se sabria cual es la
    buena.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorEditor("El modelo necesita un nombre.")
    if len(nombre) > MAX_NOMBRE_MODELO:
        raise ErrorEditor(f"El nombre pasa de {MAX_NOMBRE_MODELO} caracteres.")

    if not isinstance(icono, dict):
        raise ErrorEditor("No hay ningún icono que guardar.")
    # La posicion se elige al estampar, asi que no se guarda.
    limpio = {k: v for k, v in icono.items() if k not in ("x", "y")}

    modelos = [m for m in lee_modelos()
               if not (isinstance(m, dict)
                       and str(m.get("nombre", "")).strip().lower() == nombre.lower())]
    modelos.append({"nombre": nombre, "i": limpio})

    problemas = revisar_modelos(modelos, propios)
    if problemas:
        raise ErrorEditor("\n".join(problemas))
    _escribe_modelos(modelos)
    return {"nombre": nombre, "modelos": len(modelos)}


def borra_modelo(nombre: str, propios: dict) -> dict:
    """Quita un modelo por su nombre."""
    modelos = lee_modelos()
    quedan = [m for m in modelos
              if not (isinstance(m, dict)
                      and str(m.get("nombre", "")).strip().lower()
                      == (nombre or "").strip().lower())]
    if len(quedan) == len(modelos):
        raise ErrorEditor(f"No hay ningún modelo que se llame «{nombre}».")
    _escribe_modelos(quedan)
    return {"quitados": len(modelos) - len(quedan), "modelos": len(quedan)}


def _nombre_libre(nombre: str, ocupados: set) -> str:
    """Un nombre de icono utilizable: minusculas, numeros y guiones.

    Si ya esta cogido se le anade un numero, en vez de pisar el que hubiera:
    el usuario puede subir dos veces el mismo archivo sin darse cuenta, y
    perder el primero seria una sorpresa desagradable.
    """
    base = re.sub(r"[^a-z0-9]+", "-", (nombre or "").lower()).strip("-")
    # Sin extension: "logo-uabc.png" -> "logo-uabc".
    base = base[:24].strip("-") or "icono"
    if not NOMBRE_PROPIO.fullmatch(base):
        base = (base + "-icono")[:24]
    candidato, n = base, 1
    while candidato in ocupados or not NOMBRE_PROPIO.fullmatch(candidato):
        n += 1
        sufijo = f"-{n}"
        candidato = base[:24 - len(sufijo)] + sufijo
    return candidato


def exige_codigo_al_dia() -> None:
    """Corta el guardado si el proceso arranco antes del ultimo cambio.

    No es una precaucion teorica: es lo que hizo que el redondeo de las
    esquinas se perdiera sin dejar rastro. Guardar con el codigo de antes no
    falla, guarda menos, y eso es lo peligroso: el archivo sale bien formado y
    sin lo que ese codigo no conoce.
    """
    if huella_del_codigo() != HUELLA_ARRANQUE:
        raise ErrorEditor(
            "El editor quedó viejo: se abrió antes del último cambio de código, "
            "así que guardaría a medias lo que todavía no conoce.\n\n"
            "Cierra esta pestaña y vuelve a arrancar editor/editor.py. "
            "No se ha perdido nada: el croquis sigue como estaba.")


def guardar_croquis(zonas: list, iconos: list, propios: dict) -> dict:
    """Valida y escribe las zonas, los iconos y los iconos propios.

    Deja una copia de seguridad antes de tocar nada, y si algo no cuadra no
    escribe NADA: ni las zonas, ni los iconos, ni las imagenes. A medias
    seria peor que no escribir, porque el croquis quedaria publicado con la
    mitad del cambio y sin forma de saber cual falta.

    Los adornos de las zonas se limpian antes de validar: lo que llega del
    editor trae los campos vacios de los formularios, y una zona sin adornos
    tiene que quedar escrita igual que antes de que existieran.

    Lo primero de todo es mirar que este proceso no sea mas viejo que el
    codigo: un editor abierto antes del ultimo cambio guardaria a medias y sin
    decir nada. Se mira aqui y no en la ruta HTTP para que no haya ninguna
    forma de escribir el croquis que se salte la comprobacion.
    """
    exige_codigo_al_dia()
    zonas = _limpia_zonas(zonas)
    problemas = revisar(zonas, iconos, propios)
    if problemas:
        raise ErrorEditor("\n".join(problemas))

    texto = CROQUIS.read_text(encoding="utf-8")

    # Una copia antes de tocar nada. Git ya es un respaldo, pero esta esta a
    # mano y no hay que saber git para encontrarla.
    RESPALDO.mkdir(exist_ok=True)
    (RESPALDO / "croquis.html").write_text(texto, encoding="utf-8")

    bloques = (("ZONAS", _texto_zonas(zonas)),
               ("ICONOS", _texto_iconos(iconos)),
               ("PROPIOS", _texto_propios(propios)))
    for nombre, cuerpo in bloques:
        a, b, _ = _tramos(texto, nombre)
        ini, fin = _marcadores(nombre)
        texto = texto[:a] + ini + "\n" + cuerpo + "\n" + fin + texto[b + len(fin):]

    CROQUIS.write_text(texto, encoding="utf-8")
    return {"zonas": len(zonas), "iconos": len(iconos), "propios": len(propios)}


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
def git(*argumentos: str) -> subprocess.CompletedProcess:
    """Ejecuta git en la raiz del proyecto."""
    return subprocess.run(
        ["git", *argumentos], cwd=str(RAIZ), capture_output=True,
        text=True, encoding="utf-8", errors="replace")


def _salida(r: subprocess.CompletedProcess) -> str:
    return ((r.stdout or "") + (r.stderr or "")).strip()


def estado_git() -> dict:
    """Lo que hace falta para el boton de subir: rama, pendientes y si hay git."""
    if not shutil.which("git"):
        return {"hay": False, "error": "git no esta instalado o no esta en el PATH"}
    if not (RAIZ / ".git").is_dir():
        return {"hay": False, "error": f"{RAIZ} no es un repositorio de git"}

    rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if rama.returncode != 0:
        return {"hay": False, "error": _salida(rama)}

    pendientes = git("status", "--porcelain")
    delante = git("rev-list", "--count", "@{u}..HEAD")
    detras = git("rev-list", "--count", "HEAD..@{u}")
    siguiente = git("log", "-1", "--pretty=%s")
    return {
        "hay": True,
        "rama": (rama.stdout or "").strip(),
        "pendientes": len([l for l in (pendientes.stdout or "").splitlines() if l.strip()]),
        "sinSubir": int((delante.stdout or "0").strip() or 0),
        "sinBajar": int((detras.stdout or "0").strip() or 0),
        "ultimo": (siguiente.stdout or "").strip(),
        "detalle": (pendientes.stdout or "").strip(),
    }


def subir(mensaje: str) -> dict:
    """git add, commit y push. Cuenta lo que paso en cada paso.

    El push se hace aqui y no se deja para despues porque es justo lo que se
    pidio: que al guardar desde el editor la pagina publicada quede al dia.
    Si el push falla (red, permisos), el commit local ya esta hecho y se
    puede reintentar sin perder nada.
    """
    pasos = []
    cambios = git("status", "--porcelain")
    if not (cambios.stdout or "").strip():
        return {"ok": True, "pasos": pasos,
                "mensaje": "No hay nada que subir: el repositorio esta limpio."}

    anadir = git("add", "-A")
    pasos.append(("git add -A", _salida(anadir) or "ok"))
    if anadir.returncode != 0:
        return {"ok": False, "pasos": pasos, "mensaje": "No se pudo preparar el cambio."}

    commit = git("commit", "-m", mensaje)
    pasos.append(("git commit", _salida(commit) or "ok"))
    if commit.returncode != 0:
        return {"ok": False, "pasos": pasos,
                "mensaje": "El commit fallo. Arriba esta lo que dijo git."}

    push = git("push")
    pasos.append(("git push", _salida(push) or "ok"))
    if push.returncode != 0:
        return {"ok": False, "pasos": pasos, "commitHecho": True,
                "mensaje": "El commit quedo hecho, pero el push no subio.\n"
                           "El cambio esta a salvo en tu equipo: vuelve a "
                           "pulsar Subir para reintentarlo."}

    return {"ok": True, "pasos": pasos, "commitHecho": True,
            "mensaje": "Subido. GitHub Pages tarda uno o dos minutos en "
                       "reconstruir; despues el QR ya abre la version nueva."}


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
class Manejador(BaseHTTPRequestHandler):
    server_version = "EditorCroquis"

    # Si una peticion se queda a medias (el navegador manda las cabeceras y se
    # corta, o el cuerpo no llega entero), el hilo se quedaba esperando en
    # read() para siempre. Con esto la conexion se corta sola y el hilo se
    # libera. Paso de verdad: un dialogo del navegador congelo la pestana a
    # mitad de un guardado y el hilo se quedo colgado.
    timeout = 30

    def log_message(self, formato: str, *args) -> None:  # noqa: A003
        # El log por defecto llena la consola de cada imagen y cada sondeo.
        # Solo interesa lo que el usuario provoca.
        if self.path.startswith("/api/") and not self.path.endswith("/estado"):
            sys.stderr.write(f"  {self.command} {self.path}\n")

    # -- utilidades ---------------------------------------------------------
    def _host_local(self) -> bool:
        """Solo se atiende a quien llame por localhost.

        Sin esto, una pagina web abierta en este equipo puede apuntar un
        dominio propio a 127.0.0.1 y usar el navegador como puente para
        escribir en el croquis. El Host delata el intento: llegaria con el
        nombre del dominio, no con localhost.
        """
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in HOSTS_LOCALES

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, datos, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self._responder(codigo, cuerpo, "application/json; charset=utf-8")

    def _error(self, mensaje: str, codigo: int = 400) -> None:
        self._json({"ok": False, "mensaje": mensaje}, codigo)

    def _archivo(self, ruta: Path, tipo: str) -> None:
        if not ruta.is_file():
            self._error(f"No existe {ruta.name} en el proyecto.", 404)
            return
        self._responder(200, ruta.read_bytes(), tipo)

    def _cuerpo_json(self) -> dict:
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErrorEditor("Content-Length ilegible.") from None
        # El tope es alto porque subir un icono manda la imagen entera en
        # base64, que engorda un tercio. Lo que se acepta de verdad lo decide
        # preparar_icono, que ya mira el tamano de la imagen decodificada.
        if largo <= 0 or largo > 18_000_000:
            raise ErrorEditor("El cuerpo de la peticion no tiene un tamano razonable.")
        crudo = self.rfile.read(largo)
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ErrorEditor(f"El cuerpo no es JSON valido: {e}") from None

    # -- rutas --------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_local():
            self._error("Esta herramienta solo atiende desde localhost.", 403)
            return
        ruta = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if ruta in ("/", "/editor.html"):
                self._archivo(EDITOR_HTML, "text/html; charset=utf-8")
            elif ruta == "/mapa":
                # La misma imagen que usa el croquis publicado. Se sirve desde
                # aqui y no desde la web para poder trabajar sin conexion y
                # para no depender de que Pages ya haya reconstruido.
                self._archivo(MAPA, "image/webp")
            elif ruta == "/api/estado":
                datos = leer_croquis()
                formas = formas_simbolos()
                datos["simbolos"] = SIMBOLOS
                datos["formas"] = formas
                datos["avisos"] = tipos_coinciden(formas)
                datos["ancho"], datos["alto"] = ANCHO, ALTO
                datos["topes"] = {"tam": [MIN_TAM_ICONO, MAX_TAM_ICONO],
                                  "rot": [MIN_ROT, MAX_ROT],
                                  "inte": [MIN_INTENSIDAD, MAX_INTENSIDAD],
                                  "lado": LADO_ICONO, "boton": MAX_BOTON,
                                  "url": MAX_URL, "redondeo": MAX_REDONDEO,
                                  "titulo": MAX_TITULO, "texto": MAX_TEXTO,
                                  "totalPropios": MAX_ICONOS_PROPIOS}
                datos["animaciones"] = ANIMACIONES
                datos["sinIntensidad"] = sorted(ANIMACIONES_SIN_INTENSIDAD)
                # Las animaciones de las zonas, que son otras: la de la zona
                # mueve el relleno y la linea, y la del borde solo la linea.
                # Las manda el servidor por el mismo motivo que las de los
                # iconos: es el que valida, y dos listas separadas acabarian
                # diciendo cosas distintas.
                datos["animacionesZona"] = ANIMACIONES_ZONA
                datos["animacionesBorde"] = ANIMACIONES_BORDE
                # Si este proceso arranco antes del ultimo cambio de codigo, la
                # pagina lo dice y apaga el boton de guardar. Es la unica señal
                # que puede dar: desde dentro, un editor viejo y uno al dia
                # responden exactamente igual.
                datos["codigoViejo"] = huella_del_codigo() != HUELLA_ARRANQUE
                datos["biblioteca"] = lista_biblioteca(datos["propios"])
                # Los ajustes de cada icono propio, para que la paleta los
                # dibuje como son y al ponerlos salgan ya configurados.
                datos["ajustesPropios"] = {
                    n: _ajustes_de(n) for n in datos["propios"]}
                # Y cuales son vectores: un SVG no se pixela al ampliarlo y un
                # PNG si, y eso se ve en la paleta.
                datos["vectores"] = {
                    n: (_archivo_de(n) or Path("")).suffix.lower() == ".svg"
                    for n in datos["propios"]}
                datos["modelos"] = lee_modelos()
                datos["git"] = estado_git()
                datos["publicado"] = "https://tonycabreram.github.io/OrgulloCimarron/plantilla/croquis.html"
                self._json(datos)
            elif ruta == "/api/git":
                self._json(estado_git())
            elif ruta == "/api/biblioteca":
                # Solo la lista: los PNG que hay guardados y no estan en el
                # croquis. El contenido se pide aparte, con POST, para no
                # mandar medio mega de imagenes cada vez que se pinta el panel.
                self._json({"biblioteca": lista_biblioteca(leer_croquis()["propios"])})
            elif ruta == "/api/modelos":
                self._json({"modelos": lee_modelos()})
            else:
                self._error("Esa direccion no existe en el editor.", 404)
        except ErrorEditor as e:
            self._error(str(e))

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_local():
            self._error("Esta herramienta solo atiende desde localhost.", 403)
            return
        ruta = self.path.split("?")[0].rstrip("/")
        try:
            datos = self._cuerpo_json()
            if ruta == "/api/guardar":
                zonas, iconos = datos.get("zonas"), datos.get("iconos")
                propios = datos.get("propios")
                if not isinstance(zonas, list) or not isinstance(iconos, list):
                    raise ErrorEditor("Faltan las zonas o los iconos.")
                if propios is None:
                    propios = {}
                if not isinstance(propios, dict):
                    raise ErrorEditor("Los iconos propios tienen que ser un diccionario.")
                self._json({"ok": True,
                            "guardado": guardar_croquis(zonas, iconos, propios),
                            "git": estado_git()})
            elif ruta == "/api/icono":
                nombre, imagen, contenido, extension, quitado = preparar_icono(
                    datos.get("datos"), str(datos.get("nombre") or ""),
                    set(SIMBOLOS) | set(datos.get("existentes") or []))
                # Los ajustes se validan antes de guardar nada: unos ajustes
                # malos no se notan al guardarlos, sino al estampar con ellos.
                ajustes = limpiar_ajustes(datos.get("ajustes") or {})
                problemas = revisar_ajustes(ajustes)
                if problemas:
                    raise ErrorEditor("\n".join(problemas))
                # Se guarda en la biblioteca ademas de mandarlo: asi se puede
                # volver a poner mas adelante sin buscar la imagen otra vez, y
                # con los ajustes que se le pusieron.
                guarda_en_biblioteca(nombre, contenido, extension, ajustes)
                self._json({"ok": True, "nombre": nombre, "datos": imagen,
                            "bytes": len(imagen), "ajustes": ajustes,
                            "vector": extension == "svg", "quitado": quitado})
            elif ruta == "/api/biblioteca":
                # Recuperar un icono guardado, o quitarlo de la despensa.
                if datos.get("quitar"):
                    borra_de_biblioteca(str(datos["quitar"]))
                    self._json({"ok": True, "mensaje": "Quitado de la biblioteca.",
                                "biblioteca": lista_biblioteca(leer_croquis()["propios"])})
                else:
                    nombre = str(datos.get("nombre") or "")
                    self._json(dict({"ok": True, "nombre": nombre},
                                    **lee_de_biblioteca(nombre)))
            elif ruta == "/api/modelos":
                # Guardar un modelo, o quitarlo.
                #
                # Los modelos NO van dentro del croquis, asi que no hace falta
                # pulsar Guardar despues: su archivo es suyo y se escribe
                # aqui mismo. Es lo contrario de los iconos, que si son
                # contenido del mapa y esperan al Guardar.
                propios = leer_croquis()["propios"]
                if datos.get("quitar"):
                    quitado = borra_modelo(str(datos["quitar"]), propios)
                    self._json({"ok": True, "modelos": lee_modelos(),
                                "quitado": quitado})
                else:
                    guardado = guarda_modelo(str(datos.get("nombre") or ""),
                                             datos.get("icono"), propios)
                    self._json({"ok": True, "guardado": guardado,
                                "modelos": lee_modelos()})
            elif ruta == "/api/subir":
                mensaje = str(datos.get("mensaje") or "").strip()
                if not mensaje:
                    raise ErrorEditor("Falta el mensaje del commit.")
                if len(mensaje) > 200:
                    raise ErrorEditor("El mensaje del commit es demasiado largo.")
                if "\n" in mensaje:
                    raise ErrorEditor("El mensaje del commit va en una sola linea.")
                self._json(subir(mensaje), 200)
            else:
                self._error("Esa direccion no existe en el editor.", 404)
        except ErrorEditor as e:
            self._error(str(e))


def puerto_libre(desde: int, intentos: int = 10) -> int:
    """El primer puerto libre a partir de `desde`."""
    for p in range(desde, desde + intentos):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
            return p
    raise SystemExit(f"No hay ningun puerto libre entre {desde} y {desde + intentos}.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Editor local del croquis del Dia del Orgullo Cimarron. "
                    "Abre el navegador en una direccion que solo funciona en este equipo.")
    ap.add_argument("--puerto", type=int, default=8730,
                    help="puerto a usar (si esta ocupado, se prueba el siguiente)")
    ap.add_argument("--no-abrir", action="store_true",
                    help="no abrir el navegador automaticamente")
    args = ap.parse_args()

    for imprescindible in (CROQUIS, MAPA, EDITOR_HTML):
        if not imprescindible.is_file():
            print(f"Falta {imprescindible}.")
            return 1

    puerto = puerto_libre(args.puerto)
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    url = f"http://127.0.0.1:{puerto}/"

    print()
    print("  Editor del croquis · Dia del Orgullo Cimarron 2026")
    print("  " + "-" * 52)
    print(f"  Abierto en      {url}")
    print(f"  Modifica        {CROQUIS.relative_to(RAIZ)}")
    print(f"  Copia de seg.   {RESPALDO.relative_to(RAIZ)}\\croquis.html")
    print()
    print("  Solo funciona en este equipo. Para cerrarlo, Ctrl+C.")
    print("  Esto no se publica: el croquis que abre el QR sigue siendo")
    print("  de solo lectura.")
    print()

    if not args.no_abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrado. El croquis no cambio si no pulsaste Guardar.\n")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
