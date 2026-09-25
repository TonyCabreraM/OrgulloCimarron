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

# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------
# 'enlace'      El QR lleva solo la URL del HTML publicado. El documento se
#               edita y se sube a GitHub, y el QR sigue funcionando sin
#               regenerarlo. Es el modo normal y el que menos modulos usa.
# 'servidor'    El QR lleva la URL de una pagina base mas el HTML completo
#               comprimido en el fragmento. Sirve para que el QR no dependa
#               del hosting, o para hacer version inmutable.
# 'sin-servidor' El QR lleva una URL 'javascript:' con el HTML dentro. Chrome
#               en Android y Safari en iOS la bloquean, asi que NO sirve para
#               imprimir; queda solo para depurar en el escritorio.
PREFIJO = "(async()=>{"
SUFIJO = "})()"

# URL del HTML publicado. En modo 'enlace' el QR contiene exactamente esto, y
# en modo 'servidor' es la pagina base a la que se le anade el fragmento.
#
# En modo 'enlace' apunta al archivo fuente: si editas el HTML, subes el
# cambio y el QR ya abre la version nueva. No hay que regenerar nada.
URL_HTML = "https://tonycabreram.github.io/OrgulloCimarron/plantilla/croquis.html"

# Pagina base, para el modo 'servidor'. Es un unico archivo que sirve para
# todos los documentos, porque solo lee location.hash y nunca cambia.
URL_BASE = "https://tonycabreram.github.io/OrgulloCimarron/d.html"


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


def construir_ancla(fragmento: str, modo: str = "enlace") -> str:
    """Arma la cadena completa que viajara dentro del QR.

    'enlace' es solo la URL del HTML: no lleva fragmento ni JavaScript, y es
    lo que produce el QR con menos modulos. 'servidor' le anade el fragmento
    con el HTML comprimido. 'sin-servidor' lo envuelve en un 'javascript:'.
    """
    if modo == "enlace":
        return URL_HTML
    if modo == "servidor":
        return f"{URL_BASE}#{fragmento}"
    return f"javascript:{PREFIJO}{cuerpo_js(f'{fragmento!r}')}{SUFIJO}"


def extraer_fragmento(ancla: str) -> str:
    """Recupera el base64url de un ancla, sea 'javascript:' o 'URL#fragmento'.

    Es la operacion inversa de construir_ancla, y sirve para verificar que lo
    que se leyo del QR devuelve exactamente el documento original. En modo
    'enlace' no hay fragmento, asi que devuelve cadena vacia.
    """
    if "#" in ancla:
        return ancla.split("#", 1)[1]
    if not ancla.startswith("javascript:"):
        return ""
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


# --------------------------------------------------------------------------- #
# Colores institucionales (Manual de Identidad Grafica UABC 2022)
# --------------------------------------------------------------------------- #
# Un QR de color se escanea peor que uno en negro sobre blanco, y casi todo es
# culpa del contraste: el lector binariza la imagen, y si los modulos y el
# fondo se parecen, no encuentra los limites. Por eso se mide el contraste
# WCAG dos veces, en color y en gris, y se avisa cuando no llega.
#
# La identidad de la UABC es VERDE y ORO, los del escudo. El verde #00723F es
# el institucional: sale en el escudo, en el manual y en el sitio uabc.mx.
# El oro es precioso como acento pero clarisimo (2.0:1 sobre blanco), asi que
# no sirve para el QR.
PALETAS = {
    "negro": {
        "modulos": "#231F20",
        "fondo": "#FFFFFF",
        "nota": "negro tinta institucional, el mas seguro de todos",
    },
    "uabc": {
        "modulos": "#00723F",
        "fondo": "#FFFFFF",
        "nota": "verde institucional UABC, el del escudo. En gris da 8.9:1",
    },
    "verde-oscuro": {
        "modulos": "#024731",
        "fondo": "#FFFFFF",
        "nota": "verde profundo del sitio, para quien quiera mas margen aun",
    },
    "verde-claro": {
        "modulos": "#007738",
        "fondo": "#FFFFFF",
        "nota": "el verde mas usado en uabc.mx. Un poco mas claro que el del escudo",
    },
    "azul": {
        "modulos": "#204199",
        "fondo": "#FFFFFF",
        "nota": "azul institucional para documentos administrativos",
    },
}


def luminancia(hexa: str) -> float:
    """Luminancia relativa de un color, segun la formula de WCAG."""
    h = hexa.lstrip("#")
    canales = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lineal = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(uno: str, otro: str) -> float:
    """Razon de contraste entre dos colores, de 1 a 21."""
    la, lb = luminancia(uno), luminancia(otro)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def a_gris(hexa: str) -> str:
    """Convierte un color a su equivalente en gris perceptual.

    Es el test que de verdad importa: un lector de QR termina binarizando la
    imagen, asi que lo que decide si encuentra el codigo es cuantos pixeles se
    ven claros u oscuros en monocromo. El magenta puro tiene 4.25:1 en color
    pero cae a 2.6:1 en gris, y ahi es donde falla.
    """
    h = hexa.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    gris = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{gris:02x}{gris:02x}{gris:02x}"


