"""
Orgullo Cimarron - generador de QR que ejecuta HTML sin servidor.

La idea: el fragmento de una URL (lo que va despues del '#') NUNCA viaja al
servidor. El movil hace un GET normal a la URL y el navegador construye el
documento a partir del fragmento. Por eso el HTML completo puede codificarse
dentro del propio QR: no hay servidor, no hay que alojar nada, y al escanear
se abre la pagina con su CSS, sus animaciones y su JavaScript.

Para que quepa, el HTML se comprime con gzip (que reduce el HTML tipico a la
sexta parte) y se codifica en base64url. El navegador lo descomprime con
DecompressionStream, sin instalar nada.

Pipeline:  plantilla legible -> minificado -> gzip -> base64url -> QR
"""

from __future__ import annotations

import argparse
import base64
import gzip
import re
import sys
import zlib
from pathlib import Path

import qrcode
import qrcode.image.svg
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M

# El QR es una URL 'javascript:' que reconstruye el documento en memoria:
# atob para el base64url y DecompressionStream para el gzip. Ni una peticion
# a la red, ni un servidor. El base64url se pega con su relleno '=', que el
# navegador acepta tal cual y ocupa uno o dos modulos.
PREFIJO = "(async()=>{"
SUFIJO = "})()"

# URL de ejemplo para el modo 'servidor': cámbiala por la tuya.
URL_BASE = "https://x.to/a"


def cuerpo_js(fragmento: str) -> str:
    """Cuerpo JavaScript que descomprime el fragmento y muestra el documento.

    `fragmento` es una expresion JavaScript que produce el base64url: una
    cadena literal dentro del QR, o `location.hash` dentro de la pagina base.

    atob solo entiende el alfabeto estandar, asi que antes se convierten los
    dos caracteres propios del base64url ('-' y '_'). El relleno '=' no hace
    falta: atob repone la cuenta mientras no sea multiplo de 4 mas uno.

    Se usa igual en los tres sitios (QR, pagina base, vista previa): lo unico
    que cambia es quien lo ejecuta.
    """
    return (
        f"let s={fragmento}.replace(/-/g,'+').replace(/_/g,'/')"
        ";let a=Uint8Array.from(atob(s),c=>c.charCodeAt(0))"
        ";let f=new Blob([a]).stream().pipeThrough(new DecompressionStream('gzip'))"
        ";let t=await new Response(f).text()"
        ";document.open();document.write(t);document.close()"
    )


def construir_ancla(fragmento: str, url_base: str = URL_BASE, modo: str = "sin-servidor") -> str:
    """Arma la cadena completa que viajara dentro del QR.

    'sin-servidor' no lleva URL que resolver: el lector abre el 'javascript:' y
    la pagina se construye en memoria. 'servidor' se apoya en la URL base y
    deja el fragmento despues del '#', que el navegador nunca envia al servidor.
    """
    if modo == "servidor":
        return f"{url_base}#{fragmento}"
    return f"javascript:{PREFIJO}{cuerpo_js(f'{fragmento!r}')}{SUFIJO}"


def extraer_fragmento(ancla: str) -> str:
    """Recupera el base64url de un ancla, sea 'javascript:' o 'URL#fragmento'.

    Es la operacion inversa de construir_ancla, y sirve para verificar que lo
    que se leyo del QR devuelve exactamente el documento original.
    """
    if "#" in ancla:
        return ancla.split("#", 1)[1]
    encontrado = re.search(r"let s='([^']*)'", ancla)
    return encontrado.group(1) if encontrado else ""

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


def limpiar_html(html: str, comprimir: bool = True) -> str:
    """Comprime (opcionalmente) y codifica el HTML en base64url.

    El HTML minificado es muy repetitivo, asi que gzip lo reduce bastante.
    El base64url usa la tabla que ya necesita el QR, sin '+' ni '/', y sin
    relleno '=' porque atob lo repondrá en el decodificador.
    """
    crudo = html.encode("utf-8")
    if comprimir:
        crudo = gzip.compress(crudo, compresslevel=9, mtime=0)
    base = base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("=")
    return "".join(c for c in base if c in PESO)


def bytes_reales(fragmento: str) -> int:
    """Bytes que ocupa realmente el fragmento dentro de la capacidad del QR."""
    return (len(fragmento) * 3) // 4


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
def _version_para(bytes_datos: int, nivel: str) -> int:
    """Version del QR que le corresponde a una carga, para saber cuantos modulos tendra."""
    correccion = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "H": ERROR_CORRECT_H}[nivel]
    codigo = qrcode.QRCode(error_correction=correccion, box_size=10, border=4)
    try:
        codigo.add_data("x" * bytes_datos)
        codigo.make(fit=True)
    except (ValueError, qrcode.exceptions.DataOverflowError):
        return 41
    return codigo.version


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


