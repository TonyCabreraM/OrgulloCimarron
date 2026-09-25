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
    if "UABC Campus Mexicali" not in cuerpo:
        print("    (la URL responde, pero no es el documento del croquis)")
        return False
    print(f"    {URL_HTML} -> {estado}, {len(cuerpo)} bytes")
    return True


def test_croquis_zonas_coherentes() -> bool:
    """El array de zonas y el de descripciones tienen la misma longitud.

    Si no coinciden, al tocar un edificio la ficha sale undefined. Y si el
    array de zonas se define como texto con '+' y .split(), la precedencia
    hace que Z sea una cadena: Z.length da el numero de caracteres, el
    bucle dibuja un grupo por caracter y todas las coordenadas salen NaN
    (el mapa sale vacio, sin error). Las dos cosas son silenciosas, asi que
    se comprueban aqui.
    """
    texto = Path("plantilla/croquis.html").read_text(encoding="utf-8")

    # Codicioso y con un solo ']': el array termina en ']]' (cierre de la ultima
    # zona + cierre del array), y con ']]' en el patron se comeria el cierre de
    # esa ultima zona y dejaria fuera la cuenta.
    bloque_zonas = re.search(r"var Z=\[(.*)\],\s*\nD=", texto, flags=re.S)
    if not bloque_zonas:
        print("    (no se encuentra 'var Z=[[...]]' seguido de 'D=' en croquis.html)")
        return False
    interior = bloque_zonas.group(1)

    # Z tiene que ser un array literal de arrays, no una cadena con split().
    if ".split(" in interior:
        print("    (Z se parte con split(): al concatenar textos con '+' solo se "
              "aplicaria al ultimo trozo y Z volveria a ser una cadena)")
        return False

    zonas = re.findall(r"\[\s*[\"']?([\w-]+)[\"']?\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", interior)
    if not zonas:
        print("    (no se parses las zonas; se esperaba [[sigla,x,y,ancho,alto],...]")
        return False

    bloque_desc = re.search(r"D=\[(.*?)\]", texto, flags=re.S)
    if not bloque_desc:
        print("    (no se encuentra el array de descripciones D)")
        return False
    descripciones = re.findall(r"\"([^\"]*)\"", bloque_desc.group(1))

    if len(zonas) != len(descripciones):
        print(f"    (hay {len(zonas)} zonas pero {len(descripciones)} descripciones)")
        return False

    # Los accesos rapidos del panel salen de C. Si no mide lo mismo que Z, el
    # boton de esa zona sale sin nombre.
    bloque_corto = re.search(r"C=\[(.*?)\]", texto, flags=re.S)
    if not bloque_corto:
        print("    (no se encuentra el array de nombres cortos C)")
        return False
    cortos = re.findall(r"\"([^\"]*)\"", bloque_corto.group(1))
    if len(cortos) != len(zonas):
        print(f"    (hay {len(zonas)} zonas pero {len(cortos)} nombres cortos)")
        return False

    # Ninguna coordenada puede ser cero o negativa: siempre es un fallo.
    for sigla, x, y, w, alto in zonas:
        if min(int(x), int(y), int(w), int(alto)) <= 0:
            print(f"    (zona {sigla} con coordenada no positiva: {x},{y},{w},{alto})")
            return False
    print(f"    {len(zonas)} zonas coherentes: {' '.join(z[0] for z in zonas)}")
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
