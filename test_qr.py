"""
Pruebas del generador de QR con HTML embebido.

La lectura se hace con zxing-cpp, que es la libreria que usan los lectores de
movil. (OpenCV falla a partir de la version ~20 y no sirve para verificar esto.)
"""
from __future__ import annotations

import base64
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


def test_ronda_completa() -> bool:
    """HTML survives: generar -> PNG -> leer -> decodificar el fragmento."""
    ruta_png = Path("salida/orgullo.png")
    ruta_html = Path("salida/orgullo.html")
    if not ruta_png.is_file() or not ruta_html.is_file():
        print("    (falta salida/, ejecuta generar_qr.py)")
        return False

    texto = leer_qr(ruta_png)
    if not texto:
        print("    (el lector no pudo leer el QR)")
        return False
    if "#" not in texto:
        return False
    if not texto.startswith(g.URL_BASE):
        print(f"    (el QR apunta a {texto[:40]!r}, no a {g.URL_BASE!r})")
        return False

    fragmento = texto.split("#", 1)[1]
    recuperado = base64.urlsafe_b64decode(fragmento + "=" * (-len(fragmento) % 4)).decode("utf-8")
    return recuperado == ruta_html.read_text(encoding="utf-8")


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
    fragmento = g.limpiar_html(html)
    if set(fragmento) - set(g.PESO):
        return False
    recuperado = base64.urlsafe_b64decode(fragmento + "=" * (-len(fragmento) % 4)).decode("utf-8")
    return recuperado == html


def test_legibilidad_por_tamano() -> bool:
    """La version del QR crece con los datos; debe seguir siendo legible."""
    carga = "https://ejemplo.com/a.html#" + "A" * 2600
    resultados = {nivel: escanear_texto(carga, nivel, box=4) for nivel in ("L", "M")}
    for nivel, ok in resultados.items():
        print(f"    nivel {nivel}: {'legible' if ok else 'FALLA'}")
    return all(resultados.values())


def test_exceso_se_reporta() -> bool:
    """Un documento imposible debe salir con codigo de error, no con traceback."""
    grande = Path("_tmp_grande.html")
    grande.write_text("<p>" + "a" * 5000 + "</p>", encoding="utf-8")
    ruta_salida = Path("_tmp_salida")
    ruta_salida.mkdir(exist_ok=True)
    argv_original = sys.argv
    try:
        sys.argv = ["generar_qr.py", "--html", str(grande), "--salida", str(ruta_salida / "x"), "--nivel", "H"]
        codigo = g.main()
        if codigo == 0:
            return False
        # Y no debe haber dejado archivos a medias.
        return not any(ruta_salida.iterdir())
    finally:
        sys.argv = argv_original
        grande.unlink(missing_ok=True)
        shutil.rmtree(ruta_salida, ignore_errors=True)


def main() -> int:
    pruebas = [
        ("minificado conserva estructura", test_minificado_conserva_estructura),
        ("alfabeto y round-trip", test_alfabeto_y_viaje),
        ("QR actual decodificable", test_ronda_completa),
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
