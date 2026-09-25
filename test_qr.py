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
import shutil
import sys
from pathlib import Path

import qrcode
import zxingcpp
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M

import generar_qr as g

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

    Se recorren los dos modos, porque el QR no siempre lleva la misma forma.
    """
    origen = Path("plantilla/plantilla.html")
    crudo = origen.read_text(encoding="utf-8")
    salida = Path("_tmp_salida")
    salida.mkdir(exist_ok=True)
    try:
        for modo in ("sin-servidor", "servidor"):
            prefijo = salida / modo
            if ejecutar_main("--html", str(origen), "--salida", str(prefijo),
                             "--nivel", "L", "--modo", modo) != 0:
                return False
            texto = leer_qr(prefijo.with_suffix(".png"))
            if not texto:
                print(f"    (el lector no pudo leer el QR en modo {modo})")
                return False
            if modo == "servidor" and not texto.startswith(g.URL_BASE + "#"):
                print(f"    (el QR no apunta a la URL base: {texto[:40]!r})")
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
    try:
        if ejecutar_main("--html", str(origen), "--salida", str(salida / "q"),
                         "--nivel", "L", "--modo", "servidor",
                         "--url-base", "https://ejemplo.org/pagina.html") != 0:
            return False

        url = leer_qr(salida / "q.png")
        base, _, fragmento = url.partition("#")
        if not base.startswith("https://ejemplo.org/pagina.html"):
            print(f"    (el QR no apunta a la pagina base: {base!r})")
            return False
        if not fragmento:
            print("    (el QR no lleva fragmento)")
            return False
        # El fragmento jamas viaja al servidor: debe ser solo alfabeto seguro.
        if set(fragmento) - set(g.PESO):
            print("    (el fragmento tiene caracteres que rompen la URL)")
            return False

        # La pagina base es la que se publica: tiene que leer el hash y
        # reconstruir. Sin esto, escanear el QR no muestra nada.
        pagina = (salida / "q_base.html").read_text(encoding="utf-8")
        forPiece = ("location.hash.slice(1)", "DecompressionStream('gzip')", "atob")
        for pieza in forPiece:
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
    """
    relleno = base64.b64encode(os.urandom(6000)).decode("ascii")
    grande = Path("_tmp_grande.html")
    grande.write_text("<p>" + relleno + "</p>", encoding="utf-8")
    ruta_salida = Path("_tmp_salida")
    ruta_salida.mkdir(exist_ok=True)
    try:
        codigo = ejecutar_main("--html", str(grande), "--salida", str(ruta_salida / "x"), "--nivel", "H")
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
        ("alfabeto y round-trip", test_alfabeto_y_viaje),
        ("QR actual decodificable", test_ronda_completa),
        ("escaneo desde un movil", test_escaneo_de_un_movil),
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
