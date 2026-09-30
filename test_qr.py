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
    # Solo comprueba algo si hay algun icono con informacion Y sin aro, que es
    # el caso que se rompia. Con aro, el aro ya recogia el toque.
    iconos = leer_bloque(texto, "ICONOS") or []
    desprotegidos = [ic for ic in iconos if ic.get("i") and not ic.get("c")]
    if not desprotegidos:
        problemas.append(
            "(no hay ningun icono con informacion y sin aro en el croquis: la "
            "prueba no estaria comprobando el caso que se rompio)")

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
    i = texto.find("function pintaBoton(")
    if i < 0:
        problemas.append("(no se encuentra pintaBoton en el croquis)")
    else:
        cuerpo = texto[i:texto.find("\n}", i)]
        if "enlaceSeguro" not in cuerpo:
            problemas.append(
                "pintaBoton no comprueba el enlace antes de pintarlo")
        elif cuerpo.find("enlaceSeguro") > cuerpo.find("href"):
            problemas.append(
                "pintaBoton pone el `href` antes de comprobar el enlace: la "
                "comprobación no sirve de nada ahí")
        if 'rel = "noopener' not in cuerpo and "rel =" not in cuerpo:
            problemas.append(
                "el botón abre en pestaña nueva y no lleva `rel` con `noopener`: "
                "la página de destino podría manipular esta desde window.opener")
        # Se arma con createElement y no con innerHTML, para que la dirección
        # se trate como dirección y no como HTML.
        if "createElement" not in cuerpo:
            problemas.append(
                "el botón no se arma con `createElement`: con `innerHTML` habría "
                "que escapar la dirección a mano y un despiste la convertiría en "
                "una etiqueta")

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
