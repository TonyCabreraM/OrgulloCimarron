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
    if zonas is None or iconos is None:
        print("    (no se pueden leer los bloques ZONAS o ICONOS de croquis.html).")
        print("    Los marcadores /* === INICIO X === */ no se pueden borrar:")
        print("    sin ellos el editor no sabe qué trozo reescribir.")
        return False

    problemas = v.revisar(zonas, iconos)
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
    print(f"    {len(zonas)} zonas y {len(iconos)} iconos, "
          f"mapa de {ruta_mapa.stat().st_size // 1024} KB")
    return True


def test_iconos_y_simbolos_coinciden() -> bool:
    """El croquis sabe dibujar todos los tipos de icono que el editor ofrece.

    Son dos listas que tienen que decir lo mismo: la de editor/validar.py
    decide qué tipos se pueden guardar y la del croquis (el bloque SIMBOLOS)
    sabe dibujarlos. Si se separan, se puede guardar un icono que luego no se
    dibuja: sale un hueco en el mapa y ningún error en consola.
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
    print(f"    {len(formas)} símbolos dibujables, uno por cada tipo del editor")
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

            # 3. Un icono de un tipo que no existe: también se rechaza.
            peticion = urllib.request.Request(
                base + "/api/guardar",
                data=json.dumps({"zonas": [], "iconos": [["inventado", 100, 100, "Nada"]]}).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(peticion, timeout=5) as r:
                    problemas.append(f"aceptó un icono de tipo inventado ({r.status})")
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    problemas.append(f"con un tipo inventado esperaba 400 y dio {e.code}")

            # 4. Y nada de eso puede haber tocado el archivo.
            if CROQUIS.read_bytes() != antes:
                problemas.append("el croquis cambió con guardados que debían rechazarse")
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)

    for p in problemas:
        print(f"    {p}")
    if problemas:
        return False
    print("    rechaza Host ajeno, zonas solapadas y tipos inventados, sin escribir")
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
