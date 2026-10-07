"""
Pruebas del generador de QR con HTML embebido.

La lectura se hace con zxing-cpp, que es la libreria que usan los lectores de
movil. (OpenCV falla a partir de la version ~20 y no sirve para verificar esto.)
"""
from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import qrcode
import zxingcpp
from PIL import Image, ImageEnhance
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M

import generar_qr as g
from generar_qr import URL_HTML

# El editor vive en su propia carpeta y se ejecuta como script, asi que su
# carpeta tiene que estar en el path para poder importarlo desde aqui. Con
# ella dentro, "validar" y "editor" se resuelven solos.
sys.path.insert(0, str(Path(__file__).resolve().parent / "editor"))
import editor  # noqa: E402  (el servidor del editor)
import validar as v  # noqa: E402  (las reglas, compartidas con el editor)
import vector as vec  # noqa: E402  (los iconos en SVG)
from validar import MAX_ICONO, MAX_VECTOR  # noqa: E402

NIVELES = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "H": ERROR_CORRECT_H}


def leer_qr(ruta: Path) -> str:
    """Devuelve el texto codificado en el QR, o cadena vacia si no se lee."""
    with Image.open(ruta) as imagen:
        resultado = zxingcpp.read_barcode(imagen)
    return resultado.text if resultado else ""


def escanear_texto(texto: str, nivel: str, box: int) -> bool:
    """Codifica, escribe y relee un QR para comprobar que un lector lo resuelve."""
    codigo = qrcode.QRCode(error_correction=NIVELES[nivel], box_size=box, border=4)
    codigo.add_data(texto)
    codigo.make(fit=True)
    ruta = Path("_tmp_qr.png")
    codigo.make_image().save(ruta)
    try:
        return leer_qr(ruta) == texto
    finally:
        ruta.unlink(missing_ok=True)


def decodificar(fragmento: str, comprimir: bool) -> str:
    """Vuelve del base64url (y del gzip) al HTML original."""
    crudo = base64.urlsafe_b64decode(fragmento + "=" * (-len(fragmento) % 4))
    if comprimir:
        crudo = gzip.decompress(crudo)
    return crudo.decode("utf-8")


def ejecutar_main(*argumentos: str) -> int:
    """Llama a g.main() en silencio y devuelve su codigo de salida."""
    original = sys.argv
    try:
        sys.argv = ["generar_qr.py", *argumentos]
        with contextlib.redirect_stdout(io.StringIO()):
            return g.main()
    finally:
        sys.argv = original


def test_ronda_completa() -> bool:
    """HTML survives: generar -> PNG -> leer -> decodificar el fragmento.

    Se recorren los dos modos que llevan el HTML dentro, porque ahi el QR no
    siempre tiene la misma forma. Se usa el documento de ejemplo y no el
    croquis: el croquis es bonito pero grande, y en estos modos tiene que
    caber entero en el QR. Lo que se comprueba aqui es el mecanismo
    (empaquetar, leer, descomprimir), no que quepa un documento concreto.
    """
    origen = Path("plantilla/plantilla.html")
    crudo = origen.read_text(encoding="utf-8")
    salida = Path("_tmp_salida")
    salida.mkdir(exist_ok=True)
    try:
        for modo in ("servidor", "sin-servidor"):
            prefijo = salida / modo
            if ejecutar_main("--html", str(origen), "--salida", str(prefijo),
                             "--nivel", "L", "--modo", modo,
                             "--publicar-en", str(salida)) != 0:
                print(f"    (el HTML no cupo en modo {modo})")
                return False
            texto = leer_qr(prefijo.with_suffix(".png"))
            if not texto:
                print(f"    (el lector no pudo leer el QR en modo {modo})")
                return False
            if modo == "servidor" and not texto.startswith(g.URL_BASE + "#"):
                print(f"    (el QR no apunta a la pagina base: {texto[:40]!r})")
                return False
            if modo == "sin-servidor" and not texto.startswith("javascript:"):
                print(f"    (el QR no es un javascript: {texto[:40]!r})")
                return False
            fragmento = g.extraer_fragmento(texto)
            esperado = prefijo.with_suffix(".html").read_text(encoding="utf-8")
            if decodificar(fragmento, comprimir=True) != esperado:
                print(f"    (el HTML recuperado no coincide en modo {modo})")
                return False
    finally:
        shutil.rmtree(salida, ignore_errors=True)
    return True


def test_escaneo_de_un_movil() -> bool:
    """El flujo real de un movil: QR -> URL real -> pagina base -> documento.

    Es la prueba que importa. El modo 'servidor' es el unico que funciona en
    un telefono (Chrome en Android y Safari en iOS bloquean 'javascript:'), asi
    que se comprueba que la URL del QR sea una direccion http normal, que la
    pagina base publicada lea el fragmento, y que el documento salga entero.
    """
    origen = Path("plantilla/plantilla.html")
    salida = Path("_tmp_scan")
    salida.mkdir(exist_ok=True)
    nombre_base = Path(g.URL_BASE).name or "index.html"
    try:
        if ejecutar_main("--html", str(origen), "--salida", str(salida / "q"),
                         "--nivel", "L", "--modo", "servidor",
                         "--publicar-en", str(salida)) != 0:
            return False

        url = leer_qr(salida / "q.png")
        base, _, fragmento = url.partition("#")
        # 'base' es la parte anterior al '#', así que se compara con URL_BASE
        # a secas: compararlo con URL_BASE + '#' no puede coincidir nunca.
        if base != g.URL_BASE:
            print(f"    (el QR no apunta a la pagina base: {base[:60]!r}…)")
            return False
        if not fragmento:
            print("    (el QR no lleva fragmento)")
            return False
        # El fragmento jamas viaja al servidor: debe ser solo alfabeto seguro.
        if set(fragmento) - set(g.PESO):
            print("    (el fragmento tiene caracteres que rompen la URL)")
            return False

        # La pagina base es la que se publica: tiene que leer el hash y
        # reconstruir. Sin esto, escanear el QR no muestra nada. El generador
        # la nombra con el mismo nombre que tiene en la URL.
        pagina = (salida / nombre_base).read_text(encoding="utf-8")
        for pieza in ("location.hash.slice(1)", "DecompressionStream('gzip')", "atob"):
            if pieza not in pagina:
                print(f"    (la pagina base no usa {pieza})")
                return False
        # Sin esto, un segundo escaneo con la pagina ya abierta se queda en blanco.
        if "hashchange" not in pagina:
            print("    (la pagina base no escucha hashchange)")
            return False

        # Y el documento tiene que salir identico al original.
        if decodificar(fragmento, comprimir=True) != (salida / "q.html").read_text(encoding="utf-8"):
            print("    (el documento no se reconstruye igual)")
            return False
    finally:
        shutil.rmtree(salida, ignore_errors=True)
    return True


def test_url_publicada_responde() -> bool:
    """La URL que lleva el QR está viva y trae el documento.

    Sin esto se puede imprimir un QR que no abre nada. Requiere red; si no hay
    conexion se salta en vez de fallar, porque no es un fallo del codigo.
    """
    destino = Path(URL_HTML.rsplit("github.io/OrgulloCimarron/", 1)[-1])
    if not destino.is_file():
        print(f"    (URL_HTML apunta a {destino}, que no está en el repo)")
        return False
    marcador = destino.read_text(encoding="utf-8")
    try:
        peticion = urllib.request.Request(URL_HTML, headers={"User-Agent": "OrgulloCimarron-test"})
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", "replace")
            estado = respuesta.status
    except urllib.error.HTTPError as error:
        print(f"    (la URL devuelve {error.code}; GitHub Pages puede que esté")
        print("     reconstruyendo, o que el HTML no esté subido todavía)")
        return False
    except (urllib.error.URLError, OSError) as error:
        print(f"    (sin conexión a {URL_HTML}: {error.reason}; se omite)")
        return True
    if estado != 200:
        print(f"    (la URL devuelve {estado})")
        return False
    if "Día del Orgullo Cimarrón 2026" not in cuerpo:
        print("    (la URL responde, pero no es el documento del croquis)")
        return False
    # Que la publicada sea la de aqui es lo que hace que el QR sirva: si el
    # HTML local se cambio y no se subio, el QR abre una version vieja. No es
    # un fallo (se esta trabajando), pero conviene decirlo.
    #
    # Se comparan los saltos de linea normalizados. En Windows el archivo en
    # disco lleva CRLF y git (con core.autocrlf) guarda LF, asi que comparar
    # byte a byte daria una diferencia de un byte por linea. El contenido es
    # el mismo y avisar de eso seria un aviso que salta siempre.
    aqui = marcador.replace("\r\n", "\n")
    alla = cuerpo.replace("\r\n", "\n")
    if alla != aqui:
        print(f"    {URL_HTML} -> {estado}, {len(cuerpo)} bytes")
        print(f"    (ojo: la publicada tiene {len(alla)} caracteres y la local "
              f"{len(aqui)}; hay cambios sin subir)")
        return True
    print(f"    {URL_HTML} -> {estado}, {len(cuerpo)} bytes, igual a la local")
    return True


def leer_bloque(texto: str, nombre: str):
    """El array de dentro de un bloque /* === INICIO X === */. None si no esta.

    El bloque es JavaScript, pero un array de numeros y textos con comillas
    dobles es JSON valido, asi que se lee con json y no con expresiones
    regulares. Una expresion regular se rompe en silencio el dia que alguien
    reformatee el bloque; json.loads falla y aqui se ve por que.
    """
    ini = f"/* === INICIO {nombre} === */"
    fin = f"/* === FIN {nombre} === */"
    a, b = texto.find(ini), texto.find(fin)
    if a < 0 or b < 0:
        return None
    cuerpo = texto[a + len(ini):b]
    i, j = cuerpo.find("["), cuerpo.rfind("]")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(cuerpo[i:j + 1])
    except json.JSONDecodeError:
        return None


def leer_objeto(texto: str, nombre: str):
    """El objeto de dentro de un bloque /* === INICIO X === */. Para PROPIOS.

    Misma idea que leer_bloque: los iconos propios son un diccionario de
    nombre a data URL, y eso es JSON valido si las comillas son dobles.
    """
    ini = f"/* === INICIO {nombre} === */"
    fin = f"/* === FIN {nombre} === */"
    a, b = texto.find(ini), texto.find(fin)
    if a < 0 or b < 0:
        return None
    cuerpo = texto[a + len(ini):b]
    i, j = cuerpo.find("{"), cuerpo.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(cuerpo[i:j + 1])
    except json.JSONDecodeError:
        return None


CROQUIS = Path("plantilla/croquis.html")
EDITOR_HTML = Path("editor/editor.html")
VALIDAR = Path("editor/validar.py")


def _cuerpo_de_keyframe(css: str, nombre: str) -> str | None:
    """Lo que hay dentro de un @keyframes, o None si no esta definido.

    Hay que buscar el cierre contando llaves y no con una expresion regular:
    los pasos de un keyframe llevan llaves dentro, asi que el primer `}` que
    aparece no es el que cierra el bloque. Contando se sabe donde acaba.

    Y el nombre se busca entero: `@keyframes icGira` esta contenido en
    `@keyframes icGiraMas`, asi que sin mirar lo que viene detras se podria
    dar por bueno un keyframe que no existe.
    """
    desde = 0
    while True:
        i = css.find("@keyframes " + nombre, desde)
        if i < 0:
            return None
        fin = i + len("@keyframes ") + len(nombre)
        if fin >= len(css) or not (css[fin].isalnum() or css[fin] in "_-"):
            break
        desde = i + 1
    j = css.find("{", fin)
    if j < 0:
        return None
    hondo = 0
    k = j
    while k < len(css):
        if css[k] == "{":
            hondo += 1
        elif css[k] == "}":
            hondo -= 1
            if hondo == 0:
                return css[j + 1:k]
        k += 1
    return None


def test_croquis_zonas_coherentes() -> bool:
    """Las zonas y los iconos del croquis están completos y no se pisan.

    Las zonas son filas de cuatro campos: nombre largo, nombre corto, el
    polígono para el toque y la descripción. La caja que se encuadra al hacer
    zoom NO se guarda: se calcula del polígono, porque tener las dos cosas a
    mano garantiza que algún día se desincronicen.

    Las reglas viven en editor/validar.py, que es la misma que usa el editor
    para decidir si deja guardar. Están compartidas a propósito: si cada uno
    tuviera su copia, un día dirían cosas distintas y la que estuviera más
    floja sería la que decidiera.
    """
    if not CROQUIS.is_file():
        print(f"    (no existe {CROQUIS})")
        return False
    texto = CROQUIS.read_text(encoding="utf-8")

    zonas = leer_bloque(texto, "ZONAS")
    iconos = leer_bloque(texto, "ICONOS")
    propios = leer_objeto(texto, "PROPIOS")
    if zonas is None or iconos is None or propios is None:
        print("    (no se pueden leer los bloques ZONAS, ICONOS o PROPIOS)")
        print("    Los marcadores /* === INICIO X === */ no se pueden borrar:")
        print("    sin ellos el editor no sabe qué trozo reescribir.")
        return False

    problemas = v.revisar(zonas, iconos, propios)
    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False

    # El mapa es un archivo aparte: si no está junto al HTML, la página sale
    # con el fondo vacío y ni un error en consola.
    mapa = re.search(r'<image[^>]+href="([^"]+)"', texto)
    if not mapa:
        print("    (no se encuentra el <image> con el mapa de fondo)")
        return False

    # La dirección lleva un `?v=` con el sha1 del propio archivo, para que al
    # cambiar el arte cambie la dirección y nadie siga viendo la copia vieja.
    #
    # Hace falta de verdad: GitHub Pages sirve la imagen con
    # `Cache-Control: max-age=600`, así que durante diez minutos después de
    # subir un cambio se sigue viendo el mapa anterior, recargando inclusive.
    # Y un `?v=` que se queda viejo no da ningún error: solo un mapa que no
    # cambia, que es justo el fallo que parece «no se subió». Por eso el número
    # no se escribe a mano y se comprueba aquí.
    href = mapa.group(1)
    archivo, _, version = href.partition("?v=")
    ruta_mapa = Path("plantilla") / archivo
    if not ruta_mapa.is_file():
        print(f"    (el mapa {ruta_mapa} no existe junto al HTML)")
        return False

    sha = hashlib.sha1(ruta_mapa.read_bytes()).hexdigest()[:8]
    if not version:
        print(f"    (el <image> no lleva «?v=»: los navegadores seguirán")
        print(f"     diez minutos con el mapa viejo. Ponle href=\"{archivo}?v={sha}\")")
        return False
    if version != sha:
        print(f"    (cambió rectoria.webp y la dirección sigue con el número de")
        print(f"     antes: el navegador seguirá enseñando el mapa viejo aunque")
        print(f"     se recargue. En croquis.html pon href=\"{archivo}?v={sha}\")")
        return False

    print(f"    {len(zonas)} zonas y {len(iconos)} iconos "
          f"({len(propios)} propios), mapa de {ruta_mapa.stat().st_size // 1024} KB"
          f" (v{version})")
    return True


def test_iconos_y_simbolos_coinciden() -> bool:
    """El croquis sabe dibujar todos los tipos de icono que el editor ofrece.

    Son dos listas que tienen que decir lo mismo: la de editor/validar.py
    decide qué tipos se pueden guardar y la del croquis (el bloque SIMBOLOS)
    sabe dibujarlos. Si se separan, se puede guardar un icono que luego no se
    dibuja: sale un hueco en el mapa y ningún error en consola.

    Y una tercera: los NOMBRES del croquis, que son los que se anuncian en el
    <title> de cada icono. Si se separan, un icono acabaría llamándose «bano»
    en el mapa y «Baños» en el editor, y nadie sabe cuál de los dos manda.
    """
    texto = CROQUIS.read_text(encoding="utf-8")
    ini, fin = "/* === INICIO SIMBOLOS === */", "/* === FIN SIMBOLOS === */"
    a, b = texto.find(ini), texto.find(fin)
    if a < 0 or b < 0:
        print("    (no se encuentra el bloque SIMBOLOS en croquis.html)")
        return False

    # Los símbolos están escritos como trozos de texto encadenados con +, para
    # que las líneas no se hagan kilométricas. Aquí se vuelven a pegar.
    formas = {clave: "".join(re.findall(r"'([^']*)'", trozos))
              for clave, trozos in re.findall(
                  r"^\s*(\w+):\s*((?:\s*'[^']*'\s*\+?)+)", texto[a:b], flags=re.M)}

    faltan = sorted(set(v.SIMBOLOS) - set(formas))
    sobran = sorted(set(formas) - set(v.SIMBOLOS))
    if faltan:
        print(f"    (validar.py ofrece tipos que el croquis no puede dibujar: "
              f"{', '.join(faltan)})")
    if sobran:
        print(f"    (el croquis dibuja tipos que validar.py no deja usar: "
              f"{', '.join(sobran)})")
    if faltan or sobran:
        print("    Hay que tocar las dos listas, o los iconos salen en blanco.")
        return False

    # Un símbolo dibujado de verdad, no una cadena vacía.
    vacios = [k for k, forma in formas.items() if "<" not in forma]
    if vacios:
        print(f"    (estos símbolos no tienen dibujo: {', '.join(vacios)})")
        return False

    # Y los nombres, que viven en su propia lista porque no los reescribe el
    # editor: son los mismos para todos los mapas.
    nombres = dict(re.findall(r'(\w+):\s*"([^"]+)"',
                              texto[texto.find("var NOMBRES"):]))
    malos = [k for k in v.SIMBOLOS if nombres.get(k) != v.SIMBOLOS[k]]
    if malos:
        for k in malos:
            print(f"    «{k}»: el croquis dice «{nombres.get(k)}» y validar.py "
                  f"«{v.SIMBOLOS[k]}»")
        print("    Los nombres son los que se leen al pasar el ratón por el mapa.")
        return False

    print(f"    {len(formas)} símbolos dibujables y con el mismo nombre, "
          f"uno por cada tipo del editor")
    return True