def revisar_contraste(nombre: str) -> list[str]:
    """Avisos sobre el color elegido, vacio si todo esta bien.

    Se mide el contraste dos veces: en color y en gris. El de gris es el que
    importa, porque asi leen los lectores de verdad. Tambien se avisa si el
    color es muy saturado, que es justo lo que al perder el color destroys el
    contraste en gris.
    """
    paleta = PALETAS[nombre]
    avisos = []
    modulos, fondo = paleta["modulos"], paleta["fondo"]
    razon = contraste(modulos, fondo)
    gris = contraste(a_gris(modulos), a_gris(fondo))

    print(f"Color            : {nombre}  ({modulos} sobre {fondo})")
    print(f"Contraste        : {razon:.2f}:1 en color, {gris:.2f}:1 en gris")
    print(f"                   {paleta['nota']}")

    if gris < 4.5:
        avisos.append(
            f"en gris solo da {gris:.2f}:1, por debajo del 4.5 recomendado: "
            f"puede fallar impreso en papel sucio o con sol. Usa un color mas "
            f"oscuro (--color uabc-oscuro, azul o negro)"
        )
    elif gris < 7:
        avisos.append(
            f"en gris da {gris:.2f}:1: cumple AA pero no AAA. Para un cartel "
            f"expuesto al sol conviene subir el nivel de correccion a H"
        )

    # Un canal bajo con los otros altos significa color muy saturado: al pasar
    # a gris los canales se igualan y se pierde la separacion. El negro
    # institucional tambien tiene canal bajo, pero es gris neutro (sus tres
    # canales casi iguales), asi que se mira la diferencia, no el minimo.
    h = modulos.lstrip("#")
    canales = [int(h[i : i + 2], 16) for i in (0, 2, 4)]
    if max(canales) - min(canales) > 120:
        avisos.append(
            f"color muy saturado ({canales[0]},{canales[1]},{canales[2]}): al "
            f"quedarse en gris pierde contraste, y asi es como leen la mayoria "
            f"de los lectores de movil"
        )
    return avisos


def construir_qr(
    datos: str, ruta_png: Path, ruta_svg: Path, nivel: str, color: str = "negro"
) -> None:
    correccion = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "H": ERROR_CORRECT_H}[nivel]
    paleta = PALETAS[color]
    fondo_oscuro = luminancia(paleta["fondo"]) < 0.5
    # Con fondo oscuro hay que poner claros los modulos sobre el fondo oscuro,
    # y no al reves, que es lo que haria la libreria por defecto.
    modulos = paleta["fondo"] if fondo_oscuro else paleta["modulos"]
    fondo = paleta["modulos"] if fondo_oscuro else paleta["fondo"]

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

    imagen = qr.make_image(back_color=fondo, fill_color=modulos)
    imagen.save(ruta_png)
    qr.make_image(
        image_factory=qrcode.image.svg.SvgPathImage, back_color=fondo, fill_color=modulos
    ).save(ruta_svg)


