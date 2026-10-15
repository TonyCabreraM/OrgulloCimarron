# -*- coding: utf-8 -*-
"""
Prepara el fondo y los banners del croquis a partir del póster en SVG.

USO
---
    python preparar_mapa.py
    python preparar_mapa.py otra/ruta/poster.svg

Saca, en plantilla/:

    rectoria-chico.webp  el mapa a 1224 px   la que se abre siempre
    rectoria.webp        el mapa a 3400 px   la que entra al acercar
    banner-arriba.webp   con el título
    banner-abajo.webp    solo el dibujo

DE DONDE SALE
-------------
De «FinalSinCosas.svg», que es el póster entero, 1224 x 1224, en tres franjas.

    y     0 a  216   banner de arriba, con el título
    y   216 to 1008   el mapa
    y  1008 to 1224   banner de abajo, solo el dibujo

Y «SinCosas» va en el nombre por lo que trae, que es justo lo que se necesita
para un fondo: el mapa con las calles, las tiras de puestos y las etiquetas,
pero SIN los pictogramas de los iconos. El croquis pinta encima sus propios
cuarenta y seis iconos, en esos mismos sitios, así que si el fondo los trajera
se vería cada icono dos veces. No es un detalle que se note en el archivo:
solo se nota en la pantalla.

UN NAVEGADOR, Y POR QUÉ
-----------------------
Un SVG hay que dibujarlo, y aquí no hay Inkscape ni rsvg ni ImageMagick.
PyMuPDF -que antes hacia todo el trabajo- **no sirve**: no lee el `<style>` de
clases ni los rellenos `url(#pattern)`, y el mapa sale entero en negro. Se
comprobó: dos rectángulos de prueba, uno con `fill:#4fac48` en el estilo y
otro con un patrón, y los dos salen negros.

Así que el dibujo lo hace Chromium, el de Playwright, que es el mismo motor
que pinta el croquis en el móvil. Por eso lo que sale aquí se ve igual en la
página: si el navegador acepta un `<image>` con este SVG, el fondo es ese
mismo dibujo.

Ese Chromium hay que descargarlo una vez, y son 115 MB:

    .venv\\Scripts\\python.exe -m playwright install chromium

Las pruebas (`test_qr.py`) no lo necesitan: solo leen los WebP que este
script deja escritos.

QUE NO SE MUEVA NI UN ICONO
---------------------------
Las diez zonas y los cuarenta y seis iconos están escritos a coordenadas
fijas contra el fondo anterior, así que el mapa tiene que caer donde estaba.
Y se comprobó, no se supuso: correlación normalizada del mapa de este SVG
contra el fondo viejo publicado, moviéndolo de sitio:

    dy=-2   0.6808
    dy=-1   0.7604
    dy= 0   0.8917
    dy=+1   0.9900   <-- aquí
    dy=+2   0.8954

Un pico claro en +1, y alto: 0.9900 es prácticamente el mismo dibujo. Ese +1 es
lo que dice `DESPLAZE_Y = -1`: para que el mapa de este SVG caiga donde el
anterior, hay que pegarlo un píxel más arriba.

UN PÍXEL, Y LA FRANJA QUE QUEDA
-------------------------------
Al subirlo queda libre una fila de abajo. Se rellena con el color que ya
tiene el dibujo en su última fila, no con uno escrito aquí: para que el
relleno sea del color del arte aunque el diseño cambie de fondo otro día.

El `?v=` de cada archivo lo imprime esto al final, y hay que copiarlo en
plantilla/croquis.html. No se escribe a mano porque un número que se queda
viejo no da ningún error: sólo un mapa que no cambia, que es justo el fallo
que parece «no se subió».
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageStat

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"
ORIGEN = RAIZ / "FinalSinCosas.svg"

# El póster es de 1224 de ancho y son tres franjas de 216, 792 y 216.
ANCHO = 1224.0
ALTO_MAPA = 792
ALTO_BANNER = 216
Y_MAPA = 216
Y_ABAJO = ANCHO - ALTO_BANNER          # 1008

# El mapa va un píxel arriba de donde lo pone el póster. Medido; la tabla está en
# el docstring. El signo es el que dice que en el póster el mapa está un píxel más
# abajo que en el croquis.
DESPLAZE_Y = -1

# Ancho de cada versión del fondo. El chico es el que se abre siempre.
ANCHO_CHICO = 1224
ANCHO_GRANDE = 3400
CALIDAD = 88

# El SVG va entero dentro de la página, a píxeles, y se fotografía. Se espera un
# poco a que Chromium acaba de pintar: los dos banners del póster son PNG
# incrustados en el archivo, y una captura hecha antes de que se pinten sale con
# un hueco donde debería estar el título. Sin esto no falla nunca: sale mal una
# vez de cada varias.
ESPERA_MS = 400

PAGINA = """<!doctype html><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff;overflow:hidden}}
svg{{display:block;width:{ancho}px;height:{ancho}px}}</style>
{svg}"""


def renderiza(origen: Path, ancho: int) -> Image.Image:
    """El póster entero, dibujado por Chromium a ese ancho en píxeles.

    Va dentro de una página y no suelto como archivo porque el navegador tiene
    que resolver los `xlink:href` de los PNG incrustados igual de bien en los
    dos casos, y así se resuelve siempre en las mismas condiciones que en el
    croquis: un `<image>` que apunta a un SVG.
    """
    from playwright.sync_api import Error, sync_playwright

    svg = origen.read_text(encoding="utf-8")
    svg = svg.split("?>", 1)[1] if svg.lstrip().startswith("<?xml") else svg
    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch()
        except Error as fallo:
            if "Executable doesn't exist" not in str(fallo):
                raise
            print(f"\nNo esta el Chromium de Playwright, que es el unico que sabe "
                  f"dibujar\nun SVG aqui. Es una descarga de 115 MB, una sola vez:\n")
            print("    .venv\\Scripts\\python.exe -m playwright install chromium\n")
            raise SystemExit(1)
        try:
            pagina = navegador.new_page(viewport={"width": ancho, "height": ancho})
            pagina.set_content(PAGINA.format(ancho=ancho, svg=svg), wait_until="load")
            pagina.wait_for_timeout(ESPERA_MS)
            foto = pagina.screenshot(clip={"x": 0, "y": 0, "width": ancho, "height": ancho})
        finally:
            navegador.close()
    return Image.open(io.BytesIO(foto)).convert("RGB")


def color_del_borde(imagen: Image.Image) -> tuple:
    """El color de la última fila, que es papel liso.

    Se usa para rellenar el borde que deja el desplazamiento. Sale del dibujo y
    no de aquí, para que el relleno sea del color del arte aunque el diseño
    cambie de fondo otro día.
    """
    rgb = imagen.convert("RGB")
    return tuple(int(valor) for valor in ImageStat.Stat(
        rgb.crop((0, rgb.height - 2, rgb.width, rgb.height))
    ).median)


def coloca(imagen: Image.Image, desplaza: int) -> Image.Image:
    """La franja, movida lo que le toca y con el borde libre relleno."""
    if not desplaza:
        return imagen
    lienzo = Image.new("RGB", imagen.size, color_del_borde(imagen))
    lienzo.paste(imagen, (0, desplaza))
    return lienzo


def franja(pagina: Image.Image, ancho: int, banda: float, alto: int,
           desplaza: int = 0) -> Image.Image:
    """Una franja del póster a ese ancho en píxeles, colocada donde le toca.

    `desplaza` va en puntos del póster, no en píxeles: se multiplica por la
    escala de esta salida, para que el desplazamiento sea el mismo en las dos
    versiones del fondo y no 1 px en la chica y 3 en la grande.
    """
    z = ancho / ANCHO
    arte = pagina.crop((0, round(banda * z), pagina.width, round((banda + alto) * z)))
    return coloca(arte, round(desplaza * z))


def guarda(imagen: Image.Image, nombre: str) -> tuple:
    """Lo escribe y devuelve (nombre, ancho, alto, bytes, sha1)."""
    destino = PLANTILLA / nombre
    imagen.save(destino, "WEBP", quality=CALIDAD, method=6)
    datos = destino.read_bytes()
    return (nombre, imagen.width, imagen.height, len(datos),
            hashlib.sha1(datos).hexdigest()[:8])


def main() -> int:
    origen = RAIZ / sys.argv[1] if len(sys.argv) > 1 else ORIGEN
    if not origen.is_file():
        print(f"No encuentro {origen.name}.\n")
        print("Es un SVG, y no esta en git todavia. Solo existe en el equipo")
        print("donde se dibuja. Copialo a la raiz del proyecto, o pasale su")
        print("ruta:  python preparar_mapa.py otra/ruta/poster.svg")
        return 1
    if origen.suffix.lower() != ".svg":
        print(f"{origen.name} no es un SVG.")
        print()
        print("Antes el origen era el .ai de Illustrator y lo dibujaba PyMuPDF,")
        print("que si sabe. Un SVG no: se dibuja con Chromium, que es lo que")
        print("hace falta ahora. Exporta el poster a SVG y vuelve a llamar.")
        return 1

    texto = origen.read_text(encoding="utf-8")
    vista = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', texto)
    if not vista:
        print(f"{origen.name} no dice cual es su viewBox: no se puede saber si el")
        print("poster es de 1224 x 1224, que es de donde sale donde va cada")
        print("franja. Las coordenadas de abajo estan escritas para ese tamaño.")
        return 1
    ancho_po, alto_po = float(vista.group(1)), float(vista.group(2))
    alto_esperado = ALTO_MAPA + 2 * ALTO_BANNER
    print(f"{origen.name}: {origen.stat().st_size / 1e6:.0f} MB, "
          f"{ancho_po:.0f} x {alto_po:.0f}")
    if abs(ancho_po - ANCHO) > 1 or abs(alto_po - alto_esperado) > 1:
        print(f"OJO: el poster deberia medir {ANCHO:.0f} x {alto_esperado:.0f} "
              f"y mide {ancho_po:.0f} x {alto_po:.0f}.\n"
              f"     Las tres franjas se sacan por la ALTURA y el mapa se "
              f"coloca con un\n     desplazamiento medido contra el fondo "
              f"anterior: si el poster ha cambiado de alto, las dos\n     "
              f"cosas ya no valen y los iconos quedarian donde no toca.")

    salidas = []
    posters: dict[int, Image.Image] = {}

    def poster(ancho: int) -> Image.Image:
        """El póster a ese ancho, dibujado una sola vez por ancho."""
        if ancho not in posters:
            print(f"  dibujando el poster a {ancho} px...")
            posters[ancho] = renderiza(origen, ancho)
        return posters[ancho]

    # --- El fondo, en dos versiones ------------------------------------------
    print()
    for nombre, ancho in (("rectoria-chico.webp", ANCHO_CHICO),
                          ("rectoria.webp", ANCHO_GRANDE)):
        foto = franja(poster(ancho), ancho, Y_MAPA, ALTO_MAPA, DESPLAZE_Y)
        salidas.append(guarda(foto, nombre))
        mb = foto.width * foto.height * 4 / 1e6
        print(f"  {nombre:<22} {foto.width}x{foto.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB  {mb:>4.1f} MB en memoria")

    # --- Los banners, en una sola version cada uno ---------------------------
    # Salen del poster chico, y solo del chico: los dos vienen incrustados en el
    # SVG como PNG, y el de arriba es de 1224 px. Agrandarlo no sacaría detalle,
    # solo más bytes de lo mismo.
    print()
    for nombre, y in (("banner-arriba", 0), ("banner-abajo", Y_ABAJO)):
        foto = franja(poster(ANCHO_CHICO), ANCHO_CHICO, y, ALTO_BANNER)
        salidas.append(guarda(foto, nombre + ".webp"))
        print(f"  {(nombre + '.webp'):<22} {foto.width}x{foto.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB")

    # El papel de debajo del dibujo lo pinta el croquis en un rect que se ve un
    # instante, mientras la imagen baja. Si no fuera el del arte se veria un
    # cambio de color al abrir el mapa, asi que sale de aqui y no de a mano.
    with Image.open(PLANTILLA / "rectoria-chico.webp") as fondo:
        esquina = fondo.convert("RGB").getpixel((4, 4))
    print(f"""
  El mapa se ha colocado en y={DESPLAZE_Y:+d}, medido, para que los cuarenta y
  seis iconos y las diez zonas sigan encima de lo de siempre. La tabla de donde
  sale ese numero esta en el docstring de este script.""")

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, _, sha in salidas:
        print(f'  {nombre}?v={sha}')
    print(f'\n  Y el papel del mapa, en el <rect> de la hoja: '
          f'fill="#{esquina[0]:02x}{esquina[1]:02x}{esquina[2]:02x}"')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())