def test_animaciones_e_intensidad() -> bool:
    """Cada animación que se ofrece existe de verdad, en el mapa y en el editor.

    Son varias listas que tienen que decir lo mismo y viven en sitios
    distintos: las animaciones que validar.py deja guardar, los keyframes del
    croquis publicado y las reglas del editor (que tiene tres copias: el mapa,
    la vista previa del menú de subir y las miniaturas). Si se separan, se
    puede elegir una animación que no hace nada: el icono se guarda, el mapa
    se publica y el icono se queda quieto. Sin un solo error en ninguna parte.
    Es la peor forma de fallar, así que aquí se vigila a mano.

    Y de la INTENSIDAD se comprueba lo que de verdad se puede romper en
    silencio: que los keyframes la lean. Los keyframes son globales, así que
    con mirarlos una vez vale. Sin el `var(--m, 1)` dentro del calc() el
    deslizador se movería, el número se guardaría en el archivo y el icono se
    movería siempre igual: un ajuste que no ajusta nada.
    """
    problemas = []

    # --- 1. Las animaciones y sus reglas ------------------------------------
    # El nombre del keyframe sale del de la animación: `vibra` -> `icVibra`.
    # Si algún día no fuera así, lo dice la comprobación de más abajo.
    animadas = [k for k in v.ANIMACIONES if k]

    # Los sitios donde tiene que haber una regla por animación. Van uno por uno
    # y no por número: si falta el de las miniaturas hay que poder decir cuál
    # falta, y no «faltan dos».
    sitios = [("mapa publicado", CROQUIS, ["#iconos .an.{a}"]),
              ("mapa del editor", EDITOR_HTML, ["#gIconos .an.{a}"]),
              ("vista previa del menú de subir", EDITOR_HTML,
               ["#previoDialogo .an.{a}"]),
              ("miniaturas", EDITOR_HTML,
               [".palo svg .an.{a},", ".modelo svg .an.{a},", ".icono svg .an.{a}"])]

    for nombre, ruta, plantillas in sitios:
        if not ruta.is_file():
            problemas.append(f"no existe {ruta}")
            continue
        css = ruta.read_text(encoding="utf-8")
        for a in animadas:
            for plantilla in plantillas:
                # El selector entero, para no confundir la clase del panel con
                # la regla del SVG, que es la única que dibuja algo.
                if plantilla.format(a=a) not in css:
                    problemas.append(
                        f"en el {nombre} no hay regla para «{a}» "
                        f"(falta `{plantilla.format(a=a)}`)")

    # --- 2. Que los keyframes existan y que lean la intensidad --------------
    css_croquis = CROQUIS.read_text(encoding="utf-8")
    revisadas = 0
    for a in animadas:
        uso = re.search(r"#iconos \.an\." + re.escape(a)
                        + r"\{[^}]*animation:\s*(\w+)", css_croquis)
        if not uso:
            continue          # de la regla que falta ya se ha avisado arriba
        revisadas += 1
        nombre_keyframe = uso.group(1)
        cuerpo = _cuerpo_de_keyframe(css_croquis, nombre_keyframe)
        if cuerpo is None:
            problemas.append(
                f"la animación «{a}» usa el keyframe «{nombre_keyframe}», que no "
                f"está definido: el icono saldría quieto y sin avisar")
        elif a in v.ANIMACIONES_SIN_INTENSIDAD:
            if "var(--m" in cuerpo:
                problemas.append(
                    f"«{a}» está en ANIMACIONES_SIN_INTENSIDAD y su keyframe usa "
                    f"la intensidad, que no le hace nada")
        elif "var(--m" not in cuerpo:
            problemas.append(
                f"el keyframe «{nombre_keyframe}» de «{a}» no lee «var(--m)»: "
                f"el deslizador se movería y el icono se movería siempre igual")

    # Si la búsqueda de arriba no reconociera una sola regla, el bucle entero se
    # saltaría en silencio y esta parte de la prueba daría el visto bueno sin
    # haber mirado nada. Es exactamente el engaño en el que ya se cayó una vez
    # aquí, con una validación que se quedó dentro de un `if` y no comprobaba
    # nada. Por eso se cuenta y se exige que estén todas.
    if revisadas != len(animadas):
        problemas.append(
            f"solo se pudieron leer {revisadas} de {len(animadas)} animaciones "
            f"del croquis: el resto no se comprobó")

    # Y que el icono se dibuje con la intensidad puesta, en un elemento del que
    # el grupo animado la pueda heredar. En el mismo grupo también valdría, así
    # que lo que se comprueba es que esté, no dónde exactamente.
    for ruta in (CROQUIS, EDITOR_HTML):
        if 'style="--m:' not in ruta.read_text(encoding="utf-8"):
            problemas.append(
                f"{ruta.name} no pone nunca «--m» en un icono: la intensidad no "
                f"llegaría a los keyframes")
    # En el editor se dibuja en tres sitios: el mapa y las dos formas de
    # miniatura (la del menú de subir y la de la paleta, que comparten función).
    # Contando la definición, tienen que salir al menos tres usos.
    if EDITOR_HTML.read_text(encoding="utf-8").count("fuerzaDe(") < 3:
        problemas.append(
            "en editor.html «fuerzaDe» no se usa en los tres sitios donde se "
            "dibuja un icono: el mapa y las miniaturas")

    # --- 2 bis. Que el viento pivote en la base, como un arbol --------------
    # No basta con que la animación exista: tiene que girar sobre la BASE. Con
    # el pivote en el centro (que es el de todas las demás) el icono se
    # balancea sobre su eje y se lee como algo que flota, no como algo que
    # aguanta el aire desde abajo. Es una diferencia de una línea de CSS y de
    # nada en el HTML, así que sin esta comprobación se pierde sin que nadie se
    # entere hasta verlo en el móvil.
    sitios_viento = [("mapa publicado", CROQUIS, "#iconos"),
                     ("mapa del editor", EDITOR_HTML, "#gIconos"),
                     ("vista previa del menú", EDITOR_HTML, "#previoDialogo"),
                     ("miniaturas", EDITOR_HTML, ".palo svg")]
    for nombre, ruta, cual in sitios_viento:
        css = ruta.read_text(encoding="utf-8")
        # El selector de cada sitio, con su transform-origin al lado. Se busca
        # el bloque entero y no una linea suelta: el de las miniaturas lleva
        # tres selectores juntos separados por comas.
        patron = (re.escape(cual) + r"[^{}]*\.an\.viento\{[^}]*"
                  r"transform-origin:\s*50%\s+100%")
        if not re.search(patron, css):
            problemas.append(
                f"en {nombre} el viento no pivota en su base: falta "
                f"`transform-origin: 50% 100%` en su regla")

    # Y que el sesgo del keyframe vaya en el sentido que suma con el giro.
    # Con los dos en positivo se cancelan y la copa se queda casi quieta: se
    # midió, se movia 0.8 de los 3.9 que deberia. Un `skewX` positivo ahi
    # parece lo natural y arruina el efecto sin que se vea ningún error.
    cuerpo_viento = _cuerpo_de_keyframe(css_croquis, "icViento")
    if cuerpo_viento is None:
        problemas.append("no está definido el keyframe `icViento`")
    else:
        sesgos = re.findall(r"skewX\(calc\((-?[\d.]+)deg", cuerpo_viento)
        if not sesgos:
            problemas.append(
                "el keyframe del viento no usa `skewX`: sin él el icono es un "
                "palo rígido que gira, no un árbol que se dobla")
        elif all(s.startswith("-") for s in sesgos) is False:
            problemas.append(
                f"el `skewX` del viento tiene que ir en negativo para sumar con "
                f"el giro; viene {sesgos}. Con los dos en el mismo signo se "
                f"cancelan y la copa se queda casi quieta")
        if "rotate" not in cuerpo_viento:
            problemas.append("el keyframe del viento no gira: solo se dobla")

    # --- 3. Los ajustes: lo que se guarda y lo que se tira ------------------
    limpios = [
        ({"s": 46, "a": "late", "m": 1.0, "c": 1}, {"s": 46, "a": "late"},
         "la intensidad de fábrica no se escribe"),
        ({"a": "vibra", "m": 1.4, "c": 0}, {"a": "vibra", "m": 1.4, "c": 0},
         "una intensidad distinta sí se escribe"),
        ({"m": 0.5}, {"m": 0.5}, "la intensidad sola se conserva"),
        ({"m": ""}, {}, "una intensidad vacía se descarta"),
        ({"m": None}, {}, "una intensidad nula se descarta"),
    ]
    for entrada, esperado, nota in limpios:
        salida = v.limpiar_ajustes(dict(entrada))
        if salida != esperado:
            problemas.append(f"{nota}: {entrada} -> {salida}, esperaba {esperado}")

    # --- 4. Lo que se rechaza ----------------------------------------------
    # El booleano tiene que caer: en Python `True` es un número, y sin mirarlo
    # aparte colaría como si fuera una intensidad de 1.
    malos = [
        ({"a": "late", "m": 0.1}, "por debajo del mínimo"),
        ({"a": "late", "m": 2.6}, "por encima del máximo"),
        ({"a": "late", "m": "mucho"}, "un texto en vez de un número"),
        ({"a": "late", "m": True}, "un booleano"),
        ({"a": "gira", "m": 1.5}, "una animación que no tiene intensidad"),
        ({"a": "vuelta", "m": 1.5}, "una animación que no existe"),
    ]
    buenos = [
        ({"a": "vibra", "m": v.MIN_INTENSIDAD}, "vibra en el mínimo"),
        ({"a": "viento", "m": v.MAX_INTENSIDAD}, "viento en el máximo"),
        ({"a": "vibra"}, "vibra sin intensidad, que es la de fábrica"),
        ({"a": "gira"}, "gira sin intensidad"),
        ({"s": 60}, "solo un tamaño"),
    ]
    for ajustes, nota in malos:
        if not v.revisar_ajustes(dict(ajustes)):
            problemas.append(f"aceptó unos ajustes con {nota}: {ajustes}")
    for ajustes, nota in buenos:
        salida = v.revisar_ajustes(dict(ajustes))
        if salida:
            problemas.append(f"rechazó unos ajustes con {nota}: {salida}")

    # Y lo mismo en los iconos del mapa, que es por donde entra de verdad. Se
    # mira el mensaje además del rechazo: si el error viniera de otro sitio
    # (un tipo que no existe, por ejemplo) la prueba pasaría sin comprobar
    # nada, que es justo el engaño en el que ya se cayó una vez aquí.
    icono = {"t": "bano", "x": 300, "y": 250, "a": "vibra", "m": 1.5}
    salida = v.revisar_iconos([dict(icono)])
    if salida:
        problemas.append(f"rechazó un icono con vibra al 1.5: {salida}")
    for valor, nota in ((0.1, "una intensidad por debajo del mínimo"),
                        ("mucho", "una intensidad que no es número"),
                        (True, "una intensidad booleana")):
        salida = v.revisar_iconos([dict(icono, m=valor)])
        if not salida:
            problemas.append(f"aceptó un icono con {nota}")
        elif "icono 1" not in " ".join(salida):
            problemas.append(
                f"un icono con {nota} se rechazó, pero no por el icono: {salida}")
    salida = v.revisar_iconos([dict(icono, a="gira")])
    if not salida:
        problemas.append("aceptó un icono que gira y que además lleva intensidad")

    # --- 5. Lo que se escribe en el archivo --------------------------------
    # Se llama a la función que arma los campos en vez de levantar el servidor
    # entero: es la misma línea de código, y así la prueba no escribe nada en
    # el croquis ni en la biblioteca.
    campos = editor._campos_icono({"t": "bano", "x": 300, "y": 250,
                                   "a": "vibra", "m": 1.4})
    escrito = "{" + ", ".join(campos) + "}"
    if '"m": 1.4' not in escrito:
        problemas.append(f"el icono no se escribió con su intensidad: {escrito}")
    campos = editor._campos_icono({"t": "bano", "x": 300, "y": 250,
                                   "a": "late", "m": 1.0})
    if '"m"' in "{" + ", ".join(campos) + "}":
        problemas.append("se escribió la intensidad de fábrica, que es la de siempre")

    # El orden importa: el archivo se lee entero de arriba abajo y `m` va entre
    # `a` y `c`. En otro sitio costaría encontrar cada campo al editarlo a mano.
    # El giro va con un valor de verdad: con 0 no se escribe, porque 0 es «sin
    # girar» y no hace falta decirlo.
    orden = [p.split(":", 1)[0].strip('"') for p in editor._campos_icono(
        {"t": "bano", "x": 1, "y": 2, "n": "Baños", "s": 46, "r": -30,
         "a": "vibra", "m": 2, "c": 0, "i": ["Título", "Texto"]})]
    if orden != ["t", "x", "y", "n", "s", "r", "a", "m", "c", "i"]:
        problemas.append(f"los campos salen en otro orden: {orden}")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print(f"    {len(animadas)} animaciones dibujadas y con su keyframe, y la "
          f"intensidad de {v.MIN_INTENSIDAD} a {v.MAX_INTENSIDAD} leída por los "
          f"keyframes y rechazada donde no vale")
    return True


def test_el_toque_y_el_encabezado() -> bool:
    """El toque llega a los iconos pulsables, y el panel no tapa el titulo.

    Las dos cosas se ven solo en pantalla y las dos se rompen en silencio.

    **El toque.** Un icono con informacion necesita algo que recoja la
    pulsacion, y no vale cualquier cosa: el grupo no tiene forma propia, la
    imagen la tiene desactivada a proposito (para no quitarle la pulsacion a
    la zona de debajo) y un simbolo son trazos sueltos. Cuando lleva aro, el
    aro recoge el toque, porque esta pintado. **Sin aro no quedaba nada** y el
    toque se colaba hasta el mapa, que al tocarlo deshace el zoom: pulsar el
    icono no abria la ventana, la deshacia. Y como el mapa deshace el zoom al
    tocarlo, el fallo parecia «el icono no hace nada».

    El circulo `.toque` es la superficie. Se comprueba que exista, que no se
    pinte, y que su `pointer-events` sea de los que dan por bueno el relleno
    aunque no este pintado: `auto` (que es `visiblePainted`) y `painted`
    exigen que la forma este pintada, y con `fill:none` no lo esta. Poner
    `auto` ahi pareceria razonable y no funcionaria.

    **El encabezado.** En apaisado el panel es lateral y el encabezado va
    anclado arriba a la izquierda, asi que el panel le pasa por encima y el
    titulo desaparece detras. Aqui se comprueba que el encabezado empiece
    despues de donde termina el panel. Asi, si alguien ensancha el panel, la
    prueba avisa en vez de que el titulo desaparezca en silencio.
    """
    texto = CROQUIS.read_text(encoding="utf-8")
    problemas = []

    # --- 1. La superficie que recibe el toque --------------------------------
    regla = re.search(r"#iconos \.toque\{([^}]*)\}", texto)
    if not regla:
        problemas.append(
            "no hay regla para `#iconos .toque`: un icono sin aro y con "
            "informacion se queda sin nada que recoja la pulsacion")
    else:
        cuerpo = regla.group(1).replace(" ", "")
        if "fill:none" not in cuerpo:
            problemas.append(
                "#iconos .toque se pinta: se veria un circulo encima del icono")
        permite = re.search(r"pointer-events:(\w+)", cuerpo)
        # Solo los valores que no exigen que la forma este pintada.
        if not permite or permite.group(1) not in ("fill", "all", "stroke"):
            problemas.append(
                f"`#iconos .toque` usa pointer-events:{permite.group(1) if permite else '?'}"
                f" y con fill:none no recibe el toque; tiene que ser `fill`")

    # --- 2. Que el render lo dibuje, y solo en los que llevan informacion ----
    ini = texto.find("ICN.innerHTML")
    fin = texto.find('}).join("");', ini)
    if ini < 0 or fin < 0:
        problemas.append("(no se encuentra el bloque ICN.innerHTML en el croquis)")
    else:
        render = texto[ini:fin]
        prepara = re.search(r"var toque = ([^;]+);", render)
        if not prepara:
            problemas.append("el render no prepara el circulo del toque")
        else:
            linea = " ".join(prepara.group(1).split())
            # Tiene que depender de `ic.i`: en un icono sin informacion el
            # toque tiene que seguir siendo de la zona de debajo. Si se le
            # pusiera a todos, los iconos se comerian la pulsacion de las
            # zonas, que es justo lo que el diseno evita.
            if "ic.i" not in linea:
                problemas.append(
                    f"el circulo del toque no depende de que el icono lleve "
                    f"informacion: {linea}")
            if 'class="toque"' not in linea:
                problemas.append(f"el circulo del toque no lleva su clase: {linea}")
        if "+ toque" not in render:
            problemas.append("el circulo del toque se prepara pero no se dibuja")

    # --- 3. Que la prueba no pase en balde -----------------------------------
    # Lo que se comprueba aqui es el CODIGO: la regla de `.toque` y que el
    # render dibuje el circulo cuando el icono lleva informacion. Si ahora
    # mismo no hay ningun icono con informacion en el mapa, eso es una decision
    # de contenido, no un fallo: el dia que se vuelva a poner uno, el circulo
    # tiene que salir bien. Antes esto era un fallo y saltaba cada vez que se
    # borraba el ultimo icono con informacion, que no es de nadie.
    iconos = leer_bloque(texto, "ICONOS") or []
    if not [ic for ic in iconos if ic.get("i")]:
        print("    (ningun icono lleva informacion ahora mismo: el circulo del "
              "toque no esta en uso, pero el codigo que lo dibuja queda "
              "comprobado arriba)")

    # --- 4. El encabezado, a la derecha del panel ----------------------------
    # Hay varios bloques de pantalla ancha en el archivo (el de la ventana y el
    # del panel), asi que se busca el que lleva el panel por su regla y no el
    # primero que aparezca.
    bloques = re.findall(
        r"@media \(min-width:760px\) and \(orientation:landscape\)\{(.*?)\n\}",
        texto, flags=re.S)
    css = next((b for b in bloques if "#ficha{left:" in b), None)
    if css is None:
        problemas.append(
            "(no se encuentra el bloque de pantalla ancha que coloca el panel)")
    else:
        panel = re.search(r"#ficha\{left:(\d+)px;right:auto;top:14px;"
                          r"bottom:14px;width:(\d+)px", css)
        cabecera = re.search(r"#cab\{padding-left:(\d+)px\}", css)
        if not panel or not cabecera:
            problemas.append(
                "en pantalla ancha hacen falta el `left` y el `width` del panel y "
                "el `padding-left` del encabezado, para poder comprobar que no "
                "se pisan")
        else:
            borde_panel = int(panel.group(1)) + int(panel.group(2))
            desde = int(cabecera.group(1))
            if desde < borde_panel:
                problemas.append(
                    f"el encabezado empieza en {desde}px y el panel llega hasta "
                    f"{borde_panel}px: el titulo queda debajo del panel")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    los iconos con informacion tienen su superficie de toque y el "
          "encabezado empieza donde termina el panel")
    return True


