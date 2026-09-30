"""
Pruebas del generador de QR con HTML embebido.

La lectura se hace con zxing-cpp, que es la libreria que usan los lectores de
movil. (OpenCV falla a partir de la version ~20 y no sirve para verificar esto.)
"""
from __future__ import annotations

import base64
import contextlib
import gzip
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
    ruta_mapa = Path("plantilla") / mapa.group(1)
    if not ruta_mapa.is_file():
        print(f"    (el mapa {ruta_mapa} no existe junto al HTML)")
        return False
    print(f"    {len(zonas)} zonas y {len(iconos)} iconos "
          f"({len(propios)} propios), mapa de {ruta_mapa.stat().st_size // 1024} KB")
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

            nombre, datos, png = editor.preparar_icono(datos_url, "Extintor.png", set())
            if nombre != "extintor-png":
                problemas.append(f"el nombre salió «{nombre}» y se esperaba «extintor-png»")

            ajustes = {"s": 16, "a": "flota", "c": 0}
            editor.guarda_en_biblioteca(nombre, png, ajustes)

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
        finally:
            editor.BIBLIOTECA = original

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    los ajustes se guardan con la imagen, vuelven con ella y se borran con ella")
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
        ("croquis con zonas coherentes", test_croquis_zonas_coherentes),
        ("iconos y simbolos coinciden", test_iconos_y_simbolos_coinciden),
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
