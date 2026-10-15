# -*- coding: utf-8 -*-
"""
Deja el poster del croquis en condiciones de ir en un movil.

USO
---
    python optimizar_fondo.py
    python optimizar_fondo.py otra/ruta/poster.svg

Escribe `plantilla/FinalSinCosas.svg`, que es el fondo del croquis: el poster
entero, con el mapa y los dos banners, en un solo archivo. Lo dibuja el
navegador, asi que para publicarlo no hace falta ningun renderizador. Para
GENERARLO si hace falta Chromium, y solo para comprobar que el dibujo no ha
cambiado: sin el, el script dice que no comprueba y sigue.

QUE HACE, Y POR QUE
-------------------
El SVG que sale de VectorCraft pesa 6 438 KB. En el navegador son 2 948 KB con
gzip, y de ahi el movil tarda: antes de ver el mapa hay que bajar casi 3 MB,
analizar 6 de XML con unos diez mil trazos, y decodificar dos PNG incrustados,
uno de ellos de 3400 x 721, que en memoria son 9,8 MB.

De esos 2 948 KB, casi todo son dos cosas que no necesitan ir en vector:

    el patron de la hierba   1 327 KB   9 417 trazos en un mosaico de 153 x 141
    los dos PNG del interior 1 431 KB   el banner de arriba y el de abajo

LAS DOS COSAS
-------------
1. **La hierba, rasterizada.** El mosaico del cesped son nueve mil trazos, y el
   navegador tiene que recorrerlos todos cada vez que rasteriza el mapa a una
   escala nueva, que es cada vez que se amplia una zona. Es un gasto que se
   repite y casi no se ve: en la pantalla es una textura de unos pixeles.

   Se rasteriza una vez a `ZOOM` pixeles por pixel del poster y se deja como un
   `<image>` DENTRO del mismo `<pattern>`, con la misma cabecera y el mismo
   `patternTransform`. Por eso el mosaico sale en el mismo sitio que antes, con
   la misma vuelta y las mismas costuras, y lo unico que cambia es que ya no hay
   nueve mil trazos que recorrer.

2. **Los banners, en WebP.** Van incrustados como PNG en base64 dentro del
   archivo. El de abajo es de 3400 x 721, que para lo que se ve -216 px de alto-
   es tres veces mas de lo necesario. En WebP caben en 384 KB los dos, y a esta
   altura la diferencia no se ve.

LO QUE NO SE TOCA
-----------------
Ni el dibujo, ni los colores, ni el tamano del poster, ni donde cae cada cosa.
Y eso no se supone: al final el script dibuja el poster de entrada y el de
salida con Chromium, los compara, y si la diferencia se pasa de lo que cabe en
`MAXIMA` dice que no y deja el archivo como estaba.

El `?v=` del croquis es el sha1 del archivo, y lo imprime esto al final. Como
siempre, no se escribe a mano: un numero que se queda viejo no da ningun error,
solo un mapa que no cambia.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import re
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageStat

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"
ORIGEN = RAIZ / "FinalSinCosas.svg"
DESTINO = PLANTILLA / "FinalSinCosas.svg"

# Pixeles del mosaico por pixel del poster. Con 3, el cesped se ve igual hasta
# tres veces ampliado, que es lo que pide un movil de 3x con el mapa entero. A
# partir de ahi se nota que es una textura, que es exactamente lo que es.
ZOOM = 3

# Calidad de los dos WebP. 90 es donde la diferencia con el PNG original no se ve
# en un banner que se mira de lejos.
CALIDAD = 90

# Cuanto puede cambiar un pixel entre el poster de entrada y el de salida, antes
# de darlo por bueno. El cesped se remuestrea y los banners se recomprimen, asi
# que un par de niveles es lo normal; mas de esto es que algo se movio de sitio.
MAXIMA = 6

# El ancho al que se dibuja para comparar. 1224 es el del poster, que es donde
# lo veria el ojo en la pantalla.
COMPARACION = 1224


def avisa(mensaje: str) -> int:
    print(f"\n{mensaje}\n")
    return 1


def dibuja(svg: str, ancho: int = COMPARACION) -> Image.Image | None:
    """El poster, pintado por Chromium. None si no hay con que.

    Es lo mismo que hace el navegador con el `<image>` del croquis, que es
    justamente de donde sale la medida: si aqui se ve igual, alla tambien.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    pagina = ("<!doctype html><meta charset='utf-8'>"
              "<style>html,body{margin:0;background:#fff}svg{display:block;"
              f"width:{ancho}px;height:{ancho}px}}</style>" + svg.split("?>", 1)[-1])
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            try:
                hoja = navegador.new_page(viewport={"width": ancho, "height": ancho})
                hoja.set_content(pagina, wait_until="load")
                # Y hay que INSISTIR, porque con un poster de varios MB el analisis
                # del XML y la decodificacion de las imagenes incrustadas tardan: una
                # captura hecha antes sale a medio pintar, y compararla con la otra
                # da un `diferencia maxima` de 231 niveles que no es un cambio de
                # dibujo sino un retrato a destiempo.
                #
                # Se espera a que DOS capturas seguidas sean iguales, que es la
                # senal de que ya no esta pintando nada, en vez de esperar un
                # tiempo fijo: el tiempo que tarda depende de la maquina.
                anterior = None
                for _ in range(40):
                    hoja.wait_for_timeout(250)
                    foto = hoja.screenshot(clip={"x": 0, "y": 0,
                                                "width": ancho, "height": ancho})
                    if anterior is not None and foto == anterior:
                        return Image.open(io.BytesIO(foto)).convert("RGB")
                    anterior = foto
            finally:
                navegador.close()
    except Exception:
        return None
    return None