def test_el_sello_y_el_boton_de_la_ventana() -> bool:
    """La ventana ensena el mismo icono que se toco, y su boton es seguro.

    Dos cosas que solo se ven al abrirla y que se rompen calladas.

    **El sello.** La ventana tiene un icono al lado del titulo, dibujado con la
    misma figura que el del mapa. Estaba puesto con el circulo forzado, asi que
    un icono que en el mapa se ve suelto aparecia ahi metido en una caja: parece
    que el toque abrio otro icono. Ahora el circulo lo decide el propio icono,
    igual que en el mapa.

    **El boton.** Es un `<a href>` cuya direccion sale del archivo, y el archivo
    lo puede editar cualquiera a mano. Un `javascript:` ahi es una forma de
    ejecutar codigo en la pagina de quien mira el mapa, y una direccion sin
    esquema se toma por una ruta de esta misma pagina, con lo que el boton no
    lleva a ninguna parte sin dar ningun error.

    Por eso se comprueba en los tres sitios donde vive el enlace: la regla que
    lo valida en el croquis, la que lo valida en el servidor, y que el croquis
    de verdad la use antes de asignar el `href` (de nada sirve tener la regla
    escrita si no se llama).
    """
    problemas = []
    texto = CROQUIS.read_text(encoding="utf-8")
    val = VALIDAR.read_text(encoding="utf-8")
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. El sello, con el circulo del icono y no forzado -----------------
    ini = texto.find("function abreVentana(")
    fin = texto.find("\n}", ini)
    if ini < 0 or fin < 0:
        problemas.append("(no se encuentra abreVentana en el croquis)")
        ventana = ""
    else:
        ventana = texto[ini:fin]
        if "conAroDe(ic)" not in ventana:
            problemas.append(
                "la ventana no mira si el icono lleva circulo: el sello saldria "
                "siempre con marco, aunque en el mapa el icono vaya suelto")
        if "figuraDe(ic.t, true)" in ventana:
            problemas.append(
                "la ventana sigue pasando `true` a figuraDe: se ignora el "
                "circulo del icono")
        if '"sinAro"' not in ventana:
            problemas.append(
                "la ventana no le pone la clase «sinAro» al sello, que es la "
                "que quita el marco en el CSS")
    # Y que el CSS tenga esa clase, o la marca no sirve de nada.
    for ruta in (CROQUIS,):
        css = ruta.read_text(encoding="utf-8")
        if "#selloVentana.sinAro" not in css:
            problemas.append(
                "el CSS no tiene reglas para `#selloVentana.sinAro`: el sello "
                "seguiria con su marco aunque lleve la clase")

    # --- 1 bis. El sello encaja el icono con margen, sin recortarlo ---------
    # El icono del sello salia cortado: iba en un `<img>` con `object-fit:
    # cover`, que escala la imagen hasta llenar la caja y tira lo que sobra.
    # Una gota de 105 x 150 en una caja de 52 x 52 perdia la punta y la base,
    # y no habia ningun error: solo un dibujo al que le faltaban trozos.
    #
    # Ahora el dibujo va DENTRO del `<svg>` y el hueco lo da el `viewBox`, que
    # el script ajusta midiendo el dibujo de verdad. Tres cosas que tienen que
    # cumplirse para que eso funcione, y las tres se comprueban aqui:
    #
    #  - Que la imagen no vuelva a ir en un `<img>` con `cover`.
    #  - Que `encajaSello` exista Y se llame, y que respete el tope de pixeles
    #    libres: una funcion que no se llama no encaja nada.
    #  - Que el `<image>` deje la proporcion en manos del SVG (`meet`, que es
    #    el valor por defecto) y no la estire ni la recorte.
    if "object-fit:cover" in texto:
        problemas.append(
            "el sello vuelve a usar `object-fit:cover`: escala la imagen hasta "
            "llenar la caja y recorta lo que sobra, que es justo el corte que "
            "se arreglo")
    if re.search(r"#selloVentana\s+img", texto):
        problemas.append(
            "el CSS del sello sigue teniendo reglas para un `<img>`: los iconos "
            "propios ahora van como imagen dentro del svg")
    if "encajaSello" not in texto:
        problemas.append("no existe `encajaSello`: el icono no se encaja con "
                         "margen y vuelve a salir pegado o cortado")
    elif "encajaSello(SELLO" not in texto:
        problemas.append(
            "`encajaSello` esta definida pero no se llama al abrir la ventana: "
            "no encaja nada")
    else:
        # El tope de pixeles libres tiene que estar declarado y usarse.
        tope = re.search(r"SELLO_LIBRES\s*=\s*(\d+)", texto)
        if not tope:
            problemas.append("no esta declarado `SELLO_LIBRES`")
        elif int(tope.group(1)) < 5:
            problemas.append(
                f"`SELLO_LIBRES` vale {tope.group(1)}: se pidieron 5 pixeles "
                f"libres por lado")
        lado = re.search(r"SELLO_LADO\s*=\s*(\d+)", texto)
        css_sello = re.search(r"#selloVentana svg\{width:(\d+)px;height:(\d+)px",
                              texto)
        if not lado or not css_sello:
            problemas.append(
                "hacen falta `SELLO_LADO` y el `width` del sello en el CSS, para "
                "poder comprobar que miden lo mismo")
        elif int(lado.group(1)) != int(css_sello.group(1)):
            problemas.append(
                f"`SELLO_LADO` vale {lado.group(1)} y el sello mide "
                f"{css_sello.group(1)} px: el margen calculado no seria el "
                f"que se ve")
        # El encaje tiene que usar el bbox medido y meterlo entero dentro del
        # viewBox. Si calculara el viewBox solo del maximo, un dibujo mas ancho
        # que alto se saldria por los lados.
        ini_enc = texto.find("function encajaSello(")
        cuerpo_enc = texto[ini_enc:texto.find("\n}", ini_enc)] if ini_enc >= 0 else ""
        for pieza, nota in (("getBBox", "mida el dibujo de verdad"),
                            ("caja.width", "cuente con lo ancho del dibujo"),
                            ("caja.height", "cuente con lo alto del dibujo"),
                            ("viewBox", "ajuste el viewBox")):
            if pieza not in cuerpo_enc:
                problemas.append(f"`encajaSello` no {nota} (le falta `{pieza}`)")
        # Y que la imagen del sello no lleve `preserveAspectRatio="none"`, que
        # estiraria el dibujo hasta deformarlo.
        if 'preserveAspectRatio="none"' in texto.split("function abreVentana")[1][:900]:
            problemas.append(
                "el sello estira la imagen con `preserveAspectRatio=\"none\"`: "
                "el icono saldria deformado")

    # --- 1 ter. La ventana sale centrada ------------------------------------
    # Estaba pegada al fondo (`place-items:end center`) y en un telefono alto
    # quedaba a media pantalla de distancia del icono que se acababa de tocar.
    #
    # El `safe center` de la linea siguiente es por si la caja no cupiera de
    # alto: con un `center` a secas lo que sobra se sale por ARRIBA y de ahi no
    # se puede bajar con el dedo. Es una mejora y no un requisito, asi que lo
    # que se exige es el `center`; el `safe` se acepta pero no se pide.
    regla_ventana = re.search(r"#ventana\{([^}]*)\}", texto)
    if not regla_ventana:
        problemas.append("(no se encuentra la regla de `#ventana` en el CSS)")
    else:
        centrado = re.search(r"place-items:\s*(\w+)", regla_ventana.group(1))
        if not centrado or centrado.group(1) != "center":
            problemas.append(
                f"`#ventana` no sale centrada: usa "
                f"`place-items:{centrado.group(1) if centrado else '?'}`. Con "
                f"`end` la ventana se pega al fondo de la pantalla")
        # Y que no quede un `place-items:end` suelto en el bloque de pantalla
        # ancha, que volveria a pegarla abajo en apaisado.
        for bloque in re.findall(
                r"@media \(min-width:760px\) and \(orientation:landscape\)\{(.*?)\n\}",
                texto, flags=re.S):
            if "#ventana{" in bloque and "place-items:end" in bloque:
                problemas.append(
                    "el bloque de pantalla ancha vuelve a pegar la ventana al "
                    "fondo: en apaisado saldria abajo en vez de centrada")

    # --- 2. La regla que valida el enlace, en los tres sitios ---------------
    # En el croquis y en el editor la funcion se llama enlaceSeguro y
    # enlaceValido; en el servidor, enlace_seguro. Son nombres distintos porque
    # cada uno sigue la convencion de su lenguaje.
    for nombre, donde in (("el croquis", texto), ("el servidor", val),
                          ("el editor", edit)):
        if not any(n in donde for n in ("enlaceSeguro", "enlaceValido",
                                        "enlace_seguro")):
            problemas.append(f"en {nombre} no hay ninguna función que valide el "
                             f"enlace antes de usarlo")
    # Las tres tienen que exigir http o https y nada mas. Si alguna aflojara el
    # patrón, por ahí entraría el `javascript:`.
    for nombre, patron in (("el croquis", r"function enlaceSeguro"),
                           ("el editor", r"function enlaceValido")):
        i = texto.find(patron) if nombre == "el croquis" else edit.find(patron)
        if i < 0:
            continue
        cuerpo = (texto if nombre == "el croquis" else edit)[i:i + 260]
        if not re.search(r"\^https\?:\\/\\/", cuerpo):
            problemas.append(
                f"la comprobación del enlace en {nombre} no exige «https?://»: "
                f"{' '.join(cuerpo.split())[:90]}")
    # En el servidor se hace con una tupla de esquemas.
    if 'ESQUEMAS = ("http://", "https://")' not in val:
        problemas.append(
            "en el servidor la lista de esquemas permitidos no es "
            "exactamente http:// y https://")
    if "enlace_seguro" not in val:
        problemas.append("en el servidor no se usa `enlace_seguro` al revisar")

    # --- 3. Que el croquis la use ANTES de poner el href --------------------
    # Es la comprobación que de verdad importa: la función puede estar escrita
    # y no llamarse, y entonces no valida nada.
    #
    # Se mira en `montaEnlace` y no en `pintaBoton` porque ese es ahora el
    # ÚNICO sitio que pone un `href`, así que la comprobación de ahí vale para
    # los dos botones -el de la ventana y el del panel- y no hay ninguna otra
    # puerta por la que se pueda colar una dirección. Comprobarlo en cada botón
    # era justo lo que se podía olvidar en el segundo.
    i = texto.find("function montaEnlace(")
    if i < 0:
        problemas.append("(no se encuentra montaEnlace en el croquis)")
    else:
        cuerpo = texto[i:texto.find("\n}", i)]
        if "enlaceSeguro" not in cuerpo:
            problemas.append(
                "montaEnlace no comprueba la dirección antes de poner el href")
        elif cuerpo.find("enlaceSeguro") > cuerpo.find("href"):
            problemas.append(
                "montaEnlace pone el `href` antes de comprobar la dirección: la "
                "comprobación no sirve de nada ahí")
        if "noopener" not in cuerpo:
            problemas.append(
                "el botón de fuera abre en pestaña nueva y no lleva `noopener`: "
                "la página de destino podría manipular esta desde window.opener")
    # Y los dos botones se arman con createElement y no con innerHTML, para que
    # la dirección se trate como dirección y no como HTML.
    if texto.count('document.createElement("a")') < 2:
        problemas.append(
            "los botones no se arman con `createElement`: con `innerHTML` "
            "habría que escapar la dirección a mano y un despiste la "
            "convertiría en una etiqueta")

    # --- 4. Que el croquis no lleve el `<a>` escrito en el marcado ----------
    # Si estuviera escrito, la prueba `el croquis publicado no edita nada` lo
    # vería como un enlace sin href y no sabría que lo rellena el script.
    if re.search(r"<a\b[^>]*enlaceVentana", texto):
        problemas.append(
            "el `<a>` del botón está escrito en el marcado: lo tiene que armar "
            "el script, porque la dirección sale del archivo")

    # --- 5. El servidor tiene que exigir que haya informacion ---------------
    # Se busca un trozo corto y de una sola linea: los mensajes del servidor
    # estan partidos en varias lineas para no pasar de ancho, y la frase
    # completa no aparece entera en el archivo.
    if "título ni texto no hay dónde ponerlo" not in val:
        problemas.append(
            "el servidor no avisa de un botón con enlace en un icono sin "
            "información: el botón saldría en una ventana que no existe")

    # --- 6. Y la clave `u`, declarada en los tres sitios ---------------------
    if '"u"' not in val.split("CLAVES_ICONO")[1][:200]:
        problemas.append("`u` no está en CLAVES_ICONO de validar.py")
    if '"u": [' not in editor._campos_icono.__doc__ + "".join(
            editor._campos_icono({"t": "bano", "x": 1, "y": 1,
                                  "u": ["Ver", "https://ejemplo.mx"]})):
        problemas.append("el serializador del servidor no escribe la clave `u`")
    # El orden: `u` va al final, despues de `i`, porque sin la informacion no
    # sirve de nada.
    campos = [p.split(":", 1)[0].strip('"') for p in editor._campos_icono(
        {"t": "bano", "x": 1, "y": 1, "a": "late", "m": 2, "c": 0,
         "i": ["Título", "Texto"], "u": ["Ver", "https://ejemplo.mx"]})]
    if campos != ["t", "x", "y", "a", "m", "c", "i", "u"]:
        problemas.append(f"los campos del botón salen en otro orden: {campos}")

    # --- 7. Lo que se rechaza, llamando a las reglas de verdad --------------
    base = {"t": "bano", "x": 300, "y": 250}
    info = ["Baños", "Los baños están junto al escenario."]
    malos = [
        ({"u": "https://ejemplo.mx"}, "un botón que no es [texto, dirección]"),
        ({"u": ["Ver", "https://ejemplo.mx", "extra"]}, "un botón de tres cosas"),
        ({"u": ["", "https://ejemplo.mx"]}, "un botón sin texto"),
        ({"i": info, "u": ["Ver", "javascript:alert(1)"]}, "un javascript:"),
        ({"i": info, "u": ["Ver", "owncloud.rec.uabc.mx"]}, "un enlace sin esquema"),
        ({"i": info, "u": ["Ver", "data:text/html,<b>x</b>"]}, "un data:"),
        ({"u": ["Ver", "https://ejemplo.mx"]}, "un botón sin información"),
        ({"i": info, "u": ["V" * 41, "https://ejemplo.mx"]}, "un texto muy largo"),
    ]
    for extra, nota in malos:
        salida = v.revisar_iconos([dict(base, **extra)])
        if not salida:
            problemas.append(f"aceptó {nota}")
        elif "icono 1" not in " ".join(salida):
            problemas.append(
                f"{nota} se rechazó, pero no por el icono: {salida}")
    buenos = [
        ({"i": info, "u": ["Ver el programa", "https://owncloud.rec.uabc.mx/x"]},
         "un botón con https"),
        ({"i": info, "u": ["Ver", "http://ejemplo.mx"]}, "un botón con http"),
        ({"i": info}, "un icono con información y sin botón"),
    ]
    for extra, nota in buenos:
        salida = v.revisar_iconos([dict(base, **extra)])
        if salida:
            problemas.append(f"rechazó {nota}: {salida}")

    # Y la función del servidor, directamente, sin pasar por el servidor. Es lo
    # mismo que ya se aprendió una vez: si solo se prueba a través del
    # guardado, un rechazo por otro motivo pasa por bueno.
    for url, esperado in (("https://x.mx", True), ("http://x.mx/a?b=1", True),
                          ("HTTPS://X.MX", True), ("javascript:alert(1)", False),
                          ("data:text/html,x", False), ("x.mx", False),
                          ("//x.mx", False), ("", False), (None, False),
                          (5, False), ("https://x.mx/a b", False)):
        if v.enlace_seguro(url) != esperado:
            problemas.append(
                f"enlace_seguro({url!r}) da {v.enlace_seguro(url)} y debería dar "
                f"{esperado}")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el sello del icono respeta el círculo del mapa, y el enlace del "
          "botón se valida en el croquis, en el editor y en el servidor")
    return True