def pagina_decodificadora(expresion: str, pie: str) -> str:
    """Pagina que reconstruye el documento a partir del fragmento de la URL.

    Esta pagina NO viaja dentro del QR: es la que se publica en la URL base.
    Por eso puede ser legible y lavish: lo unico que tiene que caber en los
    2953 bytes del QR es el fragmento, no esto.

    `expresion` es de donde sale el base64url: la cadena literal (vista previa
    del modo sin-servidor) o `location.hash.slice(1)` (la pagina base, que lee
    lo que el lector de QR metio tras el '#').

    Los errores se muestran en pantalla: si alguien abre la pagina base sin
    fragmento, o con uno corrupto, veria un error de JavaScript incomprensible.
    """
    return f"""<!doctype html>
<html lang=es>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Cargando…</title>
<style>
/* overflow:hidden en html/body: el iframe va fijo y el padding del body
  <haria desbordar y aparecer un scrollbar que no toca el documento. */
html,body{{height:100%;margin:0;overflow:hidden}}
body{{display:grid;place-content:center;background:#0e151b;color:#e8f1f8;
font:15px/1.5 system-ui,sans-serif}}
#f{{display:none;padding:24px;text-align:center;max-width:38em}}
p{{margin:.4em 0}}
small{{opacity:.6;display:block;margin-top:14px;font-size:12px}}
</style>
<div id=f><p><b>No se pudo mostrar el contenido.</b></p>
<p id=e></p><small>{pie}</small></div>
<iframe id=v title="Contenido" style="position:fixed;inset:0;width:100%;height:100%;border:0;display:none"></iframe>
<script>
(async()=>{{
 // `expresion` da el base64url: location.hash.slice(1) en la pagina base, o
 // una cadena literal en la vista previa del modo sin-servidor.
 const fuente=()=>{expresion};
 const mostrar=async()=>{{
  try{{
   if(typeof DecompressionStream!=="function")
    throw new Error("Este navegador es muy antiguo. Actualiza a Chrome, Safari 16.4+ o Firefox 113+.");
   // atob solo entiende base64 estandar; el fragmento va en base64url.
   const s=(fuente()||"").replace(/-/g,'+').replace(/_/g,'/');
   if(!s)throw new Error("La direccion no trae el codigo. Escanea el codigo QR completo.");
   const a=Uint8Array.from(atob(s),c=>c.charCodeAt(0));
   const b=new Blob([a]).stream().pipeThrough(new DecompressionStream('gzip'));
   // Se mete en un iframe y no con document.write: asi esta pagina no se
   // destruye, el aviso de error sigue vivo y un segundo escaneo con la
   // pagina ya abierta vuelve a cargar bien.
   const v=document.getElementById("v");
   v.style.display="block";
   document.getElementById("f").style.display="none";
   v.srcdoc=await new Response(b).text();
  }}catch(e){{
   const f=document.getElementById("f"),m=document.getElementById("e");
   f.style.display="block";m.textContent=String(e&&e.message||e);
   document.getElementById("v").style.display="none";
  }}
 }};
 mostrar();
 // Cambiar solo el '#' NO recarga el documento. Sin esto, si la pagina ya
 // esta abierta y se escanea otro QR, se queda en blanco.
 addEventListener("hashchange",mostrar);
}})();
</script>
"""


def vista_previa(ancla: str, modo: str) -> str:
    """Replica el decodificador para comprobar el resultado sin escanear.

    En modo servidor el fragmento viene en `location.hash`, asi que esta copia
    se abre anadiendo el fragmento del QR a mano.
    """
    if modo == "servidor":
        return pagina_decodificadora(
            "location.hash.slice(1)",
            "Copia la direccion del QR y pegala aqui, seguida de su <em>#</em> y el fragmento.",
        )
    encontrado = re.search(r"let s='([^']*)'", ancla)
    literal = f"'{encontrado.group(1)}'" if encontrado else "''"
    return pagina_decodificadora(
        literal,
        "Replica el decodificador del QR, sin escanear nada.",
    )