def cabecera_patron(patron: str) -> str:
    """El `<pattern ...>` tal cual, con sus unidades y su transformada."""
    return patron[:patron.index(">") + 1]


def escala_patron(patron: str) -> float:
    """Cuanto se achica el mosaico al entrar en el poster."""
    return abs(float(re.search(r'patternTransform="matrix\(([-\d.]+)', patron).group(1)))


def rasteriza_mosaico(patron: str, reglas: dict) -> str:
    """El cesped, como un WebP dentro del mismo `<pattern>`.

    PyMuPDF no dibuja el SVG entero -no lee el estilo ni los patrones-, pero
    dibujando SOLO el mosaico, con los rellenos escritos a mano, si: son
    trazados sueltos sobre un fondo liso.
    """
    ancho = float(re.search(r'width="([\d.]+)"', patron).group(1))
    alto = float(re.search(r'height="([\d.]+)"', patron).group(1))
    escala = escala_patron(patron)

    cuerpo = patron[patron.index("<g "):patron.rindex("</g>") + 4]
    n = 0

    def pega(m):
        nonlocal n
        n += 1
        return f'<path{atributos(reglas.get(m.group(2), ""))} d="{m.group(1)}"/>'

    sustituir = re.sub(r'<path d="([^"]+)" class="(cls-\d+)"/>', pega, cuerpo)

    # El mosaico sale a `escala` dentro del poster, asi que para tener ZOOM
    # pixeles por pixel del poster hay que pedir `ancho * escala * ZOOM`.
    temporal = PLANTILLA / "_mosaico.svg"
    temporal.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{round(ancho * escala * ZOOM)}" height="{round(alto * escala * ZOOM)}" '
        f'viewBox="0 0 {ancho} {alto}">{sustituir}</svg>', encoding="utf-8")
    try:
        pix = pymupdf.open(str(temporal))[0].get_pixmap(alpha=False)
    finally:
        temporal.unlink(missing_ok=True)
    imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    buffer = io.BytesIO()
    imagen.save(buffer, "WEBP", quality=CALIDAD, method=6)
    print(f"  la hierba: {n} trazos -> un mosaico de {imagen.width}x{imagen.height} px, "
          f"{len(buffer.getvalue()) // 1024} KB")
    datos = base64.b64encode(buffer.getvalue()).decode("ascii")

    # La cabecera es la del original, para que las unidades, la vuelta y el
    # desplazamiento del mosaico sean EXACTAMENTE los mismos.
    return (cabecera_patron(patron)
            + f'<image width="{ancho}" height="{alto}" preserveAspectRatio="none" '
              f'xlink:href="data:image/webp;base64,{datos}"/></pattern>')