def test_las_animaciones_se_paran_cuando_no_se_ven() -> bool:
    """Las animaciones no corren cuando nadie las mira, y se reanudan igual.

    Es la optimizacion mas importante del croquis en un movil de gama baja, y
    no se ve en ningun sitio: si alguien la quita sin querer, no falla nada,
    solo vuelve a trabarse en los telefonos.

    Lo que se midio en el navegador, que es el motivo de todo esto: en cuanto
    hay UNA animacion corriendo, el compositor produce un fotograma a la
    frecuencia de la pantalla y no para. Cuesta casi lo mismo con un icono
    animado que con cuarenta (1.69 ms por fotograma con uno, 2.32 ms con
    cuarenta): el gasto esta en el fotograma, no en los iconos. Con cero
    animaciones no produce ninguno.

    Asi que lo unico que sirve de verdad es no producir fotogramas cuando no
    hacen falta. Aqui se comprueba que existan las tres formas de pararlo y
    que ninguna quite la animacion: `animation-play-state` la deja donde
    estaba, asi que al reanudar no dan un salto.
    """
    texto = CROQUIS.read_text(encoding="utf-8")
    problemas = []

    # --- 1. La regla que las para -------------------------------------------
    regla = re.search(r"#m\.frenado \.pausa,\s*\n#m \.pausa\.fuera\{([^}]*)\}",
                      texto)
    if not regla:
        problemas.append(
            "no existe la regla que para las animaciones (`#m.frenado .pausa` y "
            "`#m .pausa.fuera`): el mapa volveria a animar 58 cosas aunque no "
            "se vea ninguna")
    else:
        cuerpo = regla.group(1).replace(" ", "")
        if "animation-play-state:paused" not in cuerpo:
            problemas.append(
                f"la regla de parar no usa `animation-play-state:paused`: {cuerpo}")
        # Parar NO es quitar. Quitar la animacion la reinicia desde el
        # principio, y al reanudar el elemento daria un salto.
        if re.search(r"animation:\s*none", cuerpo):
            problemas.append(
                "la regla de parar quita la animacion (`animation:none`) en vez "
                "de pausarla: al reanudar daria un salto al principio")

        # La regla tiene que ir DESPUES de las que dan animacion a cada clase.
        # Las dos tienen la misma fuerza, asi que decide el orden: puesta antes,
        # las de las zonas la pisaban y el mapa seguia animandose durante el
        # zoom aunque los iconos ya estuvieran parados. Es un fallo que no da
        # ningun error, solo un telefono que se sigue trabando.
        puesto = texto.find("#m.frenado .pausa")
        for cual in ("#zonas .g.za-late", "#zonas .g.zb-camina",
                     "#iconos .an.late", "#iconos .an.viento"):
            if cual in texto and texto.find(cual) > puesto:
                problemas.append(
                    f"la regla de parar esta antes que «{cual}»: como las dos "
                    f"tienen la misma fuerza, gana la animacion y esa no se "
                    f"pararia nunca")

    # --- 2. Los tres motivos para parar -------------------------------------
    # 2a. Mientras el mapa se mueve.
    ini = texto.find("function encuadra(")
    fin = texto.find("\n}", ini)
    if ini < 0:
        problemas.append("(no se encuentra encuadra en el croquis)")
    else:
        cuerpo = texto[ini:fin]
        if "frenaUnRato(" not in cuerpo:
            problemas.append(
                "`encuadra` no para las animaciones: durante el zoom el mapa "
                "entero se reencuadra en cada fotograma y ademas los iconos "
                "siguen animandose, y las dos cosas se pelean por el mismo sitio")
        # Y solo si el encuadre cambia de verdad. En un movil, `resize` salta
        # al esconderse la barra del navegador; sin esta comprobacion, mover el
        # dedo por la pantalla dejaria las animaciones congeladas un rato largo.
        if "=== puesto) return" not in cuerpo and "== puesto) return" not in cuerpo:
            problemas.append(
                "`encuadra` para las animaciones aunque el encuadre no cambie: "
                "en un movil, cada asomo de la barra del navegador las "
                "congelaria sin que nada se mueva")

    # 2b. Con la pagina escondida.
    if "visibilitychange" not in texto:
        problemas.append(
            "no se escucha `visibilitychange`: un mapa abierto en una pestana "
            "de fondo seguiria animandose y gastando bateria")
    elif "document.hidden" not in texto:
        problemas.append(
            "se escucha `visibilitychange` pero no se mira `document.hidden`")

    # 2 quater. Y que NO vuelva la regla que apagaba TODO con el ajuste del
    # sistema. Existio, no hacia nada (las reglas de cada clase la ganaban), y
    # al ponerle `!important` para que por fin funcionara se apago el mapa
    # entero: en un equipo con el ajuste puesto no se movia ni un icono ni una
    # linea, y el sintoma parecia «la animacion no funciona».
    #
    # Se quito a proposito: las animaciones las elige una por una quien edita y
    # son contenido, no adorno de fondo, asi que un ajuste del sistema no debe
    # borrarlas.
    for bloque in re.findall(r"@media\s*\(prefers-reduced-motion[^{]*\{([^@]*?)\n\}",
                             texto, flags=re.S):
        if re.search(r"animation:\s*none", bloque):
            problemas.append(
                "hay una regla de `prefers-reduced-motion` que apaga las "
                "animaciones: en un equipo con ese ajuste puesto, el mapa "
                "entero se queda quieto —los iconos y las lineas— y parece que "
                "la animacion no funciona. Se quito a proposito; si se quiere "
                "recuperar, hay que probarla en un equipo CON el ajuste")

    # 2c. Los iconos que han quedado fuera de la pantalla.
    if "IntersectionObserver" not in texto:
        problemas.append(
            "no hay `IntersectionObserver`: los iconos fuera de la pantalla "
            "seguirian animandose. Ampliado en un movil se ven cuatro o cinco "
            "de los 48, y los otros gastaban lo mismo")
    else:
        # Tiene que haber un margen: sin el, los iconos que asoman por el borde
        # estarian parados y darian un salto al entrar.
        if "rootMargin" not in texto:
            problemas.append(
                "el `IntersectionObserver` no lleva `rootMargin`: los iconos "
                "que asoman por el borde entrarian ya moviendose de golpe")
        if "toggle(\"fuera\"" not in texto:
            problemas.append(
                "el `IntersectionObserver` no pone ni quita la clase «fuera»")

    # --- 3. Que la clase se quite de verdad ---------------------------------
    # Un icono que se queda marcado «fuera» para siempre no se anima nunca mas.
    # Se comprueba que la clase se ponga y se quite segun el resultado, y que
    # al volver a la vista general no quede ninguno marcado.
    if "isIntersecting" not in texto:
        problemas.append(
            "el `IntersectionObserver` no mira `isIntersecting`: no hay forma de "
            "saber si el icono ha vuelto a la pantalla")
    if "sueltaAnimaciones" not in texto:
        problemas.append(
            "no hay forma de soltar el freno: las animaciones se quedarian "
            "paradas para siempre")

    # --- 4. Y que la prueba no pase en balde --------------------------------
    # Todo esto solo sirve si hay animaciones que parar. Sin ninguna, la prueba
    # daria el visto bueno sin comprobar nada.
    iconos = leer_bloque(texto, "ICONOS") or []
    animados = [ic for ic in iconos if ic.get("a")]
    if len(animados) < 10:
        problemas.append(
            f"(solo {len(animados)} iconos animados: la prueba no estaria "
            f"comprobando el caso que importa, que es el mapa lleno)")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print(f"    {len(animados)} animaciones que se paran al esconderse la "
          f"pagina, al moverse el mapa y al quedar fuera de la pantalla, sin "
          f"perderse ninguna")
    return True


def test_los_adornos_de_las_zonas() -> bool:
    """Una zona puede llevar color, linea y movimiento, y sigue siendo opcional.

    Las zonas nacen invisibles: son poligonos transparentes que solo existen
    para recibir el toque, para no tapar el dibujo del mapa. Los adornos son lo
    que las hace visibles en el croquis publicado, y son OPCIONALES: una zona
    sin adornos tiene que quedar escrita y dibujada exactamente igual que antes
    de que existieran. Eso es lo que mas facil se rompe, porque no se nota
    hasta que alguien mira el diff de git y ve las diez zonas cambiadas.

    Se comprueban las tres partes que tienen que decir lo mismo: las reglas del
    servidor, lo que se escribe en el archivo y lo que dibuja el croquis.
    """
    problemas = []
    texto = CROQUIS.read_text(encoding="utf-8")
    val = VALIDAR.read_text(encoding="utf-8")
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. Las listas de animaciones, y que el croquis las dibuje ----------
    # Son dos listas distintas porque son dos cosas distintas: la de la zona
    # mueve el fondo y la linea, y la del borde solo la linea.
    if not v.ANIMACIONES_ZONA or not v.ANIMACIONES_BORDE:
        problemas.append("faltan las listas de animaciones de zona o de borde")
    if "camina" not in v.ANIMACIONES_BORDE:
        problemas.append("`camina` no esta entre las animaciones del borde: es "
                         "la de la linea que avanza, como una carretera")
    # Cada animacion tiene que tener su regla en el croquis, o se elige y no
    # pasa nada.
    for lista, prefijo, cual in ((v.ANIMACIONES_ZONA, "za", "la zona"),
                                 (v.ANIMACIONES_BORDE, "zb", "el borde")):
        for a in lista:
            if a and f"#zonas .g.{prefijo}-{a}" not in texto:
                problemas.append(
                    f"el croquis no tiene regla para la animacion «{a}» de {cual}")

    # Y el sentido de `camina`, que es una regla aparte. Solo lo tiene ella: es
    # la unica que recorre el borde de punta a punta.
    if not v.SENTIDOS_CAMINA:
        problemas.append("`SENTIDOS_CAMINA` esta vacia: no habria nada que elegir")
    if "#zonas .g.zb-camina.zd-reves" not in texto:
        problemas.append(
            "el croquis no tiene la regla de `camina` al reves: se elegiria el "
            "sentido y la linea seguiria avanzando igual, sin dar ningun error")
    # Y se le da la vuelta con `reverse` en vez de con un segundo keyframe: el
    # viaje es el mismo, y dos keyframes serian dos numeros que se pueden
    # separar. El periodo (16) tiene que seguir siendo el mismo. si no, el
    # bucle daria un tiron al llegar al final.
    regla_reves = re.search(r"#zonas \.g\.zb-camina\.zd-reves\{([^}]*)\}",
                            texto, flags=re.S)
    if regla_reves and "reverse" not in regla_reves.group(1):
        problemas.append(
            "la regla de `camina` al reves no lleva `reverse`: seria la misma "
            "animacion y la linea avanzaria hacia el mismo lado")

    # --- 2. Los keyframes, y que `camina` cierre el bucle -------------------
    # El desplazamiento de los guiones tiene que ser EXACTAMENTE un periodo
    # (9 + 7 = 16) para que al repetir no de un tiron. Con 15 o 17, cada vuelta
    # daria un salto visible.
    cuerpo = _cuerpo_de_keyframe(texto, "bordeCamina")
    if cuerpo is None:
        problemas.append("no esta definido el keyframe `bordeCamina`: la linea "
                         "no avanzaria")
    else:
        if "stroke-dashoffset" not in cuerpo:
            problemas.append("`bordeCamina` no mueve `stroke-dashoffset`: los "
                             "guiones no avanzarian por el borde")
        # En negativo: el patron se mueve al reves que el desplazamiento, asi
        # que en positivo la linea pareceria ir hacia atras.
        if not re.search(r"stroke-dashoffset:\s*calc\(\s*-16", cuerpo):
            problemas.append(
                "el desplazamiento de `bordeCamina` no es un periodo exacto en "
                f"negativo: {cuerpo.strip()[:80]}")
        # Y tiene que acabar en `* 1px`. Sin esa unidad el calculo da un numero
        # sin unidad, y el navegador NO lo interpola: el desplazamiento salta de
        # 0 a -16 de golpe y los guiones PARPADEAN en el sitio en vez de
        # avanzar. Medido: 2 valores distintos sin el `1px`, 34 con el.
        #
        # Es un fallo que no da ningun error: la animacion figura como
        # corriendo y el valor final es el correcto, asi que el sintoma se lee
        # como «la animacion no se ve».
        #
        # Se comprueba con un `in` y no con una expresion regular a proposito:
        # el valor lleva `var(--m, 1)` dentro del calc, y un `[^)]*` se para en
        # ese parentesis y no llega a ver el final. Con el trozo de texto no hay
        # forma de equivocarse.
        if "* 1px" not in cuerpo:
            problemas.append(
                "el desplazamiento de `bordeCamina` no lleva `* 1px`: sin esa "
                "unidad el navegador no lo interpola y los guiones parpadean en "
                "el sitio en vez de avanzar por el borde, sin dar ningun error")
    # Y que los guiones de `camina` sean 9 y 7 —que es de donde sale el 16— y
    # que lleven su unidad, por lo mismo.
    regla_camina = re.search(r"#zonas \.g\.zb-camina\{([^}]*)\}", texto, flags=re.S)
    if not regla_camina:
        problemas.append("no existe la regla de `camina` en el croquis")
    else:
        rc = regla_camina.group(1)
        if "9" not in rc or "7" not in rc:
            problemas.append(
                "los guiones de `camina` no son `9 7`: el keyframe da por hecho "
                "ese periodo, asi que los dos numeros tienen que cuadrar")
        if rc.count("* 1px") != 2:
            problemas.append(
                f"los guiones de `camina` tienen que llevar `* 1px` en los dos "
                f"numeros: {rc.strip()}")

    # --- 3. Que una zona sin adornos se escriba como siempre ----------------
    # Es la comprobacion que de verdad importa para no romper lo que ya hay.
    #
    # La zona entra con CINCO campos y el quinto vacio, que es como la manda el
    # editor: siempre manda los mismos campos, rellenos o no. Tiene que salir
    # con cuatro, o guardar desde el editor reescribiria las diez zonas del
    # mapa aunque no se hubiera tocado ninguna. Probar con una zona de cuatro
    # no valdria: esa ya sale bien sola, y el caso que importa es el otro.
    zona = ["Teatro", "Teatro", [[10, 10], [200, 10], [200, 200], [10, 200]],
            "Una descripcion que pasa del minimo.", {}]
    limpia = editor._limpia_zonas([list(zona)])
    if len(limpia[0]) != 4:
        problemas.append(
            f"una zona que llega con los adornos vacios se queda con "
            f"{len(limpia[0])} campos en vez de 4: guardar sin tocar los adornos "
            f"reescribiria las diez zonas del mapa")
    escrito = editor._texto_zonas(limpia)
    if "{" in escrito.split("Una descripcion")[1]:
        problemas.append(f"una zona sin adornos escribe un objeto vacio: {escrito}")
    # Y con adornos, si se escriben. Se parte de los cuatro campos de siempre,
    # no de la zona con el quinto vacio, que si no quedaria con seis.
    con = [list(zona[:4]) + [{"f": "#c8e6c9", "l": "#00723f", "p": 1, "rd": 12,
                              "a": "late", "b": "camina", "d": -1, "m": 2}]]
    escrito2 = editor._texto_zonas(editor._limpia_zonas(con))
    for trozo in ('"f": "#c8e6c9"', '"l": "#00723f"', '"p": 1', '"rd": 12',
                  '"a": "late"', '"b": "camina"', '"d": -1', '"m": 2'):
        if trozo not in escrito2:
            problemas.append(f"al escribir los adornos falta {trozo}")

    # --- 4. Lo que se rechaza ----------------------------------------------
    base = ["Teatro", "Teatro", [[10, 10], [200, 10], [200, 200], [10, 200]],
            "Una descripcion que pasa del minimo."]
    malos = [
        ({"f": "rojo"}, "un color con nombre en vez de #rrggbb"),
        ({"f": "#abc"}, "un color de tres cifras"),
        ({"f": "#gggggg"}, "un color con letras que no son hexadecimales"),
        ({"l": "url(#x)"}, "una url en vez de un color"),
        ({"l": "#00723f", "p": 1, "x": 1}, "una clave que no existe"),
        ({"l": "#00723f", "a": "vuela"}, "una animacion de zona que no existe"),
        ({"l": "#00723f", "b": "vuela"}, "una animacion de borde que no existe"),
        ({"a": "late", "b": "camina"}, "una animacion de borde sin linea"),
        ({"p": 1}, "un punteado sin linea"),
        ({"l": "#00723f", "m": 2}, "una intensidad sin animacion"),
        ({"l": "#00723f", "m": 9}, "una intensidad fuera de rango"),
        ({"l": "#00723f", "b": "late", "d": -1},
         "un sentido con una animacion que no recorre el borde"),
        ({"l": "#00723f", "b": "camina", "d": 2},
         "un sentido que no existe"),
        ({"l": "#00723f", "b": "camina", "d": 0},
         "un sentido de cero, que es ni uno ni otro"),
    ]
    for adornos, nota in malos:
        salida = v.revisar_zonas([base + [adornos]])
        if not salida:
            problemas.append(f"acepto unos adornos con {nota}")
        elif "zona 1" not in " ".join(salida):
            problemas.append(
                f"{nota} se rechazo, pero no por la zona: {salida}")
    buenos = [
        ({"f": "#c8e6c9"}, "solo relleno"),
        ({"l": "#00723f"}, "solo linea"),
        ({"l": "#00723f", "p": 1}, "linea punteada"),
        ({"l": "#00723f", "b": "camina"}, "linea que avanza"),
        ({"l": "#00723f", "b": "camina", "m": 2.5}, "la carretera al maximo"),
        ({"l": "#00723f", "b": "camina", "d": -1}, "la carretera al reves"),
        ({"l": "#00723f", "b": "camina", "d": 1}, "la carretera en su sentido"),
        ({"a": "destello"}, "una zona que destella, sin linea"),
        ({}, "adornos vacios"),
    ]
    for adornos, nota in buenos:
        salida = v.revisar_zonas([base + [adornos]])
        if salida:
            problemas.append(f"rechazo unos adornos con {nota}: {salida}")

    # --- 5. Y que el croquis dibuje lo que se guarda ------------------------
    # De nada sirve guardar el color si el croquis no lo pinta. Se mira que el
    # poligono de la zona coja el relleno, la linea y el punteado, y que el
    # toque siga funcionando: el poligono de una zona con color NO puede perder
    # la pulsacion, o se quedaria sin poder tocarla.
    ini = texto.find("ZON.innerHTML")
    if ini < 0:
        problemas.append("(no se encuentra el render de las zonas en el croquis)")
    else:
        render = texto[ini:texto.find('}).join("");', ini)]
        for pieza, nota in (("a.f", "el relleno"), ("a.l", "la linea"),
                            ("a.p", "el punteado"), ("a.rd", "el redondeo"),
                            ("a.a", "la animacion de la zona"),
                            ("a.b", "la animacion del borde"),
                            ("a.d", "el sentido del borde"),
                            ("contorno(", "el contorno, que es lo que recibe el toque")):
            if pieza not in render:
                problemas.append(f"el render de las zonas no usa {nota}")
        # Sin color, el relleno tiene que seguir siendo transparente: si
        # quedara en negro, las diez zonas taparian el mapa entero.
        if '"transparent"' not in render:
            problemas.append(
                "el render de las zonas no deja el relleno transparente cuando "
                "no hay color: las zonas taparian el mapa")
        # Y que no se dupliquen los puntos en dos formas: el toque y lo que se
        # ve van en el mismo elemento.
        if render.count("<path") > 1 or "<polygon" in render:
            problemas.append(
                "el render de las zonas hace mas de una forma por zona: el "
                "toque y el color tienen que ir en la misma, o los puntos se "
                "pueden desincronizar")

    # --- 5 bis. El contorno redondeado --------------------------------------
    # Se dibuja siempre un <path>, aunque no haya redondeo: con `rd` en 0 tiene
    # que dar exactamente el poligono de siempre, con las esquinas en angulo
    # recto. Si eso fallara, TODAS las zonas del mapa cambarian de forma sin
    # que nadie lo hubiera pedido.
    ini = texto.find("function contorno(")
    if ini < 0:
        problemas.append("no existe `contorno` en el croquis: las esquinas no "
                         "se podrian redondear")
    else:
        cuerpo = texto[ini:texto.find("\n}", ini)]
        # El recorte por el lado es lo que evita que las curvas de dos esquinas
        # se crucen y el contorno se retuerza.
        if "lAnt / 2" not in cuerpo or "lSig / 2" not in cuerpo:
            problemas.append(
                "`contorno` no recorta el redondeo a la mitad del lado: con un "
                "radio mayor que el lado, las curvas se cruzarian y el contorno "
                "se retorceria en un lazo")
        if "Q" not in cuerpo:
            problemas.append("`contorno` no dibuja ninguna curva")
        if '"Z"' not in cuerpo and "'Z'" not in cuerpo:
            problemas.append("`contorno` no cierra el contorno")
    # Y que el editor use el MISMO contorno, o lo que se ve al editar no seria
    # lo que sale despues.
    if "function contorno(" not in edit:
        problemas.append("el editor no tiene su `contorno`: la vista previa no "
                         "podria ensenar el redondeo")

    # Y el redondeo se valida y se escribe.
    if "rd" not in v.CLAVES_ZONA:
        problemas.append("`rd` no esta en CLAVES_ZONA")
    for rd in (0, 61, -1, "mucho"):
        if not v.revisar_zonas([base + [{"rd": rd}]]):
            problemas.append(f"acepto un redondeo de {rd!r}")
    for rd in (1, 30, v.MAX_REDONDEO):
        if v.revisar_zonas([base + [{"rd": rd}]]):
            problemas.append(f"rechazo un redondeo de {rd}")
    # El 0 no se escribe: es «sin redondear», o sea lo de siempre.
    if "rd" in v.limpiar_adornos({"rd": 0, "l": "#00723f"}):
        problemas.append("se guarda un redondeo de 0, que es no redondear nada")
    if "rd" not in v.limpiar_adornos({"rd": 20, "l": "#00723f"}):
        problemas.append("no se guarda el redondeo")
    if '"rd": 20' not in editor._texto_zonas([base[:4] + [{"rd": 20}]]):
        problemas.append("el redondeo no se escribe en el archivo")

    # Y el sentido de `camina` se valida y se escribe, con la misma regla de
    # siempre: lo que sale solo no se guarda. El sentido normal es aquel en el
    # que estan escritos los puntos, asi que solo se escribe el de al reves.
    if "d" not in v.CLAVES_ZONA:
        problemas.append("`d` no esta en CLAVES_ZONA: el sentido no se guardaria")
    for mal_d in (0, 2, -2, "reves", None, True):
        salida = v.revisar_zonas([base + [{"l": "#00723f", "b": "camina",
                                           "d": mal_d}]])
        if not salida:
            problemas.append(f"acepto un sentido de {mal_d!r}")
    for bien_d in (-1, 1):
        salida = v.revisar_zonas([base + [{"l": "#00723f", "b": "camina",
                                          "d": bien_d}]])
        if salida:
            problemas.append(f"rechazo un sentido de {bien_d}: {salida}")
    # Sin `camina` no vale: es la unica que recorre el borde.
    if not v.revisar_zonas([base + [{"l": "#00723f", "b": "late", "d": -1}]]):
        problemas.append("acepto un sentido con una animacion que no es `camina`")
    if "d" not in v.limpiar_adornos({"l": "#00723f", "b": "camina", "d": -1}):
        problemas.append("no se guarda el sentido al reves")
    if "d" in v.limpiar_adornos({"l": "#00723f", "b": "camina", "d": 1}):
        problemas.append(
            "se guarda el sentido normal, que es el que sale solo: llenaria el "
            "archivo de ajustes que no hacen nada")
    escrito3 = editor._texto_zonas(
        editor._limpia_zonas([base[:4] + [{"l": "#00723f", "b": "camina",
                                           "d": -1}]]))
    if '"d": -1' not in escrito3:
        problemas.append(f"el sentido no se escribe en el archivo: {escrito3}")
    # Y el orden: el sentido va pegado a la animacion del borde, que es de la
    # unica que es. Leerlo lejos de ella obligaria a buscarlo.
    if escrito3.index('"b"') > escrito3.index('"d"'):
        problemas.append("el sentido se escribe antes que la animacion del "
                         "borde, y es cosa de ella")

    # --- 6. Que la prueba no pase en balde ----------------------------------
    if not v.CLAVES_ZONA:
        problemas.append("`CLAVES_ZONA` esta vacia: no se validaria nada")
    # Las dos listas tienen que llegar al editor desde el servidor: si el editor
    # tuviera su propia copia, un dia diria cosas distintas que las que valida
    # el servidor y se podria elegir una animacion que luego rebota.
    if "animacionesZona" not in edit or "animacionesBorde" not in edit:
        problemas.append(
            "(el editor no lee las animaciones de zona del servidor: se estaria "
            "eligiendo de una lista que puede no coincidir con la que valida)")
    # Y el sentido, por lo mismo: lo manda el servidor, que es quien valida.
    if "sentidosCamina" not in edit:
        problemas.append("(el editor no lee del servidor los sentidos de `camina`)")
    if "sentidosCamina" not in editor.leer_croquis.__doc__ and \
            "sentidosCamina" not in Path("editor/editor.py").read_text(encoding="utf-8"):
        problemas.append("el servidor no manda los sentidos de `camina` al editor")
    # Las dos animaciones de una zona tienen que poder convivir. Se declaran
    # como variables y las junta una sola regla porque `animation` es una
    # taquigrafia: con una declaracion por clase, la ultima borra la anterior y
    # una zona con animacion de zona Y de borde se quedaba solo con la del
    # borde, sin dar ningun error.
    for nombre, hoja, prefijo in (("el croquis", texto, "#zonas .g"),
                                  ("el editor", edit, "#gZonas .z")):
        mezcla = re.search(re.escape(prefijo) + r"\{animation:var\(--az, none\), "
                           r"var\(--ab, none\)\}", hoja)
        if not mezcla:
            problemas.append(
                f"{nombre} no junta las dos animaciones en una sola regla: con "
                f"una declaracion por clase, la de la zona se pierde")
        for var, familia in (("--az", "za"), ("--ab", "zb")):
            for a in (v.ANIMACIONES_ZONA if familia == "za" else v.ANIMACIONES_BORDE):
                if a and f"{prefijo}.{familia}-{a}" not in hoja:
                    problemas.append(f"{nombre} no define {familia}-{a}")
                if a and f"{var}:" not in hoja:
                    problemas.append(f"{nombre} no usa la variable {var}")
    if '"animacionesZona"' not in editor.__dict__.get("__doc__", "") and \
            "animacionesZona" not in editor.leer_croquis.__doc__ and \
            "animacionesZona" not in Path("editor/editor.py").read_text(encoding="utf-8"):
        problemas.append("el servidor no manda las animaciones de zona al editor")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print(f"    {len(v.ANIMACIONES_ZONA) - 1} animaciones de zona y "
          f"{len(v.ANIMACIONES_BORDE) - 1} de borde, con el relleno, la linea y "
          f"el punteado opcionales: una zona sin adornos se queda como estaba")
    return True