def vista_previa(ancla: str, modo: str) -> str:
    """Pagina que ejecuta el mismo cuerpo JavaScript que viaja en el QR.

    Sirve para comprobar el resultado en un navegador sin escanear nada: el
    script es identico byte a byte, lo unico que cambia es que aqui corre
    desde un <script> en vez de desde la URL que codifica el QR.
    """
    if modo == "servidor":
        cuerpo = PREFIJO + cuerpo_js("location.hash.slice(1)") + SUFIJO
        pie = "Abre esta pagina con <em>#</em> y el fragmento del QR para ver el resultado."
    else:
        cuerpo = ancla[len("javascript:") :] if ancla.startswith("javascript:") else ancla
        pie = "Replica el decodificador del QR, sin escanear nada."
    return (
        "<!doctype html><meta charset=utf-8><title>Vista previa</title>"
        f"<script>{cuerpo}</script>"
        f"<p style='font:14px system-ui;padding:12px;background:#eee'>{pie}</p>"
    )


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
    analizador.add_argument(
        "--modo",
        choices=["sin-servidor", "servidor"],
        default="sin-servidor",
        help="sin-servidor: la URL no necesita existir. servidor: usa --url-base real",
    )
    analizador.add_argument(
        "--nivel",
        choices=list(CAPACIDAD),
        default="M",
        help="correccion de errores: H=1273 bytes (menos cuadritos), M=2331, L=2953",
    )
    analizador.add_argument("--no-minificar", action="store_true", help="conservar el HTML tal cual")
    analizador.add_argument("--sin-comprimir", action="store_true", help="no aplicar gzip (QR mas denso)")
    args = analizador.parse_args()

    origen = Path(args.html)
    if not origen.is_file():
        raise SystemExit(f"No encontre el HTML fuente: {origen}")

    crudo = origen.read_text(encoding="utf-8")
    if "<html" not in crudo.lower() and "<!doctype" not in crudo.lower():
        crudo = f"<!doctype html>{crudo}"

    html = crudo if args.no_minificar else minificar(crudo)
    fragmento = limpiar_html(html, comprimir=not args.sin_comprimir)

    problemas = revisar_autonomo(crudo)
    if problemas:
        print("Aviso: el HTML referencia recursos externos que NO viajan en el QR:")
        for problema in problemas:
            print(f"  - {problema}")

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    ancla = construir_ancla(fragmento, args.url_base, args.modo)
    total = len(ancla.encode("utf-8"))
    capacidad = CAPACIDAD[args.nivel]
    porcentaje = total / capacidad * 100
    version = _version_para(total, args.nivel)
    modulos = 17 + 4 * version

    print(f"HTML fuente      : {origen}")
    print(f"HTML minificado  : {len(html.encode('utf-8'))} bytes")
    if not args.sin_comprimir:
        print(f"Comprimido (gzip): {bytes_reales(fragmento)} bytes")
    print(f"Fragmento        : {len(fragmento)} chars en base64url")
    print(f"Contenido del QR : {total} bytes ({porcentaje:.0f}% de {capacidad}, nivel {args.nivel})")
    print(f"Cuadritos        : version {version} -> {modulos}x{modulos} modulos")
    if porcentaje > 100:
        siguiente = {"M": "L", "H": "M"}.get(args.nivel)
        print("ERROR: no cabe." + (f" Prueba con --nivel {siguiente}." if siguiente else " Reduce el documento."))
        return 1
    if porcentaje > 95:
        print(f"Aviso: vas justo de espacio ({porcentaje:.0f}%). Recorta texto antes de publicar.")
    elif porcentaje > 85:
        print(f"Aviso: queda poco margen ({porcentaje:.0f}%).")

    # A partir de aqui si se escriben archivos.
    html_path = salida.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML autonomo    -> {html_path}")

    construir_qr(ancla, salida.with_suffix(".png"), salida.with_suffix(".svg"), args.nivel)
    print(f"QR (PNG)        -> {salida.with_suffix('.png')}")
    print(f"QR (SVG)        -> {salida.with_suffix('.svg')}")
    print(f"Modo            : {args.modo}")

    # Vista previa: replica el decodificador del QR en un archivo local,
    # para comprobar el resultado sin tener que escanear nada.
    vista = salida.with_name(salida.name + "_qr.html")
    vista.write_text(vista_previa(ancla, args.modo), encoding="utf-8")
    print(f"Vista previa    -> {vista}  (abre esto para ver el resultado)")

    # Modo servidor: la pagina base es lo que se publica en la URL, y es la
    # que lee el fragmento para reconstruir el documento.
    if args.modo == "servidor":
        base = salida.with_name(salida.name + "_base.html")
        base.write_text(vista_previa(ancla, args.modo), encoding="utf-8")
        print(f"Pagina base     -> {base}  (publica esto en {args.url_base})")

    print()
    if args.modo == "sin-servidor":
        print("Sin servidor: la URL del QR no existe y da igual. Al escanear,")
        print("el lector ejecuta el decodificador y muestra el HTML.")
    else:
        print(f"Con servidor: publica una pagina vacia en {args.url_base}")
        print("El QR se apoya en ella para descomprimir y mostrar el HTML.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