def atributos(regla: str) -> str:
    """Una regla de clase escrita como atributos, porque PyMuPDF no lee el CSS."""
    return "".join(f' {k}="{v.strip()}"' for k, v in re.findall(r"([\w-]+):([^;]+)", regla)
                   if k != "class")


def recodifica_banners(texto: str) -> str:
    """Los dos PNG incrustados, en WebP."""
    salida = texto
    for i, png in enumerate(re.findall(r'xlink:href="data:image/png;base64,([^"]+)"', texto), 1):
        imagen = Image.open(io.BytesIO(base64.b64decode(png)))
        buffer = io.BytesIO()
        imagen.save(buffer, "WEBP", quality=CALIDAD, method=6)
        webp = base64.b64encode(buffer.getvalue()).decode("ascii")
        print(f"  banner {i}: {imagen.width}x{imagen.height} px, "
              f"{len(png) * 3 // 4 // 1024} KB en PNG -> {len(buffer.getvalue()) // 1024} KB"
              f" en WebP")
        salida = salida.replace(png, webp, 1)
    return salida


def main() -> int:
    origen = RAIZ / sys.argv[1] if len(sys.argv) > 1 else ORIGEN
    if not origen.is_file():
        return avisa(f"No encuentro {origen.name}. El poster va en la raiz del proyecto,\n"
                     f"o pasale su ruta:  python optimizar_fondo.py otra/ruta/poster.svg")
    if origen.suffix.lower() != ".svg":
        return avisa(f"{origen.name} no es un SVG: el fondo del croquis es el poster "
                     f"exportado.")

    texto = origen.read_text(encoding="utf-8")
    print(f"{origen.name}: {origen.stat().st_size / 1e6:.1f} MB, "
          f"{len(gzip.compress(texto.encode(), 9)) // 1024} KB con gzip")

    ini = texto.find('<pattern id="pattern-1"')
    if ini < 0:
        return avisa("El SVG no tiene el patron de la hierba, o ya esta rasterizado:\n"
                     "no hay nada que optimizar.")
    fin = texto.index("</pattern>", ini) + len("</pattern>")

    print("\nCambios:")
    salida = texto[:ini] + rasteriza_mosaico(texto[ini:fin],
                                              dict(re.findall(r"\.(cls-\d+)\{([^}]*)\}", texto)))
    salida = recodifica_banners(salida)

    # --- Y que no haya cambiado el dibujo -------------------------------------
    print("\nComprobando que el dibujo es el mismo...")
    antes = dibuja(texto)
    despues = dibuja(salida)
    if antes is None or despues is None:
        return avisa("No se ha podido dibujar el poster para compararlo: falta Chromium\n"
                     "(.venv\\Scripts\\python.exe -m playwright install chromium).\n"
                     "El archivo plantilla/FinalSinCosas.svg NO se ha tocado.")
    if antes.size != despues.size:
        return avisa("Los dos posters no miden lo mismo. El archivo NO se ha tocado.")
    puntos = ImageStat.Stat(ImageChops.difference(antes, despues).convert("L"))
    mayor, media = puntos.extrema[0][1], puntos.mean[0]
    print(f"  diferencia maxima {mayor} niveles, media {media:.2f}  (el limite es {MAXIMA})")
    if mayor > MAXIMA:
        return avisa(f"El dibujo ha cambiado mas de lo permitido: {mayor} niveles.\n"
                     f"El archivo NO se ha tocado.")

    DESTINO.write_text(salida, encoding="utf-8")
    datos = DESTINO.read_bytes()
    print(f"""
  plantilla/FinalSinCosas.svg  {len(datos) // 1024} KB crudos, {len(gzip.compress(datos, 9)) // 1024} KB con gzip
  el poster de origen           {origen.stat().st_size // 1024} KB crudos, {len(gzip.compress(texto.encode(), 9)) // 1024} KB con gzip

Copia este numero en plantilla/croquis.html:

    FinalSinCosas.svg?v={hashlib.sha1(datos).hexdigest()[:8]}

Y comprueba con:  .venv\\Scripts\\python.exe test_qr.py""")
    return 0


if __name__ == "__main__":
    sys.exit(main())