def _sin_comentarios(texto: str) -> str:
    """El croquis sin comentarios, que es donde puede haber codigo.

    Los comentarios no ejecutan nada y en el croquis son utiles: avisan de
    que hay un editor y de que los marcadores no se pueden borrar. Lo que se
    vigila es el codigo, asi que se quitan antes de mirar.
    """
    texto = re.sub(r"/\*.*?\*/", " ", texto, flags=re.S)
    texto = re.sub(r"<!--.*?-->", " ", texto, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", texto, flags=re.M)


def test_el_croquis_publicado_no_edita_nada() -> bool:
    """El croquis que abre el QR no puede modificar el mapa.

    Es la razón de que el editor sea un programa aparte. Aquí se comprueba que
    la página publicada no tenga con qué escribir: ni formularios, ni llamadas
    que manden datos a ningún sitio, ni nada que cargue código de fuera.

    Una página suelta en GitHub Pages no puede escribir en el repositorio de
    todas formas, pero eso es una garantía de la plataforma. Esto comprueba
    que además el archivo no lleve la puerta puesta.

    Y de paso vigila los enlaces de salida, que son lo único que puede apuntar
    fuera: no pueden ser javascript: y, si abren en pestaña nueva, tienen que
    llevar rel="noopener" o la página de destino puede manipular esta.
    """
    texto = _sin_comentarios(CROQUIS.read_text(encoding="utf-8"))

    # Nada de formularios: no hay campos que rellenar ni nada que enviar.
    for etiqueta in ("<form", "<input", "<textarea", "contenteditable"):
        if etiqueta in texto:
            print(f"    (el croquis publicado lleva un {etiqueta}: puede editarse)")
            return False

    # Nada de hablar con un servidor. El croquis se carga solo: su unica
    # peticion es la imagen del mapa, que va con <image href>.
    for llamada in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket",
                    "<script src", "<link", "import(", "navigator.send"):
        if llamada in texto:
            print(f"    (el croquis publicado usa {llamada}: carga o manda algo)")
            return False

    # Ni formas de guardar nada en el equipo de quien mira el mapa.
    for escritura in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        if escritura in texto:
            print(f"    (el croquis publicado usa {escritura})")
            return False

    # Los enlaces de salida. Un <a href> no carga nada por si solo: solo
    # navega cuando alguien lo pulsa, asi que puede apuntar a donde haga
    # falta. Lo que no puede es ser un javascript: ni abrirse en pestana
    # nueva sin noopener.
    enlaces = re.findall(r"<a\b([^>]*)>", texto)
    for atributos in enlaces:
        href = re.search(r'href="([^"]*)"', atributos)
        if not href or href.group(1).startswith(("javascript:", "data:", "vbscript:")):
            print("    (hay un <a> sin href o con un esquema peligroso: "
                  f"{atributos.strip()[:60]})")
            return False
        if 'target="_blank"' in atributos and "noopener" not in atributos:
            print(f"    (el enlace a {href.group(1)} abre en pestana nueva sin "
                  "rel=\"noopener\")")
            return False

    # Lo que se CARGA solo si tiene que ser de casa: el croquis tiene que
    # verse sin depender de nadie, ni aunque no haya internet mas alla del
    # propio archivo. Se quitan antes los <a> para no confundirlos con
    # recursos: un enlace no se carga.
    sin_enlaces = re.sub(r"<a\b[^>]*>", " ", texto)
    cargados = re.findall(r'(?:src|href)="([^"]+)"', sin_enlaces)
    ajenos = [r for r in cargados if r.startswith(("http://", "https://", "//"))]
    if ajenos:
        print(f"    (el croquis publicado carga recursos de fuera: {', '.join(ajenos)})")
        return False

    print("    sin formularios, sin peticiones y sin codigo de fuera")
    return True