def main() -> int:
    analizador = argparse.ArgumentParser(
        description="Genera un QR que abre un documento HTML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python generar_qr.py --html plantilla/croquis.html --salida salida/croquis --nivel H
  python generar_qr.py --modo servidor --nivel L
  python generar_qr.py --modo sin-servidor      (solo para depurar)
""",
    )
    analizador.add_argument("--html", default="plantilla/croquis.html", help="HTML fuente legible")
    analizador.add_argument("--salida", default="salida/croquis", help="prefijo de salida (sin extension)")
    analizador.add_argument(
        "--modo",
        choices=["enlace", "servidor", "sin-servidor"],
        default="enlace",
        help="enlace (por defecto): el QR lleva solo la URL del HTML publicado, y da el "
        "QR más pequeño. servidor: además lleva el HTML dentro, por si el QR debe "
        "funcionar aunque el hosting caiga. sin-servidor: URL 'javascript:', que "
        "los móviles bloquean; solo para depurar",
    )
    analizador.add_argument(
        "--nivel",
        choices=list(CAPACIDAD),
        default="H",
        help="corrección de errores: H=1273 bytes (el más robusto, Recommended), "
        "M=2331, L=2953 (el que más cabe, pero el más frágil al imprimir)",
    )
    analizador.add_argument("--no-minificar", action="store_true", help="conservar el HTML tal cual")
    analizador.add_argument("--sin-comprimir", action="store_true", help="no aplicar gzip (QR más denso)")
    analizador.add_argument(
        "--color",
        choices=sorted(PALETAS),
        default="uabc",
        help="color del QR, de la paleta institucional de la UABC. 'uabc' es el "
        "verde del escudo, que es el institucional; 'negro' es el mas seguro de "
        "todos. El oro institucional no aparece porque es demasiado claro para "
        "un QR",
    )
    analizador.add_argument(
        "--publicar-en",
        metavar="CARPETA",
        default=".",
        help="modo servidor: dónde dejar la página base. Por defecto la raíz del repo",
    )
    args = analizador.parse_args()

    origen = Path(args.html)
    if not origen.is_file():
        raise SystemExit(f"No encontré el HTML fuente: {origen}")

    crudo = origen.read_text(encoding="utf-8")
    if "<html" not in crudo.lower() and "<!doctype" not in crudo.lower():
        crudo = f"<!doctype html>{crudo}"

    problemas = revisar_autonomo(crudo)
    if problemas:
        print("Aviso: el HTML referencia recursos externos, así que NO funcionará solo:")
        for problema in problemas:
            print(f"  - {problema}")
        if args.modo != "enlace":
            print("  (en los otros modos el archivo no viaja en el QR: no lo verían)")

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    # En modo 'enlace' el documento se sirve tal cual desde el repo, así que no
    # hace falta minificarlo ni comprimirlo: el QR solo lleva la URL.
    if args.modo == "enlace":
        ancla = construir_ancla("", "enlace")
    else:
        html = crudo if args.no_minificar else minificar(crudo)
        fragmento = limpiar_html(html, comprimir=not args.sin_comprimir)
        ancla = construir_ancla(fragmento, args.modo)

    total = len(ancla.encode("utf-8"))
    capacidad = CAPACIDAD[args.nivel]
    porcentaje = total / capacidad * 100
    version = _version_para(total, args.nivel)
    modulos = 17 + 4 * version

    print(f"Modo            : {args.modo}")
    print(f"HTML fuente     : {origen}  ({len(crudo.encode('utf-8'))} bytes)")
    if args.modo != "enlace":
        print(f"HTML minificado : {len(html.encode('utf-8'))} bytes")
        if not args.sin_comprimir:
            print(f"Comprimido (gzip): {bytes_reales(fragmento)} bytes")
        print(f"Fragmento       : {len(fragmento)} chars en base64url")
    print(f"Contenido del QR : {total} bytes ({porcentaje:.0f}% de {capacidad}, nivel {args.nivel})")
    print(f"Cuadritos        : version {version} -> {modulos}x{modulos} módulos")
    if porcentaje > 100:
        siguiente = {"M": "L", "H": "M"}.get(args.nivel)
        print("ERROR: no cabe." + (f" Prueba con --nivel {siguiente}." if siguiente else " Reduce el documento."))
        return 1
    if args.modo == "enlace":
        print("Margen          : sobra sitio de sobra, no hace falta recortar nada")
    elif porcentaje > 95:
        print("Aviso: vas justo de espacio. Recorta texto antes de publicar.")
    elif porcentaje > 85:
        print("Aviso: queda poco margen.")

    # A partir de aquí sí se escriben archivos.
    if args.modo != "enlace":
        html_path = salida.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")
        print(f"HTML minificado -> {html_path}  (copia de referencia)")

    construir_qr(ancla, salida.with_suffix(".png"), salida.with_suffix(".svg"), args.nivel, args.color)
    print(f"QR (PNG)        -> {salida.with_suffix('.png')}")
    print(f"QR (SVG)        -> {salida.with_suffix('.svg')}  (para imprenta)")

    # Avisos de color, despues de imprimir el resumen para que se vean juntos.
    for aviso in revisar_contraste(args.color):
        print(f"Aviso           : {aviso}")
    if args.color != "negro" and args.nivel != "H":
        print("Sugerencia      : con color, usa '--nivel H'. La correccion de "
              "errores es lo que absorbe el ruido de la impresion")

    if args.modo == "enlace":
        print()
        print("LISTO PARA ESCANEAR. El QR contiene solo esta dirección:")
        print(f"  {ancla}")
        print()
        print("Comprueba que abre en el móvil. Si editas el HTML y subes el cambio,")
        print("el QR ya abre la versión nueva: no hay que regenerarlo.")
    elif args.modo == "servidor":
        base = Path(args.publicar_en) / (Path(URL_BASE).name or "index.html")
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(vista_previa(ancla, args.modo), encoding="utf-8")
        print(f"Página base     -> {base}  (súbela a la raíz del repo)")
        print()
        print("LISTO PARA ESCANEAR. El QR apunta a:")
        print(f"  {URL_BASE}#{fragmento[:40]}…")
        print()
        print("1. Sube el archivo de página base a la raíz del repo.")
        print("2. Comprueba que esa página abre en el móvil.")
        print("3. Escanea el QR.")
        print()
        print("Aviso: la URL ronda los", total, "caracteres porque el fragmento")
        print("viaja dentro. Si algún lector la trunca, recorta el documento.")
    else:
        base = salida.with_name(salida.name + "_base.html")
        base.write_text(vista_previa(ancla, args.modo), encoding="utf-8")
        print(f"Vista previa    -> {base}  (abre esto para ver el resultado)")
        print()
        print("OJO: este modo usa una URL 'javascript:'. Chrome en Android y")
        print("Safari en iOS la bloquean, así que el QR NO funcionará en un")
        print("teléfono. Usa '--modo enlace' o '--modo servidor' para imprimirlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
