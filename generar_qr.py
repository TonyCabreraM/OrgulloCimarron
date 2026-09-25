"""
Orgullo Cimarron - generador de QR con HTML embebido.

Un QR puede apuntar a una URL con fragmento (#). Esa parte NUNCA viaja al
servidor, asi que podemos codificar un documento HTML completo dentro del
propio codigo. Al escanearlo, el movil hace un GET normal a la URL base y el
navegador abre el documento del fragmento: sin servidor, sin archivos extra,
con CSS, JS, animaciones y transiciones.

Pipeline:  plantilla legible -> minificado -> fragmento -> QR (PNG + SVG)
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

import qrcode
import qrcode.image.svg
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M

# URL a la que apunta el QR. Despues del '#' viaja el HTML.
# Debe ser una URL real y accesible (GitHub Pages, Netlify Drop, etc).
# Cada caracter cuenta: una URL larga se come el espacio del documento.
URL_BASE = "https://x.to/a"

# Capacidad maxima aproximada de datos (version 40) segun nivel de correccion.
CAPACIDAD = {
    "L": 2953,
    "M": 2331,
    "H": 1273,
}

PESO = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_PLACEHOLDER = re.compile(r"\x00POZA(\d+)\x00")


# --------------------------------------------------------------------------- #
# Minificado
# --------------------------------------------------------------------------- #
def minificar(html: str) -> str:
    """Reduce el HTML a lo minimo sin romper el render."""
    huecos = []

    def guardar(m: re.Match[str]) -> str:
        huecos.append(m.group(0))
        return f"\x00POZA{len(huecos) - 1}\x00"

    # 1. Protege bloques donde el whitespace es significante.
    html = re.sub(
        r"<(script|style|pre|textarea)\b[^>]*>.*?</\1\s*>",
        guardar,
        html,
        flags=re.S | re.I,
    )

    # 2. Comentarios de bloque.
    html = re.sub(r"<!--(?!\[if).*?-->", "", html, flags=re.S)

    # 3. Espacios sobrantes entre etiquetas y dentro de las etiquetas.
    html = re.sub(r"\s+", " ", html)
    html = re.sub(r"\s*(/?>)\s*<", r"\1<", html)
    html = re.sub(r"\s+>", ">", html)
    html = re.sub(r"<\s*(html|head|body)\b", r"<\1", html, flags=re.I)
    html = html.replace("application/xhtml+xml", "text/html")

    # 4. Comillas solo en atributos con valor simple (lang, type, id...).
    #    Nunca en content:"" ni en manejadores como onclick="f('a','b')".
    html = re.sub(r"([a-zA-Z-]+)=([\"'])([\w.-]+)\2", r"\1=\3", html)

    # 5. Compacta los bloques protegidos, conservando sus etiquetas de apertura/cierre.
    for indice, bloque in enumerate(huecos):
        apertura = re.match(r"<\s*\w+[^>]*>", bloque)
        cierre = re.search(r"</\s*\w+\s*>\s*$", bloque)
        etiqueta = re.match(r"<\s*(\w+)", bloque).group(1).lower()
        interno = bloque[apertura.end() : bloque.rfind(cierre.group(0))]
        if etiqueta == "style":
            interno = re.sub(r"\s*([{}:;,>])\s*", r"\1", interno)
            interno = re.sub(r";\}", "}", interno)
        elif etiqueta == "script":
            interno = re.sub(r"^\s*//.*$", "", interno, flags=re.M)
        interno = interno.strip()
        compacto = apertura.group(0) + interno + cierre.group(0)
        html = html.replace(f"\x00POZA{indice}\x00", compacto)

    return html.strip()


def limpiar_html(html: str) -> str:
    """Codifica el HTML en base64url sin padding, usando la tabla URL-safe del QR."""
    crudo = html.encode("utf-8")
    base = base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("=")
    return "".join(c for c in base if c in PESO)


def peso_decodificado(fragmento: str) -> int:
    """Bytes que ocupa realmente el fragmento dentro de la capacidad del QR."""
    return len(fragmento.encode("ascii")) * 3 // 4


# --------------------------------------------------------------------------- #
# Chequeos
# --------------------------------------------------------------------------- #
def revisar_autonomo(html: str) -> list[str]:
    """Detecta referencias a archivos que no van a viajar con el HTML."""
    problemas = []
    for patron, motivo in (
        (r"<link[^>]+href=[\"'](?!https?:)[\w./-]+", "hoja de estilos externa"),
        (r"<script[^>]+src=", "script externo"),
        (r"<img[^>]+src=[\"'](?!https?:|data:)[\w./-]+", "imagen local"),
        (r"url\((?!['\"]?https?:|['\"]?data:)[\w./-]+\)", "fondo local"),
    ):
        if re.search(patron, html, flags=re.I):
            problemas.append(motivo)
    return problemas


# --------------------------------------------------------------------------- #
# Generacion
# --------------------------------------------------------------------------- #
def construir_qr(datos: str, ruta_png: Path, ruta_svg: Path, nivel: str) -> None:
    correccion = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "H": ERROR_CORRECT_H}[nivel]
    qr = qrcode.QRCode(
        error_correction=correccion,
        box_size=10,
        border=4,
    )
    try:
        qr.add_data(datos)
        qr.make(fit=True)
    except (ValueError, qrcode.exceptions.DataOverflowError):
        siguiente = "L" if nivel in ("M", "H") else None
        extra = f" Prueba con --nivel {siguiente}." if siguiente else " Ya no queda margen: reduce el documento."
        raise SystemExit(
            f"El HTML no cabe en un QR nivel {nivel} (los datos miden {len(datos)} bytes).{extra}"
        )

    qr.make_image().save(ruta_png)
    qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(ruta_svg)


def main() -> int:
    analizador = argparse.ArgumentParser(
        description="Genera un QR que abre un HTML animado sin servidor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Ejemplos:
  python generar_qr.py
  python generar_qr.py --html plantilla/plantilla.html --salida salida/orgullo
  python generar_qr.py --nivel L --url-base https://ejemplo.com/mi-pagina
""",
    )
    analizador.add_argument("--html", default="plantilla/plantilla.html", help="HTML fuente legible")
    analizador.add_argument("--salida", default="salida/orgullo", help="prefijo de salida (sin extension)")
    analizador.add_argument("--url-base", default=URL_BASE, help="URL a la que apunta el QR")
    analizador.add_argument("--nivel", choices=list(CAPACIDAD), default="M", help="correccion de errores: M=2331 bytes, L=2953, H=1273")
    analizador.add_argument("--no-minificar", action="store_true", help="conservar el HTML tal cual")
    args = analizador.parse_args()

    origen = Path(args.html)
    if not origen.is_file():
        raise SystemExit(f"No encontre el HTML fuente: {origen}")

    crudo = origen.read_text(encoding="utf-8")
    if "<html" not in crudo.lower() and "<!doctype" not in crudo.lower():
        crudo = f"<!doctype html>{crudo}"

    if args.no_minificar:
        html = crudo
        fragmento = html
    else:
        html = minificar(crudo)
        fragmento = limpiar_html(html)

    problemas = revisar_autonomo(crudo)
    if problemas:
        print("Aviso: el HTML referencia recursos externos que NO viajan en el QR:")
        for problema in problemas:
            print(f"  - {problema}")

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    # --url-base es la URL completa del documento; el fragmento se le anade.
    base = args.url_base
    separador = "" if "#" in base else "#"
    url = f"{base}{separador}{fragmento}"

    # El peso real incluye la URL base: tambien ocupa celdas del QR.
    total = len(url.encode("utf-8"))
    capacidad = CAPACIDAD[args.nivel]
    porcentaje = total / capacidad * 100

    print(f"HTML fuente      : {origen}")
    print(f"HTML minificado  : {len(html.encode('utf-8'))} bytes")
    print(f"Fragmento        : {len(fragmento)} chars en base64url")
    print(f"URL completa     : {total} bytes ({porcentaje:.1f}% de {capacidad} con nivel {args.nivel})")
    if porcentaje > 100:
        siguiente = "L" if args.nivel != "L" else None
        print(f"ERROR: no cabe. Reduce el documento o acorta --url-base"
              + (f", o usa --nivel {siguiente}." if siguiente else "."))
        return 1
    if porcentaje > 95:
        print(f"Aviso: vas justo de espacio ({porcentaje:.0f}%). Recorta texto o acorta la URL antes de publicar.")
    elif porcentaje > 85:
        print(f"Aviso: queda poco margen ({porcentaje:.0f}%).")

    # A partir de aqui si se escriben archivos.
    html_path = salida.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML autonomo    -> {html_path}")

    construir_qr(url, salida.with_suffix(".png"), salida.with_suffix(".svg"), args.nivel)
    print(f"QR (PNG)        -> {salida.with_suffix('.png')}")
    print(f"QR (SVG)        -> {salida.with_suffix('.svg')}")
    print(f"Destino del QR  : {base}")
    print()
    print("Abre el QR con un lector: el HTML viaja en el fragmento (#), no se descarga.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