def test_el_editor_rechaza_lo_ajeno() -> bool:
    """El editor solo atiende en local y no escribe nada que no valide.

    Se levanta el servidor de verdad en un puerto libre y se le ataca como lo
    haría una página web abierta en el mismo equipo: con un Host que no es
    localhost. Si el editor atendiera esa petición, cualquier web podría
    usarlo de puente para escribir en el croquis y subirlo a GitHub.

    Y de paso se comprueba lo más importante: que un guardado inválido NO
    toque el archivo. A medias sería peor que no escribir, porque el croquis
    quedaría publicado con la mitad del cambio.
    """
    import threading
    from http.server import ThreadingHTTPServer

    antes = CROQUIS.read_bytes()
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), editor.Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    base = f"http://127.0.0.1:{puerto}"
    problemas = []
    try:
        # El manejador escribe cada peticion a stderr. Dentro de una prueba eso
        # solo ensucia la salida y hace que PowerShell la tome por un error.
        with contextlib.redirect_stderr(io.StringIO()):
            # 1. Host ajeno: se rechaza con 403.
            peticion = urllib.request.Request(
                base + "/api/estado", headers={"Host": "sitio-ajeno.example"})
            try:
                with urllib.request.urlopen(peticion, timeout=5) as r:
                    problemas.append(f"aceptó un Host ajeno ({r.status})")
            except urllib.error.HTTPError as e:
                if e.code != 403:
                    problemas.append(f"con Host ajeno esperaba 403 y dio {e.code}")

            # 2. Guardar zonas que se solapan: se rechaza con 400 y no se escribe.
            malas = [
                ["Una", "Una", [[100, 100], [400, 100], [400, 400], [100, 400]],
                 "Una zona cualquiera."],
                ["Otra", "Otra", [[200, 200], [500, 200], [500, 500], [200, 500]],
                 "Otra zona encima."]]
            peticion = urllib.request.Request(
                base + "/api/guardar",
                data=json.dumps({"zonas": malas, "iconos": []}).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(peticion, timeout=5) as r:
                    problemas.append(f"aceptó dos zonas solapadas ({r.status})")
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    problemas.append(f"con zonas solapadas esperaba 400 y dio {e.code}")

            # 3. Los iconos malos. Todas estas peticiones llevan TAMBIÉN las
            #    zonas de verdad, y no una lista vacía: un croquis sin zonas se
            #    rechaza por su cuenta, así que con la lista vacía todo daba
            #    400 y la prueba pasaba sin haber mirado un solo icono. Pasó
            #    justo eso: la validación de los iconos se quedó muerta en un
            #    refactor y esta prueba siguió en verde.
            zonas_reales = leer_bloque(CROQUIS.read_text(encoding="utf-8"), "ZONAS")

            def guardar_iconos(iconos: list) -> tuple:
                """Manda a guardar unos iconos y devuelve (código, mensaje)."""
                peticion = urllib.request.Request(
                    base + "/api/guardar",
                    data=json.dumps({"zonas": zonas_reales, "iconos": iconos}).encode("utf-8"),
                    method="POST", headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(peticion, timeout=5) as r:
                        return r.status, ""
                except urllib.error.HTTPError as e:
                    return e.code, e.read().decode("utf-8", "replace")

            # 4. Iconos que tienen que rebotar: un tipo que no existe, un giro
            #    imposible, una animación que el croquis no sabe hacer, una
            #    información a la que le falta el texto, un círculo que no es
            #    0 ni 1 y una clave mal escrita.
            rotos = [
                ({"t": "inventado", "x": 100, "y": 100}, "un tipo inventado"),
                ({"t": "bano", "x": 100, "y": 100, "r": 9999}, "un giro imposible"),
                ({"t": "bano", "x": 100, "y": 100, "a": "temblar"}, "una animación inventada"),
                ({"t": "bano", "x": 100, "y": 100, "i": ["Solo título", "  "]},
                 "información sin texto"),
                ({"t": "bano", "x": 100, "y": 100, "c": 2}, "un círculo que no es 0 ni 1"),
                ({"t": "bano", "X": 100, "y": 100}, "una clave mal escrita"),
            ]
            for icono, etiqueta in rotos:
                codigo, cuerpo = guardar_iconos([icono])
                if codigo == 200:
                    problemas.append(f"aceptó un icono con {etiqueta}")
                elif codigo != 400:
                    problemas.append(f"con {etiqueta} esperaba 400 y dio {codigo}")
                elif "icono 1" not in cuerpo:
                    # 400 por el motivo equivocado: si el mensaje no habla del
                    # icono, es que rebotó por otra cosa y no se comprobó nada.
                    problemas.append(
                        f"con {etiqueta} dio 400, pero no por el icono: "
                        f"{cuerpo.strip()[:70]}")

            # 5. Y uno bien formado, con todo, sí tiene que entrar. Es la otra
            #    mitad de la prueba: un validador que lo rechaza todo no vale.
            #
            #    Este paso SÍ escribe en el croquis, así que al terminar se
            #    deja como estaba. Se comprueba antes de restaurar, que es lo
            #    único que se puede comprobar.
            codigo, cuerpo = guardar_iconos([
                {"t": "bano", "x": 300, "y": 250, "n": "Baños",
                 "s": 60, "r": -30, "a": "late", "c": 0,
                 "i": ["Baños", "Los baños están junto al escenario."]}])
            if codigo != 200:
                problemas.append(f"rechazó un icono completo: {codigo} {cuerpo[:80]}")

            # 6. Lo que quedó escrito tiene que ser ese icono, entero y con
            #    todos sus campos, y en el formato que lee el croquis.
            escrito = CROQUIS.read_text(encoding="utf-8")
            for clave, valor in (("a", '"late"'), ("r", "-30"), ("s", "60"),
                                 ("c", "0"), ("x", "300"), ("y", "250")):
                if f'"{clave}": {valor}' not in escrito:
                    problemas.append(f"el icono bueno no se escribió con «{clave}»")
            if "Los baños están junto al escenario." not in escrito:
                problemas.append("la información del icono no se escribió")
    finally:
        # Pase lo que pase, el croquis vuelve a como estaba. Una prueba que
        # deja su basura en el archivo es peor que no tenerla: al dia
        # siguiente nadie sabe de donde salió ese icono.
        CROQUIS.write_bytes(antes)
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    rechaza Host ajeno, zonas solapadas, tipos inventados, giros y")
    print("    animaciones imposibles y claves mal escritas, sin tocar el archivo")
    return True


def _literales_de_los_return(texto: str, inicio: int = 0) -> list[str]:
    """Junta los trozos de texto de cada `return` que arma HTML.

    Los trozos de HTML se escriben encadenados con +, y ahi esta el peligro:
    una comilla que falta no se ve en ningun trozo suelto, solo en el
    resultado de pegarlos. Por eso no basta con mirar cada literal por su
    cuenta (que es lo que hacia antes esta prueba) y hay que reconstruir lo
    que saldria.

    Se recorre el texto buscando `return`, se salta los textos de verdad y se
    para en el `;` que cierra la sentencia. Los trozos entrecomillados que hay
    dentro se pegan en orden: las expresiones que van en medio desaparecen,
    que es justo lo que interesa, porque asi queda la plantilla con los
    huecos, y en esa plantilla se ve si un atributo se queda sin comilla.
    """
    plantillas = []
    n = len(texto)
    i = 0
    while True:
        j = texto.find("return", i)
        if j < 0:
            break
        # Que sea la palabra `return` y no parte de otra.
        antes = texto[j - 1] if j else " "
        if antes.isalnum() or antes in "_$":
            i = j + 6
            continue

        trozos, k, comilla = [], j + 6, None
        while k < n:
            c = texto[k]
            if comilla:
                if c == "\\":
                    k += 2
                    continue
                if c == comilla:
                    comilla = None
                else:
                    trozos.append(c)
            elif c in "\"'`":
                comilla = c
            elif c == ";":
                break
            k += 1
        plantilla = "".join(trozos)
        # Solo interesan las plantillas que arman etiquetas.
        if "<" in plantilla and "=" in plantilla:
            plantillas.append(plantilla)
        i = k + 1
    return plantillas


def _atributo_sin_cerrar(plantilla: str) -> str:
    """El primer atributo que abre comilla y no la cierra antes del '>'.

    Se recorren las etiquetas de la plantilla. Dentro de cada una, cada vez
    que aparece `="` se busca la comilla que lo cierra; si antes aparece el
    `>` de la etiqueta, es que falta.
    """
    for etiqueta in re.findall(r"<[^<>]*>", plantilla):
        k = 0
        while True:
            a = etiqueta.find('="', k)
            if a < 0:
                break
            cierra = etiqueta.find('"', a + 2)
            if cierra < 0:
                return etiqueta
            k = cierra + 1
    return ""


def test_ningun_literal_cierra_una_etiqueta_sin_comilla() -> bool:
    """Ninguna etiqueta armada en JavaScript cierra un atributo sin su comilla.

    Cerrar la etiqueta antes de cerrar la comilla del atributo es el fallo
    mas facil de cometer al encadenar textos, y se cometio dos veces en este
    proyecto. El navegador se traga media etiqueta, el atributo se queda con
    basura dentro y el elemento no se dibuja: en el croquis eso deja el mapa
    sin iconos y lo unico que sale es un aviso en la consola, que nadie mira.

    Al principio esta prueba miraba cada trozo entrecomillado por su cuenta y
    buscaba un `)>` dentro. No bastaba: los trozos van encadenados con +, y la
    comilla que falta puede estar al final de un trozo y el `>` al principio
    del siguiente, con lo que ninguno de los dos tiene el rastro completo.
    Ahora se pegan los trozos de cada `return` como los pegaria el navegador
    y se mira el resultado, que es donde el fallo se ve siempre.
    """
    problemas = []
    for archivo in (CROQUIS, Path("editor/editor.html")):
        if not archivo.is_file():
            print(f"    (no existe {archivo})")
            return False
        for plantilla in _literales_de_los_return(archivo.read_text(encoding="utf-8")):
            malo = _atributo_sin_cerrar(plantilla)
            if malo:
                problemas.append(f"{archivo.name}: {malo[:70]}")

    if problemas:
        for p in problemas:
            print(f"    {p}")
        print("    Falta la comilla que cierra el atributo antes del '>'.")
        print("    El navegador se traga media etiqueta y el elemento no se dibuja.")
        return False
    print("    ninguna etiqueta armada en JavaScript se queda sin cerrar")
    return True


def _sin_cadenas_ni_comentarios(texto: str) -> str:
    """El texto sin comentarios, sin cadenas y sin expresiones regulares.

    Hace falta para poder contar parentesis, corchetes y llaves: dentro de una
    cadena o de un comentario no cuentan, y `"("` no abre nada. Se recorre
    caracter a caracter porque el orden importa: un `//` dentro de una cadena
    no es un comentario, y una comilla dentro de un comentario no abre una
    cadena. Mirar uno y luego el otro se equivoca siempre en algun caso.
    """
    fuera = []
    i, n = 0, len(texto)
    # El ultimo caracter significativo, para saber si un `/` abre una
    # expresion regular o es una division. Es la heuristica de siempre: tras
    # un operador, un parentesis o una coma, `/` abre una regex.
    anterior = ""
    while i < n:
        c = texto[i]
        if c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "*":
            fin = texto.find("*/", i + 2)
            i = n if fin < 0 else fin + 2
            continue
        if c in "'\"`":
            comilla, i = c, i + 1
            while i < n:
                if texto[i] == "\\":
                    i += 2
                    continue
                if texto[i] == comilla:
                    i += 1
                    break
                # Una cadena sin cerrar no puede colar el resto del archivo.
                if texto[i] == "\n" and comilla != "`":
                    break
                i += 1
            anterior = comilla
            continue
        if c == "/" and (anterior == "" or anterior in "(,=:[!&|?{};+-*%~^<>"):
            # Expresion regular: se salta hasta el `/` que la cierra, sin
            # contar los que van dentro de una clase [^/].
            i += 1
            dentro_clase = False
            while i < n:
                if texto[i] == "\\":
                    i += 2
                    continue
                if texto[i] == "[":
                    dentro_clase = True
                elif texto[i] == "]":
                    dentro_clase = False
                elif texto[i] == "/" and not dentro_clase:
                    i += 1
                    break
                elif texto[i] == "\n":
                    break
                i += 1
            anterior = "/"
            continue
        fuera.append(c)
        if not c.isspace():
            anterior = c
        i += 1
    return "".join(fuera)


def test_el_javascript_cuadra() -> bool:
    """El JavaScript de los dos archivos tiene los cierres que abre.

    Un parentesis de mas o de menos en el `<script>` deja la pagina entera en
    blanco: no se dibujan ni las zonas ni los iconos, y lo unico que sale es un
    `Unexpected token` en la consola del navegador, que nadie mira. Paso de
    verdad al añadir el circulo opcional: un `)` de mas en una funcion de tres
    lineas tumbo el mapa entero.

    No es un validador de JavaScript, es un contador de cierres. No entiende la
    sintaxis, pero caza el error de tecleo que mas veces deja estos archivos
    muertos, y lo caza antes de abrir el navegador.
    """
    parejas = {")": "(", "]": "[", "}": "{"}
    problemas = []
    for archivo in (CROQUIS, Path("editor/editor.html")):
        texto = archivo.read_text(encoding="utf-8")
        for k, bloque in enumerate(re.findall(r"<script[^>]*>(.*?)</script>",
                                              texto, flags=re.S)):
            limpio = _sin_cadenas_ni_comentarios(bloque)
            pila = []
            for pos, c in enumerate(limpio):
                if c in "([{":
                    pila.append((c, pos))
                elif c in parejas:
                    if not pila:
                        linea = limpio.count("\n", 0, pos) + 1
                        problemas.append(
                            f"{archivo.name} (script {k + 1}): sobra un «{c}» "
                            f"sobre la línea {linea}")
                        break
                    abierto, _ = pila.pop()
                    if abierto != parejas[c]:
                        linea = limpio.count("\n", 0, pos) + 1
                        problemas.append(
                            f"{archivo.name} (script {k + 1}): se cierra con "
                            f"«{c}» lo que se abrió con «{abierto}», sobre la "
                            f"línea {linea}")
                        break
            else:
                if pila:
                    abierto, pos = pila[-1]
                    linea = limpio.count("\n", 0, pos) + 1
                    problemas.append(
                        f"{archivo.name} (script {k + 1}): se abre «{abierto}» "
                        f"sobre la línea {linea} y no se cierra")

    if problemas:
        for p in problemas:
            print(f"    {p}")
        print("    Un cierre de mas o de menos deja la pagina en blanco y solo")
        print("    se ve un «Unexpected token» en la consola del navegador.")
        return False
    print("    los cierres del JavaScript cuadran en los dos archivos")
    return True


def test_los_modelos_se_guardan_y_se_estamplan() -> bool:
    """Un modelo guardado se puede estampar tal cual en el mapa.

    Un modelo es un icono guardado entero menos la posicion: el tipo, el
    tamano, el giro, la animacion, el circulo y la informacion. Al pulsarlo y
    hacer clic en el mapa se pone uno igual.

    Se comprueba el viaje completo: guardarlo, que el icono que sale de el
    pase las reglas del mapa, y que el archivo de modelos no acabe con cosas
    que el croquis rechazaria. Es el fallo que mas caro saldria: un modelo mal
    guardado no se nota al guardarlo, sino al estampar veinte iconos con el.
    """
    import tempfile

    # El archivo de modelos se escribe de verdad, asi que se apunta a uno
    # temporal durante la prueba y se deja el de verdad como estaba. Sin esto,
    # cada pasada por las pruebas borraria los modelos del usuario.
    original = editor.MODELOS
    problemas = []
    with tempfile.TemporaryDirectory() as carpeta:
        editor.MODELOS = Path(carpeta) / "modelos.json"
        try:
            # 1. Uno completo entra.
            guardado = editor.guarda_modelo("Puesto de comida", {
                "t": "comida", "x": 700, "y": 400, "n": "Puesto de comida",
                "s": 70, "r": -15, "a": "late", "c": 0,
                "i": ["Puesto de comida", "Aquí se sirve comida."]}, {})
            if guardado["nombre"] != "Puesto de comida":
                problemas.append("no se guardó con el nombre que se pidió")

            leidos = editor.lee_modelos()
            if len(leidos) != 1:
                problemas.append(f"se esperaba 1 modelo y hay {len(leidos)}")
            # 2. La posicion NO se guarda: la elige quien estampa.
            if "x" in leidos[0]["i"] or "y" in leidos[0]["i"]:
                problemas.append("el modelo guardó una posicion")
            # 3. Pero todo lo demas si.
            for clave in ("t", "n", "s", "r", "a", "c", "i"):
                if clave not in leidos[0]["i"]:
                    problemas.append(f"el modelo perdió «{clave}» al guardarse")

            # 4. Y lo que sale de un modelo tiene que valer como icono del mapa.
            estampado = dict(leidos[0]["i"], x=600, y=300)
            problemas.extend(v.revisar_iconos([estampado], {}))

            # 5. Volver a guardar con el mismo nombre reemplaza, no acumula.
            editor.guarda_modelo("Puesto de comida", {"t": "comida", "s": 90}, {})
            leidos = editor.lee_modelos()
            if len(leidos) != 1:
                problemas.append("volver a guardar con el mismo nombre acumuló")
            elif leidos[0]["i"].get("s") != 90:
                problemas.append("volver a guardar no actualizó el modelo")

            # 6. Un nombre vacío o un icono sin tipo se rechazan.
            for malo, etiqueta in ((("", {"t": "bano"}), "sin nombre"),
                                   (("X", {"n": "sin tipo"}), "sin tipo")):
                try:
                    editor.guarda_modelo(malo[0], malo[1], {})
                    problemas.append(f"aceptó un modelo {etiqueta}")
                except editor.ErrorEditor:
                    pass

            # 7. Y quitarlo funciona y no deja rastro.
            editor.borra_modelo("Puesto de comida", {})
            if editor.lee_modelos():
                problemas.append("quitar el modelo lo dejó en el archivo")
            try:
                editor.borra_modelo("No existe", {})
                problemas.append("quitar un modelo que no está no dio error")
            except editor.ErrorEditor:
                pass
        finally:
            editor.MODELOS = original

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el modelo guarda el icono entero menos la posición y se estampa igual")
    return True


def test_el_circulo_se_puede_quitar() -> bool:
    """Un icono puede ir sin el círculo de fondo, y el croquis lo respeta.

    El círculo se guarda como `"c": 0` y solo cuando se quita: los que lo
    llevan —que son la mayoría— no llenan el archivo de repetir lo de siempre.

    Aquí se comprueba la cadena entera, que es donde está el peligro: que el
    servidor escriba la clave, que el croquis la lea sin confundir el 0 con la
    ausencia, y que los tres sitios que dibujan un icono (el mapa, la ventana y
    la miniatura del editor) usen la misma regla. Un `if (!ic.c)` en cualquiera
    de ellos trataría el 0 como «no está» y el círculo seguiría saliendo.
    """
    import tempfile

    problemas = []
    for archivo, etiqueta in ((CROQUIS, "el croquis"),
                              (Path("editor/editor.html"), "el editor")):
        texto = archivo.read_text(encoding="utf-8")
        # La comprobación tiene que distinguir el 0 de la ausencia.
        if '("c" in ic)' not in texto:
            problemas.append(
                f"{etiqueta}: no comprueba «c» con `in`, así que un `c: 0` "
                f"se confundiría con no llevarlo")
        # Y tiene que haber una regla para el icono sin círculo.
        if "sinAro" not in texto:
            problemas.append(f"{etiqueta}: no hay ningún estilo para el icono sin círculo")

    # El 0 tiene que sobrevivir al viaje de ida y vuelta por el serializador.
    ejemplo = {"t": "bano", "x": 100, "y": 100, "c": 0}
    escrito = editor._texto_iconos([ejemplo])
    if '"c": 0' not in escrito:
        problemas.append(f"el serializador perdió el círculo apagado: {escrito!r}")
    if v.revisar_iconos([ejemplo], {}):
        problemas.append("un icono sin círculo no pasa las reglas")

    # Y con el círculo puesto no se escribe nada, para no llenar el archivo.
    con_aro = {"t": "bano", "x": 100, "y": 100}
    if '"c"' in editor._texto_iconos([con_aro]):
        problemas.append("un icono con círculo escribe una clave que no hace falta")

    # Un valor que no sea 0 ni 1 se rechaza.
    if not v.revisar_iconos([{"t": "bano", "x": 100, "y": 100, "c": 5}], {}):
        problemas.append("aceptó un círculo que no es 0 ni 1")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el círculo se puede quitar y el 0 no se confunde con la ausencia")
    return True


def test_los_ajustes_del_icono_propio_viajan() -> bool:
    """Un icono subido guarda con qué se configuró, y eso vuelve con él.

    Al subir una imagen se eligen el tamaño, la animación y si lleva círculo.
    Esos ajustes se guardan al lado del PNG en la biblioteca, así que al volver
    a poner ese icono en el mapa sale como se dejó y no con los de fábrica.

    Sin esto, subir un extintor sin círculo y con animación obliga a
    configurarlo cada vez que se pone uno, y con veinte puestos eso es veinte
    veces el mismo trabajo.

    Se usa una carpeta temporal: esta prueba escribe de verdad, y hacerlo en
    `editor/iconos/` borraría o pisaría las imágenes que tenga quien edita.
    """
    import io
    import tempfile

    from PIL import Image, ImageDraw

    original = editor.BIBLIOTECA
    problemas = []
    with tempfile.TemporaryDirectory() as carpeta:
        editor.BIBLIOTECA = Path(carpeta)
        try:
            # Una imagen mínima, como la que subiría alguien.
            img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse([20, 20, 180, 180], fill=(200, 60, 40, 255))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            datos_url = ("data:image/png;base64,"
                         + base64.b64encode(buf.getvalue()).decode("ascii"))

            nombre, datos, contenido, extension, quitado = editor.preparar_icono(
                datos_url, "Extintor.png", set())
            if nombre != "extintor-png":
                problemas.append(f"el nombre salió «{nombre}» y se esperaba «extintor-png»")
            if extension != "png":
                problemas.append(f"un PNG se guardó con extensión «{extension}»")

            ajustes = {"s": 16, "a": "flota", "c": 0}
            editor.guarda_en_biblioteca(nombre, contenido, extension, ajustes)

            # 1. Vuelven al leerlo, que es lo que hace falta para recuperarlo.
            leido = editor.lee_de_biblioteca(nombre)
            if leido["ajustes"] != ajustes:
                problemas.append(f"los ajustes volvieron como {leido['ajustes']}")
            if not leido["datos"].startswith("data:image/png;base64,"):
                problemas.append("la imagen no volvió como data URL de PNG")

            # 2. Y se ven en la lista, para poder enseñarlos antes de recuperar.
            en_lista = editor.lista_biblioteca({})
            if len(en_lista) != 1 or en_lista[0]["ajustes"] != ajustes:
                problemas.append(f"la lista no lleva los ajustes: {en_lista}")

            # 3. Un icono que está en el croquis no se lista: ya se ve en la paleta.
            if editor.lista_biblioteca({nombre: "x"}):
                problemas.append("un icono que ya está en el croquis sigue en Guardados")

            # 4. Se lee con los ajustes ya puestos y sirve para estampar.
            estampado = dict(ajustes, t=nombre, x=400, y=300)
            problemas.extend(v.revisar_iconos([estampado], {nombre: datos}))

            # 5. Borrar se lleva el PNG y sus ajustes: no deja el JSON huérfano.
            editor.borra_de_biblioteca(nombre)
            if list(Path(carpeta).glob("*")):
                problemas.append(
                    f"borrar dejó rastro: {[p.name for p in Path(carpeta).glob('*')]}")
            try:
                editor.lee_de_biblioteca(nombre)
                problemas.append("se pudo leer un icono ya borrado")
            except editor.ErrorEditor:
                pass

            # 6. Y un SVG por el mismo camino, para que las dos rutas acaben
            #    en el mismo sitio y con las mismas reglas.
            nombre_v, datos_v, contenido_v, ext_v, _ = editor.preparar_icono(
                "data:image/svg+xml;base64,"
                + base64.b64encode(_SVG_DE_PRUEBA).decode("ascii"),
                "Escudo.svg", {nombre})
            if ext_v != "svg":
                problemas.append(f"un SVG se guardó con extensión «{ext_v}»")
            if not datos_v.startswith("data:image/svg+xml;base64,"):
                problemas.append(f"el SVG no volvió como data URL de SVG: {datos_v[:40]}")
            editor.guarda_en_biblioteca(nombre_v, contenido_v, ext_v, {"s": 90})
            leido_v = editor.lee_de_biblioteca(nombre_v)
            if not leido_v["vector"]:
                problemas.append("el SVG recuperado no se marcó como vector")
            if leido_v["ajustes"].get("s") != 90:
                problemas.append("el SVG perdió sus ajustes")
            if not v.revisar_iconos([{"t": nombre_v, "x": 300, "y": 300}],
                                    {nombre_v: datos_v}):
                pass  # pasa por diseño: solo se comprueba que no reviente
            else:
                problemas.append("un icono con SVG no pasó las reglas")

            # El borrado se lleva las dos extensiones si el mismo nombre las
            # tuviera: borrar solo una dejaría el icono a medias.
            (Path(carpeta) / f"{nombre_v}.png").write_bytes(b"x")
            editor.borra_de_biblioteca(nombre_v)
            sobra = [p.name for p in Path(carpeta).glob(f"{nombre_v}.*")]
            if sobra:
                problemas.append(f"borrar un SVG dejó sus hermanos: {sobra}")
        finally:
            editor.BIBLIOTECA = original

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    los ajustes y el formato viajan con el icono, en PNG y en SVG")
    return True


# Un SVG pequeño para las pruebas: formas, un degradado, un `url(#interno)` que
# tiene que sobrevivir, y la basura que tiene que desaparecer.
_SVG_DE_PRUEBA = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">\n'
    b'  <script>alert("fuera")</script>\n'
    b'  <defs><linearGradient id="cuerpo">'
    b'<stop offset="0" stop-color="#e63946"/>'
    b'<stop offset="1" stop-color="#8d1f2a"/></linearGradient></defs>\n'
    b'  <rect x="20" y="10" width="24" height="44" rx="4" fill="url(#cuerpo)"/>\n'
    b'  <circle cx="32" cy="32" r="28" fill="none" stroke="#333" onclick="alert(1)"/>\n'
    b'  <image href="https://malo.example/x.png" width="8" height="8"/>\n'
    b'</svg>')


def test_los_svg_se_limpian_y_no_se_pixelan() -> bool:
    """Un SVG subido como icono se limpia, se guarda entero y no se reduce.

    Un PNG se guarda a 160 px de lado, y los iconos del mapa se amplían hasta
    cuatro veces con el zoom: estirado a 1700 px se ve pixelado. Un SVG son
    órdenes de dibujar, así que se ve igual de nítido a cualquier tamaño. Por
    eso NO se reduce: reducir un vector sería destruir justo lo que lo hace
    bueno.

    Y por eso mismo se limpia en vez de rechazarlo. Lo que se quita es lo que
    un icono no puede llevar —scripts, manejadores `on…`, referencias a otros
    sitios— y nada más: los degradados, los filtros y los `url(#interno)`, que
    son la mayoría de un dibujo de verdad, se quedan.

    (Aunque el SVG se dibuje en un `<image>`, donde el navegador no ejecuta
    nada, la limpieza se hace igual: el archivo puede acabar abriéndose solo,
    y un SVG que viaja dentro de un documento ajeno no debería llevar según
    qué.)
    """
    import tempfile

    problemas: list[str] = []

    # 1. Lo que se quita y lo que se queda.
    limpio, quitado = vec.prepara(_SVG_DE_PRUEBA)
    for etiqueta in ("script", "onclick", "malo.example"):
        if etiqueta in limpio:
            problemas.append(f"el SVG limpio todavía lleva «{etiqueta}»")
    for etiqueta in ("url(#cuerpo)", "linearGradient", "rx="):
        if etiqueta not in limpio:
            problemas.append(f"la limpieza se llevó por delante «{etiqueta}»")
    if not quitado:
        problemas.append("no se quitó nada, y el SVG traía script, onclick y una image de fuera")
    if b"<image" in _SVG_DE_PRUEBA and "<image" in limpio:
        problemas.append("quedó un <image> sin su href, que no dibuja nada")
    # Y sigue siendo un SVG de una sola pieza.
    if not limpio.startswith("<svg") or not limpio.rstrip().endswith("</svg>"):
        problemas.append(f"el SVG limpio no empieza y acaba donde debe: {limpio[:40]}")
    if "\n" in limpio:
        problemas.append("el SVG limpio quedó con saltos de línea: no se minificó")

    # 2. Un vector NO se reduce: se guarda tal cual, así que no se pixela.
    #    Se compara con lo que pesaría el mismo dibujo en PNG a 160 px.
    with tempfile.TemporaryDirectory() as carpeta:
        original = editor.BIBLIOTECA
        editor.BIBLIOTECA = Path(carpeta)
        try:
            url = "data:image/svg+xml;base64," + base64.b64encode(
                _SVG_DE_PRUEBA).decode("ascii")
            nombre, datos, contenido, ext, _ = editor.preparar_icono(url, "Escudo.svg", set())
            if ext != "svg":
                problemas.append(f"un SVG acabó con extensión «{ext}»")
            if contenido != limpio.encode("utf-8"):
                problemas.append("lo que se guardó no es el SVG limpio")
            # Y vale como icono del mapa, con las reglas de siempre.
            problemas.extend(v.revisar_iconos(
                [{"t": nombre, "x": 300, "y": 300, "s": 120}], {nombre: datos}))

            # 3. Un SVG roto o sin con qué escalar se rechaza con un motivo.
            for crudo, etiqueta, esperado in (
                    (b'<svg xmlns="http://www.w3.org/2000/svg">x', "roto", "bien formado"),
                    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
                     "sin viewBox", "viewBox"),
                    (b'<html><body>hola</body></html>', "que no es un SVG", "no un <svg>"),
                    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">'
                     b'<script>x</script></svg>', "que solo era un script", "nada")):
                try:
                    vec.prepara(crudo)
                    problemas.append(f"aceptó un SVG {etiqueta}")
                except vec.SvgInvalido as e:
                    if esperado not in str(e):
                        problemas.append(
                            f"el SVG {etiqueta} se rechazó, pero el motivo no lo "
                            f"explica: {str(e)[:60]}")

            # 4. Y el tope de peso es el suyo, más alto que el de una imagen:
            #    un vector pesado sigue siendo nítido y vale la pena.
            if not (MAX_VECTOR > MAX_ICONO):
                problemas.append(
                    f"el tope del vector ({MAX_VECTOR}) no es mayor que el de "
                    f"la imagen ({MAX_ICONO})")
        finally:
            editor.BIBLIOTECA = original

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el SVG se limpia, se guarda entero y no se reduce como una imagen")
    return True


def test_atributos_sin_comillas_no_se_tragan() -> bool:
    """Ningun valor de atributo sin comillas puede terminar en '/>'.

    En HTML, un valor sin comillas sigue tragandose caracteres hasta el
    espacio, y la '/' cuenta como parte del valor. Escribiendo
    'fill=#16241c/>' el parser lee fill="#16241c/" y la etiqueta nunca se
    cierra: se traga todo el dibujo y el mapa sale en negro, sin ningun
    error en la consola. Es un fallo silencioso, asi que se vigila con una
    expresion regular en vez de confiar en la vista.
    """
    fallos = []
    # Se ignoran los comentarios de linea: un comentario que explica el fallo
    # contiene el patron tragao y daria un falso positivo. El '//' de un
    # 'https://' va precedido de ':', no de espacio, asi que sobrevive.
    patron_comentario = re.compile(r"(?m)(?:^|\s)//[^\n]*")
    patron = r"""=\s*([^\s"'=<>/]+)/>"""
    for origen in sorted(Path("plantilla").glob("*.html")):
        texto = patron_comentario.sub("", origen.read_text(encoding="utf-8"))
        for encontrado in re.finditer(patron, texto):
            fallos.append(f"{origen.name}: valor sin comillas terminado en '/>' -> ...{encontrado.group(0)}")
    for fallo in fallos:
        print(f"    {fallo}")
    return not fallos


def test_modo_enlace_es_una_url() -> bool:
    """El modo por defecto pone solo la URL en el QR, sin fragmento.

    Es el modo que da el QR más pequeño: si el documento ya está publicado,
    meterlo dentro del QR es tirar bytes. También tiene que ser una URL
    http de verdad, porque es lo que abrirá el lector del móvil.
    """
    salida = Path("_tmp_enlace")
    salida.mkdir(exist_ok=True)
    try:
        if ejecutar_main("--html", "plantilla/croquis.html",
                         "--salida", str(salida / "q"), "--nivel", "H") != 0:
            return False
        url = leer_qr(salida / "q.png")
        if url != g.URL_HTML:
            print(f"    (el QR no contiene la URL del HTML: {url!r})")
            return False
        if not url.startswith("https://"):
            print("    (el QR no es una URL https)")
            return False
        if "#" in url or "javascript:" in url:
            print("    (el QR lleva fragmento o javascript:, no es un enlace simple)")
            return False
        # El documento tiene que existir en el repo, y ser autónomo: si el QR
        # solo lleva la URL, el archivo publicado tiene que abrir solo.
        destino = Path(url.split("github.io/OrgulloCimarron/", 1)[-1])
        if not destino.is_file():
            print(f"    (la URL apunta a {destino}, que no está en el repo)")
            return False
        crudo = destino.read_text(encoding="utf-8")
        if g.revisar_autonomo(crudo):
            print("    (el HTML publicado tiene recursos externos: no abrirá solo)")
            return False
        print(f"    {len(url)} chars -> {destino} ({len(crudo)} bytes, autónomo)")
        return True
    finally:
        shutil.rmtree(salida, ignore_errors=True)


def test_colores_legibles() -> bool:
    """Todos los colores institucionales se leen, y aguantan el desgaste.

    Un QR de color se escanea peor que uno en negro, asi que esto no es
    opcional: se genera con cada paleta y se lee con zxing-cpp, primero tal
    cual y luego con las degradaciones tipicas de un cartel impreso (mas
    pequeno, menos contraste, con poca luz y en blanco y negro).
    """
    salida = Path("_tmp_color")
    salida.mkdir(exist_ok=True)
    # El negro es la referencia: si una degradacion le falla a el tambien, es
    # que la degradacion es demasiado agresiva y no mide nada del color.
    degradaciones = {
        "normal": lambda im: im,
        "55% tamano": lambda im: im.resize((int(im.width * .55), int(im.height * .55)),
                                           Image.LANCZOS),
        "contraste 50%": lambda im: ImageEnhance.Contrast(im).enhance(0.5),
        "luz baja": lambda im: ImageEnhance.Brightness(im).enhance(0.6),
        "blanco y negro": lambda im: im.convert("L"),
    }
    problemas = []
    try:
        for nombre in sorted(g.PALETAS):
            prefijo = salida / nombre
            if ejecutar_main("--html", "plantilla/croquis.html", "--salida", str(prefijo),
                             "--nivel", "H", "--color", nombre) != 0:
                problemas.append(f"{nombre}: no se pudo generar")
                continue
            with Image.open(prefijo.with_suffix(".png")) as original:
                imagen = original.convert("RGB")
                for etiqueta, transformar in degradaciones.items():
                    temporal = salida / f"{nombre}_{etiqueta.replace(' ', '_')}.png"
                    transformar(imagen).save(temporal)
                    if not leer_qr(temporal):
                        problemas.append(f"{nombre}: no se lee con '{etiqueta}'")
                    temporal.unlink(missing_ok=True)
    finally:
        shutil.rmtree(salida, ignore_errors=True)

    for problema in problemas:
        print(f"    {problema}")
    if problemas:
        return False
    print(f"    {len(g.PALETAS)} colores x {len(degradaciones)} pruebas: todos legibles")
    return True


def test_minificado_conserva_estructura() -> bool:
    """El minificador no rompe las piezas que sostienen el render."""
    crudo = Path("plantilla/plantilla.html").read_text(encoding="utf-8")
    html = g.minificar(crudo)
    return all([
        "<style>" in html and "</style>" in html,
        'content:""' in html,
        "onclick=" in html,
        "charset=utf-8" in html,
        html.lower().startswith("<!doctype html>"),
        g.revisar_autonomo(crudo) == [],
    ])


def test_alfabeto_y_viaje() -> bool:
    """El fragmento solo usa caracteres seguros y hace round-trip."""
    html = g.minificar("<p>áéíóú ñ 🔥</p>")
    for comprimir in (False, True):
        fragmento = g.limpiar_html(html, comprimir=comprimir)
        if set(fragmento) - set(g.PESO):
            print(f"    (caracteres fuera del alfabeto con comprimir={comprimir})")
            return False
        if decodificar(fragmento, comprimir) != html:
            print(f"    (round-trip fallo con comprimir={comprimir})")
            return False
    return True


def test_legibilidad_por_tamano() -> bool:
    """La version del QR crece con los datos; debe seguir siendo legible."""
    carga = "https://ejemplo.com/a.html#" + "A" * 2600
    resultados = {nivel: escanear_texto(carga, nivel, box=4) for nivel in ("L", "M")}
    for nivel, ok in resultados.items():
        print(f"    nivel {nivel}: {'legible' if ok else 'FALLA'}")
    return all(resultados.values())


def test_exceso_se_reporta() -> bool:
    """Un documento imposible debe salir con codigo de error, no con traceback.

    El relleno tiene que ser incompresible: una tira de 'a' repetidas la
    reduce gzip a unas decenas de bytes y entraria de sobra en el QR.

    Va en modo 'servidor' a proposito: en modo 'enlace' el documento no viaja
    en el QR, asi que da igual que sea enorme y la prueba no probaria nada.
    """
    relleno = base64.b64encode(os.urandom(6000)).decode("ascii")
    grande = Path("_tmp_grande.html")
    grande.write_text("<p>" + relleno + "</p>", encoding="utf-8")
    ruta_salida = Path("_tmp_salida")
    ruta_salida.mkdir(exist_ok=True)
    try:
        codigo = ejecutar_main("--html", str(grande), "--salida", str(ruta_salida / "x"),
                               "--nivel", "H", "--modo", "servidor",
                               "--publicar-en", str(ruta_salida))
        if codigo == 0:
            print("    (un documento de 8000 bytes deberia exceder el nivel H)")
            return False
        # Y no debe haber dejado archivos a medias.
        return not any(ruta_salida.iterdir())
    finally:
        grande.unlink(missing_ok=True)
        shutil.rmtree(ruta_salida, ignore_errors=True)


def test_el_editor_avisa_si_quedo_viejo() -> bool:
    """Un editor abierto antes del ultimo cambio de codigo guarda a medias.

    Es el fallo mas caro que puede tener esta herramienta, y paso de verdad:
    al anadir el redondeo de las esquinas, el editor que estaba abierto no
    conocia la clave, la tiraba al limpiar los adornos y escribia el croquis
    sin ella. Guardar parecia ir bien, no saltaba ningun error, y lo que
    llegaba a GitHub eran las zonas sin redondear. Lo perdido no se recupera:
    nadie sabe que se perdio.

    El servidor carga los .py UNA vez, al arrancar, asi que la unica forma de
    notarlo desde dentro es comparar el codigo que tiene cargado con el que hay
    ahora mismo en el disco.
    """
    import tempfile

    problemas: list[str] = []
    raiz = Path(__file__).resolve().parent
    fuente = (raiz / "editor" / "editor.py").read_text(encoding="utf-8")
    pagina = (raiz / "editor" / "editor.html").read_text(encoding="utf-8")

    # --- 1. La huella, calculada con el codigo de verdad --------------------
    # Se llama dos veces: tiene que dar lo mismo y tener forma de sha1 corto.
    # Si dependiera de algo que cambia entre llamadas (la hora, el respaldo,
    # los iconos), el editor se creeria viejo siempre y no dejaria guardar.
    huella = editor.huella_del_codigo()
    if not re.fullmatch(r"[0-9a-f]{12}", huella):
        problemas.append(f"la huella no tiene forma de sha1 corto: {huella!r}")
    if huella != editor.huella_del_codigo():
        problemas.append("la huella cambia entre dos llamadas seguidas")
    if '"*.py"' not in fuente:
        problemas.append(
            "la huella no se calcula sobre los .py del editor: mirar la "
            "carpeta entera la haria cambiar con cada guardado")

    # --- 2. Un proceso viejo se niega a guardar -----------------------------
    # El croquis de verdad se apunta a un temporal: si la comprobacion no
    # saltara, la validacion rechazaria el envio vacio y no se tocaria nada,
    # pero mas vale no depender de eso para no romper el mapa al probar.
    original = (editor.CROQUIS, editor.RESPALDO, editor.HUELLA_ARRANQUE)
    with tempfile.TemporaryDirectory() as carpeta:
        falso = Path(carpeta) / "croquis.html"
        falso.write_text("var ZONAS = [];\n", encoding="utf-8")
        editor.CROQUIS = falso
        editor.RESPALDO = Path(carpeta) / "respaldo"
        editor.HUELLA_ARRANQUE = "0" * 12
        try:
            editor.guardar_croquis([], [], {})
        except editor.ErrorEditor as e:
            # El mensaje tiene que decir QUE hacer, no solo que algo va mal.
            if "viejo" not in str(e) or "editor.py" not in str(e):
                problemas.append(f"el aviso no dice como arreglarlo: {e}")
        else:
            problemas.append(
                "guardo con el codigo viejo: es el caso que hizo perder el "
                "redondeo de las esquinas sin dejar rastro")
        finally:
            editor.CROQUIS, editor.RESPALDO, editor.HUELLA_ARRANQUE = original

    # Y al dia tiene que dejar pasar la comprobacion: si no, no se guardaria
    # nunca y el editor quedaria inservible.
    if editor.huella_del_codigo() != editor.HUELLA_ARRANQUE:
        problemas.append(
            "la huella de arranque no cuadra con la del disco: el editor se "
            "creeria viejo nada mas abrirlo")

    # --- 3. Y la pagina lo ensena y apaga el guardado -----------------------
    # De nada sirve detectarlo si la unica señal es un error al pulsar
    # Guardar: hay que verlo al abrir y no poder perder el tiempo editando.
    for aguja, queja in (
            ('"codigoViejo"', "/api/estado no manda `codigoViejo`"),
            ('id="reinicia"', "falta el aviso de editor viejo en la pagina"),
            ("E.codigoViejo = !!d.codigoViejo",
             "la pagina no se queda con lo que manda el servidor"),
            ("E.codigoViejo ||",
             "el boton de Guardar no se apaga con el editor viejo"),
            ("btnSubir\").disabled = E.codigoViejo",
             "el boton de Subir no se apaga con el editor viejo"),
            ("if (E.codigoViejo) {",
             "guardar() no corta por su cuenta con el editor viejo")):
        if aguja not in pagina and aguja not in fuente:
            problemas.append(queja)

    for p in problemas:
        print(f"  - {p}")
    return not problemas


def test_las_pestanas_del_editor() -> bool:
    """El panel esta partido en pestañas, y ninguna deja nada fuera.

    El panel era una columna larga con siete bloques seguidos: para encontrar
    algo habia que recorrerla entera. Ahora son cuatro pestañas, una por cosa.
    Lo que se puede romper al partir un panel no es el aspecto, es que un
    bloque se quede sin pestaña: entonces media herramienta desaparece de la
    vista y nada avisa, porque el HTML sigue ahi.
    """
    problemas: list[str] = []
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. Una pestaña por hoja, y sin repetir ------------------------------
    pestanas = re.findall(r'class="pestana".*?data-panel="(\w+)"', edit, flags=re.S)
    hojas = re.findall(r'class="hoja" data-panel="(\w+)"', edit)
    if len(pestanas) < 2:
        problemas.append("no hay pestañas en el panel")
    if len(set(pestanas)) != len(pestanas):
        problemas.append(f"hay pestañas repetidas: {pestanas}")
    if pestanas != hojas:
        problemas.append(
            f"las pestañas y sus hojas no cuadran: pestañas {pestanas} y hojas "
            f"{hojas}. Una pestaña sin hoja ensena un panel vacio, y una hoja "
            f"sin pestaña no se puede abrir")

    # --- 2. Nada se queda fuera de una pestaña -------------------------------
    # Se parte el archivo por donde empieza cada hoja: trozos[0] es lo de antes
    # de la primera (los avisos y la tira de pestañas) y el resto, una por
    # hoja. Un bloque tiene que estar en UNA, y solo en una.
    trozos = re.split(r'<div class="hoja" data-panel="\w+">', edit)
    if len(trozos) != len(pestanas) + 1:
        problemas.append(
            f"se cuentan {len(trozos) - 1} trozos de panel para {len(pestanas)} "
            f"pestañas: alguna hoja se abre o se cierra de mas")
    for id_ in ("listaZonas", "bloqueForm", "paleta", "bloqueIcono",
                "bloqueAlinear", "bloqueModelos", "infoGit", "infoMapa",
                "enlacePublicado"):
        donde = [n for n, t in enumerate(trozos) if f'id="{id_}"' in t]
        if not donde:
            problemas.append(f"«{id_}» no esta dentro de ninguna pestaña: "
                             f"quedaria fuera de la vista")
        elif len(donde) > 1:
            problemas.append(f"«{id_}» esta en mas de una pestaña: {donde}")

    # --- 3. Los avisos, fuera de las pestañas --------------------------------
    # Es lo primero que se mira antes de guardar. Meterlos en una pestaña seria
    # esconderlos justo cuando hacen falta.
    if 'id="avisos"' not in trozos[0]:
        problemas.append(
            "los avisos tienen que quedar FUERA de las pestañas, siempre a la "
            "vista: dentro solo se ven si se acierta con la pestaña")

    # --- 4. Se cambia de pestaña, y se recuerda cual --------------------------
    if "function ponPestana(" not in edit:
        problemas.append("no existe `ponPestana`: las pestañas no cambiarian")
    if "dataset.panel === nombre" not in edit:
        problemas.append("`ponPestana` no marca la pestaña que esta puesta")
    # El nombre guardado se comprueba antes de usarlo. Si no, al renombrar una
    # pestaña lo que quede en el navegador no valdria y el panel se veria
    # vacio, sin decir por que.
    if "pestana[data-panel=" not in edit:
        problemas.append(
            "`ponPestana` no comprueba que la pestaña pedida exista: con un "
            "nombre viejo guardado en el navegador, el panel saldria vacio")
    # Y elegir algo en el mapa lleva a la pestaña que lo edita.
    if "ponPestana(sel.tipo === \"zona\"" not in edit:
        problemas.append(
            "elegir una zona o un icono no cambia de pestaña: se toca una zona "
            "y sus datos pueden estar en una pestaña que no se ve")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print(f"    {len(pestanas)} pestañas ({', '.join(pestanas)}) con sus hojas, "
          f"los avisos siempre a la vista y los controles en su sitio")
    return True


def test_quitar_vertices_de_una_zona() -> bool:
    """Se puede quitar una esquina sin tener que adivinar el doble clic.

    Quitar una esquina ya existia, pero SOLO con doble clic encima del punto,
    y eso no lo descubre nadie. Ahora hay un boton. Lo que hay que vigilar es
    que sea el mismo camino que el doble clic -dos formas de hacer lo mismo se
    separan al primer descuido- y que no deje la zona con menos de tres
    esquinas, que seria un poligono que no se puede dibujar.
    """
    problemas = []
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. El boton existe y esta puesto --------------------------------
    if 'id="btnQuitarVertice"' not in edit:
        problemas.append("no hay boton para quitar una esquina")
    if 'getElementById("btnQuitarVertice")' not in edit:
        problemas.append("el boton de quitar esquina no esta enganchado")
    if "function quitaVertice(" not in edit:
        problemas.append("no existe `quitaVertice`")

    # --- 2. El boton y el doble clic son el MISMO camino ---------------------
    # Si cada uno borrara por su cuenta, el dia que se cambie una regla la otra
    # se queda con la vieja, y quitar por el boton haria algo distinto que
    # quitar con doble clic.
    doble = re.search(r's\.addEventListener\("dblclick".*?\n\}\);', edit, flags=re.S)
    if not doble:
        problemas.append("no se encuentra el manejador del doble clic")
    else:
        if "quitaVertice()" not in doble.group(0):
            problemas.append(
                "el doble clic no llama a `quitaVertice`: habria dos formas de "
                "quitar una esquina que se pueden separar")
        if ".splice(" in doble.group(0):
            problemas.append("el doble clic quita la esquina por su cuenta, en "
                             "vez de usar el mismo camino que el boton")
    # Y que solo haya UN sitio donde se quita de verdad.
    if edit.count(".splice(verticeSel, 1)") != 1:
        problemas.append("la esquina se quita en mas de un sitio, o en ninguno")

    # --- 3. Nunca por debajo de tres ----------------------------------------
    if "menos de 3 esquinas" not in edit:
        problemas.append(
            "quitar una esquina no avisa del minimo: una zona de dos esquinas "
            "no es un poligono y el croquis la dibujaria mal")
    # Y hay que marcar antes: son dos acciones a proposito, porque quitar una
    # esquina no se puede deshacer.
    if "Pulsa antes la esquina" not in edit:
        problemas.append("no se pide marcar la esquina antes de quitarla")

    # --- 4. La marca ---------------------------------------------------------
    if "var verticeSel = null" not in edit:
        problemas.append("no se lleva la cuenta de que esquina esta marcada")
    # La marca es un indice DENTRO de una zona: al cambiar de zona hay que
    # soltarla, o quitar se llevaria por delante un punto de otra.
    if "verticeSel = null;" not in edit:
        problemas.append("la marca de la esquina no se limpia nunca")
    if edit.count("verticeSel = null;") < 3:
        problemas.append(
            "la marca solo se limpia en un sitio: hay que soltarla al cambiar "
            "de zona y al meter una esquina nueva, porque los indices se corren")
    if '"acto"' not in edit:
        problemas.append("la esquina marcada no se distingue de las demas")
    if "#gZonas circle.acto{" not in edit:
        problemas.append("no hay regla para la esquina marcada")
    # Y va DESPUES de `.mal`: en una zona con problemas hay que poder ver cual
    # esta marcada, y el filo rojo lo llevan todas las esquinas por igual.
    if "#gZonas circle.mal{" in edit and \
            edit.index("#gZonas circle.mal{") > edit.index("#gZonas circle.acto{"):
        problemas.append("la regla de la esquina marcada va antes que la de "
                         "los problemas, y el rojo la taparia")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    boton y doble clic comparten el mismo camino, con la esquina "
          "marcada a la vista y el minimo de 3 esquinas respetado")
    return True


def test_la_ventana_solo_se_abre_con_el_mapa_acercado() -> bool:
    """La ventana de informacion solo sale con una zona ampliada.

    Con el mapa entero delante los iconos son marcas de referencia: si
    respondieran al toque, una ventana encima taparia justo lo que se estaba
    mirando, y ademas no se podria acercar la zona que hay debajo porque el
    icono se comeria la pulsacion. Se apagan las dos cosas a la vez -el toque y
    el filo verde que lo promete-, porque un adorno que anuncia algo que no
    pasa es peor que no tenerlo.
    """
    problemas = []
    texto = CROQUIS.read_text(encoding="utf-8")

    # --- 1. El mapa dice si esta acercado --------------------------------
    ini = texto.find("function pinta(")
    if ini < 0:
        problemas.append("(no se encuentra `pinta` en el croquis)")
    else:
        cuerpo = texto[ini:texto.find("\n}", ini)]
        if "deCerca" not in cuerpo:
            problemas.append(
                "`pinta` no avisa de si el mapa esta acercado: los iconos con "
                "informacion no tendrian forma de saberlo")
        if "k >= 0" not in cuerpo:
            problemas.append("`pinta` no mira si hay una zona elegida")

    # --- 2. Y el toque se apaga de verdad --------------------------------
    # El filo verde, el cursor y el `pointer-events` tienen que depender de la
    # misma clase: si el `pointer-events` no se apaga, el icono se come la
    # pulsacion y no se puede acercar la zona de debajo.
    if "#iconos .conInfo{pointer-events:auto" in texto:
        problemas.append(
            "los iconos con informacion reciben el toque SIEMPRE: con el mapa "
            "entero delante no se podria acercar la zona que tienen debajo")
    if "#iconos.deCerca .conInfo{pointer-events:auto}" not in texto:
        problemas.append(
            "el toque de los iconos con informacion no depende de `deCerca`")
    if "#iconos.deCerca .conInfo .aro{" not in texto:
        problemas.append(
            "el filo verde de los iconos con informacion se ve siempre: estaria "
            "prometiendo un toque que con el mapa entero no hace nada")

    # --- 3. Y aunque el toque llegara, la ventana no se abre --------------
    # Doble red: el CSS puede fallar -un navegador raro, una regla que se
    # pierde-, y lo que no puede pasar es que salga la ventana sin zoom.
    i = texto.find('ICN.addEventListener("click"')
    if i < 0:
        problemas.append("(no se encuentra el manejador del clic de los iconos)")
    else:
        cuerpo = texto[i:texto.find("\n});", i)]
        if "A < 0" not in cuerpo and "A >= 0" not in cuerpo:
            problemas.append(
                "el clic de un icono abre la ventana sin mirar si el mapa esta "
                "acercado: con el mapa entero taparia lo que se estaba mirando")
    # Y el que corta el toque para que no llegue al mapa tiene que mirarlo
    # tambien: sin zoom el toque tiene que ACERCAR la zona de debajo.
    i = texto.find('ICN.addEventListener("pointerdown"')
    if i >= 0:
        cuerpo = texto[i:texto.find("\n});", i)]
        if "A >= 0" not in cuerpo:
            problemas.append(
                "el icono se come el toque aunque no haya zoom: pulsarlo no "
                "acercaria la zona que tiene debajo")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el filo, el cursor y el toque de los iconos con informacion "
          "dependen del zoom, y la ventana no se abre sin el")
    return True


def test_los_recursos_y_el_boton_del_mapa() -> bool:
    """Un boton puede llevar a un archivo de RecursosExtra, y hay dos botones.

    El de la ventana de un icono y el del panel del mapa se eligen igual. Lo
    que hay que vigilar es que la carpeta no sea una puerta abierta -una ruta
    con `..` apuntaria a cualquier sitio del repositorio-, que el croquis y el
    servidor opinen lo mismo sobre lo que es una imagen, y que el texto y la
    direccion no acaben escritos en dos sitios que se puedan separar.
    """
    problemas = []
    texto = CROQUIS.read_text(encoding="utf-8")
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. La carpeta no es una puerta abierta ---------------------------
    for bueno in ("RecursosExtra/plan.pdf", "RecursosExtra/plano final.jpg",
                  "RecursosExtra/a.png"):
        if not v.es_destino(bueno):
            problemas.append(f"rechazo un recurso que vale: {bueno}")
    for malo in ("RecursosExtra/../../etc/passwd", "RecursosExtra/a/b.png",
                 "RecursosExtra/", "RecursosExtra/.oculto",
                 "RecursosExtra/plan.exe?x=1", "../RecursosExtra/plan.pdf",
                 "javascript:alert(1)", "plan.pdf", "", None):
        if v.es_destino(malo):
            problemas.append(f"acepto un destino que no vale: {malo!r}")
    # Y lo de fuera sigue valiendo.
    for url in ("https://owncloud.rec.uabc.mx/x", "http://a.b/c"):
        if not v.es_destino(url):
            problemas.append(f"rechazo una direccion que vale: {url}")

    # --- 2. El boton del mapa: sus reglas ---------------------------------
    bien = {"t": "Programa del evento", "u": "RecursosExtra/plan.pdf"}
    if v.revisar_enlace(bien):
        problemas.append(f"rechazo un boton bueno: {v.revisar_enlace(bien)}")
    if v.revisar_enlace(None) or v.revisar_enlace({}):
        problemas.append("un croquis sin boton tiene que ser valido")
    for malo, nota in (({"t": "", "u": "https://a.b"}, "sin texto"),
                       ({"t": "x" * 60, "u": "https://a.b"}, "con texto larguisimo"),
                       ({"t": "x", "u": "javascript:alert(1)"}, "con codigo de destino"),
                       ({"t": "x", "u": "RecursosExtra/../a"}, "apuntando fuera"),
                       ({"t": "x"}, "sin destino"),
                       ({"t": "x", "u": "https://a.b", "z": 1}, "con una clave rara")):
        if not v.revisar_enlace(malo):
            problemas.append(f"acepto un boton {nota}")
    # Y a medias no se guarda nada: o entero o nada.
    if v.limpiar_enlace({"t": "x"}) is not None:
        problemas.append("un boton sin destino se guarda a medias")
    if v.limpiar_enlace({"t": " x ", "u": " RecursosExtra/a.png "}) != \
            {"t": "x", "u": "RecursosExtra/a.png"}:
        problemas.append("el boton no se limpia de espacios al guardarlo")

    # --- 3. Ida y vuelta por el archivo -----------------------------------
    # Es lo que hace que el editor pueda volver a abrir lo que escribio.
    escrito = editor._texto_enlace(bien)
    if '"t": "Programa del evento"' not in escrito or '"u": "RecursosExtra/plan.pdf"' not in escrito:
        problemas.append(f"el boton no se escribe entero: {escrito}")
    if editor._texto_enlace(None) != "var ENLACE = null;":
        problemas.append(f"un croquis sin boton no escribe `null`: "
                         f"{editor._texto_enlace(None)}")

    # --- 4. Y el croquis lo lee -------------------------------------------
    if "/* === INICIO ENLACE === */" not in texto:
        problemas.append("falta el bloque ENLACE en el croquis: el editor no "
                         "tendria donde escribir el boton")
    # La lista de lo que es una imagen tiene que ser la MISMA en los tres
    # sitios. El croquis decide que hacer al pulsar y el editor lo que dice al
    # elegir; ninguno puede preguntarle al otro en ese momento, asi que la
    # unica forma de que no se separen es comprobarlo aqui.
    lista = re.search(r"var IMAGENES = \[([^\]]*)\]", texto)
    if not lista:
        problemas.append("el croquis no tiene la lista de extensiones de imagen")
    else:
        en_croquis = tuple(x.strip().strip('"') for x in lista.group(1).split(","))
        if en_croquis != v.EXTENSIONES_IMAGEN:
            problemas.append(
                f"la lista de imagenes del croquis {en_croquis} no es la del "
                f"servidor {v.EXTENSIONES_IMAGEN}: un archivo se abriria de una "
                f"forma al elegirlo y de otra al pulsarlo")
    # Y la carpeta tiene que estar donde el croquis la busca: el croquis vive
    # en plantilla/, asi que sube un nivel.
    if '"../" + CARPETA_RECURSOS' not in texto:
        problemas.append(
            "el croquis no sube un nivel para llegar a RecursosExtra: la "
            "carpeta esta en la raiz y el croquis dentro de plantilla/")

    # --- 5. El editor ofrece lo que hay, y solo lo que vale ---------------
    for aguja, queja in (
            ('id="mDestino"', "el editor no tiene el selector del boton del mapa"),
            ('id="mBoton"', "el editor no tiene la casilla del boton del mapa"),
            ("opcionesDeDestino", "el editor no arma la lista de destinos"),
            ("PREFIJO_RECURSOS", "el editor no conoce la carpeta de recursos"),
            ("enlace: E.enlace",
             "el editor no manda el boton al guardar: se perderia al guardar")):
        if aguja not in edit:
            problemas.append(queja)
    if "recursos" not in editor.leer_recursos.__doc__ and \
            "recursos" not in Path("editor/editor.py").read_text(encoding="utf-8"):
        problemas.append("el servidor no manda la lista de RecursosExtra")
    # Un archivo que no pase `es_recurso` no se puede ofrecer: el editor
    # dejaria elegir algo que el guardado rechazaria.
    fuente = Path("editor/editor.py").read_text(encoding="utf-8")
    if "es_recurso" not in fuente:
        problemas.append("el servidor ofrece archivos sin comprobar que valgan")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    RecursosExtra con su forma comprobada, el boton del mapa "
          "editable y la misma lista de imagenes en el croquis y el servidor")
    return True


def test_los_vectores_se_publican_como_pesen_menos() -> bool:
    """Un vector pasa a PNG al publicarlo, pero solo si el PNG pesa menos.

    La idea de partida era convertir todo a PNG para que el movil trabaje menos
    al dibujarlo. Medido, sale al reves: los 17 vectores del mapa ocupan 75 KB
    y pasados a PNG de 256 px serian 271 KB, porque el SVG de un dibujo plano
    pesa poquisimo y el PNG de un dibujo con curvas suaves pesa mucho -cada
    borde rebajado es una orla de colores que el formato no sabe resumir-.
    Convertirlos a ciegas haria el croquis TRES VECES mas pesado, que es justo
    lo contrario de lo que se buscaba.

    Asi que se prueba y se queda lo que ocupe menos, icono por icono. Con los
    de ahora no cambia ninguno; el dia que se suba un dibujo complicado se
    convierte solo.
    """
    problemas = []
    edit = EDITOR_HTML.read_text(encoding="utf-8")

    # --- 1. La conversion existe ------------------------------------------
    for aguja, queja in (
            ("function svgAPng(", "no hay forma de convertir un SVG a PNG"),
            ("async function propiosParaPublicar()",
             "no hay nada que prepare los iconos antes de publicarlos"),
            ("propiosParaPublicar()", "`guardar` no convierte antes de mandar"),
            ("data:image/svg+xml", "la conversion no mira de que tipo es cada icono")):
        if aguja not in edit:
            problemas.append(queja)

    # --- 2. Y solo cambia cuando de verdad pesa menos ---------------------
    # Es LA comprobacion de esta prueba. Sin ella, la conversion se hace
    # siempre y el croquis engorda en vez de adelgazar.
    i = edit.find("async function propiosParaPublicar(")
    if i < 0:
        problemas.append("(no se encuentra propiosParaPublicar)")
    else:
        cuerpo = edit[i:edit.find("\n}", i)]
        if "png.length < uri.length" not in cuerpo:
            problemas.append(
                "no se compara el peso antes de cambiar: convertir a ciegas "
                "haria el croquis tres veces mas pesado con estos dibujos")
        if "cambiados.push" not in cuerpo:
            problemas.append(
                "no se lleva la cuenta de lo que se convirtio: no se podria "
                "decir al guardar, y el cambio seria invisible")

    # --- 3. El editor vuelve a trabajar con el archivo original -----------
    # Si no, un icono subido en SVG volveria al editor convertido a PNG, se
    # perderia el original y el croquis publicado pasaria a ser la fuente.
    if "def propios_para_editar(" not in \
            Path("editor/editor.py").read_text(encoding="utf-8"):
        problemas.append("el servidor no devuelve los iconos como se editan")
    if "propios_para_editar(datos[\"propios\"])" not in \
            Path("editor/editor.py").read_text(encoding="utf-8"):
        problemas.append(
            "`/api/estado` manda los iconos tal como estan en el croquis, ya "
            "convertidos: se perderia el vector original al volver a editar")

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    el vector se convierte a PNG solo cuando pesa menos, y el "
          "editor sigue trabajando con el archivo original")
    return True


def main() -> int:
    pruebas = [
        ("minificado conserva estructura", test_minificado_conserva_estructura),
        ("atributos sin comillas no se tragan", test_atributos_sin_comillas_no_se_tragan),
        ("el javascript cuadra", test_el_javascript_cuadra),
        ("etiqueta sin comilla de cierre",
         test_ningun_literal_cierra_una_etiqueta_sin_comilla),
        ("el círculo se puede quitar", test_el_circulo_se_puede_quitar),
        ("los modelos se guardan y se estampan", test_los_modelos_se_guardan_y_se_estamplan),
        ("los ajustes del icono propio viajan", test_los_ajustes_del_icono_propio_viajan),
        ("los svg se limpian y no se pixelan", test_los_svg_se_limpian_y_no_se_pixelan),
        ("croquis con zonas coherentes", test_croquis_zonas_coherentes),
        ("iconos y simbolos coinciden", test_iconos_y_simbolos_coinciden),
        ("animaciones e intensidad", test_animaciones_e_intensidad),
        ("el toque y el encabezado", test_el_toque_y_el_encabezado),
        ("el sello y el boton de la ventana", test_el_sello_y_el_boton_de_la_ventana),
        ("las animaciones se paran cuando no se ven",
         test_las_animaciones_se_paran_cuando_no_se_ven),
        ("los adornos de las zonas", test_los_adornos_de_las_zonas),
        ("las pestanas del editor", test_las_pestanas_del_editor),
        ("quitar vertices de una zona", test_quitar_vertices_de_una_zona),
        ("la ventana solo con el zoom", test_la_ventana_solo_se_abre_con_el_mapa_acercado),
        ("los recursos y el boton del mapa", test_los_recursos_y_el_boton_del_mapa),
        ("los vectores se publican como pesen menos",
         test_los_vectores_se_publican_como_pesen_menos),
        ("el editor avisa si quedo viejo", test_el_editor_avisa_si_quedo_viejo),
        ("el croquis publicado no edita nada", test_el_croquis_publicado_no_edita_nada),
        ("el editor rechaza lo ajeno", test_el_editor_rechaza_lo_ajeno),
        ("alfabeto y round-trip", test_alfabeto_y_viaje),
        ("modo enlace: QR = URL", test_modo_enlace_es_una_url),
        ("colores institucionales legibles", test_colores_legibles),
        ("QR actual decodificable", test_ronda_completa),
        ("escaneo desde un movil", test_escaneo_de_un_movil),
        ("URL publicada responde", test_url_publicada_responde),
        ("legibilidad por nivel", test_legibilidad_por_tamano),
        ("exceso se reporta limpio", test_exceso_se_reporta),
    ]
    fallos = 0
    for nombre, prueba in pruebas:
        try:
            ok = prueba()
        except Exception as error:  # noqa: BLE001
            print(f"[ERROR] {nombre}: {error}")
            ok = False
        print(f"[{'OK  ' if ok else 'FALL'}] {nombre}")
        fallos += not ok
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
