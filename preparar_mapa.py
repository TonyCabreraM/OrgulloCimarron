# -*- coding: utf-8 -*-
"""
Prepara el fondo y los banners del croquis a partir del póster de Illustrator.

USO
---
    python preparar_mapa.py
    python preparar_mapa.py otra/ruta/poster.ai

Saca, en plantilla/:

    rectoria-chico.webp  el mapa a 1224 px   la que se abre siempre
    rectoria.webp        el mapa a 3400 px   la que entra al acercar
    banner-arriba.webp   con el título
    banner-abajo.webp    solo el dibujo

DE DONDE SALE
-------------
De «Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL3.ai», que es el póster
completo: 1224 x 1224 pt, en tres franjas.

    y     0 a  216   banner de arriba, con el título
    y   216 to 1008   el mapa
    y  1008 to 1224   banner de abajo, solo el dibujo

Un `.ai` de Illustrator es un PDF por dentro, así que se abre con PyMuPDF y se
rasteriza a la resolución que se le pida. De ahí que los cuatro archivos salgan
nítidos y no pixelados: el origen es vectorial, así que 3400 px son 3400 px
reales y no un estiramiento.

EL FINAL3 Y NO EL FINAL2
------------------------
El FINAL2, y el `.webp` que se exportó de él, NO valen para el fondo. Traen el
mapa con los pictogramas dentro -aseos, agua, primeros auxilios, parquímetro y
las tiras de puestos numeradas ya dibujados- y el croquis pinta encima sus
propios cuarenta y seis iconos, en los mismos sitios. Con lo que cada icono se
veía dos veces, y desde el archivo parece que todo está bien: sólo se nota en la
pantalla.

Se comprobó contando, no a ojo: los píxeles azules de las tiras en el mapa del
FINAL3 son 0.

LA RESOLUCION
-------------
El fondo son dos tamaños porque es el 90 % de lo que baja el móvil: la chica,
para verlo entero al abrir, y la grande, para el detalle al acercar. Los banners
son UNA sola versión porque no cambian con el zoom -se van con el mapa entero-, así
que nunca hace falta una mayor que la que está en pantalla.

QUE NO SE MUEVA NI UN ICONO
---------------------------
Las diez zonas y los cuarenta y seis iconos están escritos a coordenadas fijas
contra el fondo anterior, así que el mapa tiene que caer donde estaba. Y se
comprobó, no se supuso: correlación normalizada contra el fondo viejo publicado,
con el mapa colocado en cada posición:

    dy=-2   0.8307
    dy=-1   0.9778   <-- aquí
    dy= 0   0.9186
    dy=+1   0.7564

Un pico claro en -1, y alto: 0.9778 es prácticamente el mismo dibujo.

UN PÍXEL, Y LA FRANJA QUE QUEDA
-------------------------------
Al subir el mapa un píxel queda libre una fila de abajo. Se rellena con el color
que ya tiene el dibujo en su última fila, no con uno escrito aquí: para que el
relleno sea del color del arte aunque el diseño cambie de fondo otro día.

El desplazamiento va en puntos del `.ai` y se multiplica por la escala de cada
salida, para que sea el mismo en las dos versiones y no 1 px en la chica y 3 en
la grande.

El `?v=` de cada archivo lo imprime esto al final, y hay que copiarlo en
plantilla/croquis.html. No se escribe a mano porque un número que se queda viejo
no da ningún error: sólo un mapa que no cambia, que es justo el fallo que parece
«no se subió».
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageStat

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"
ORIGEN = RAIZ / "Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL3.ai"

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


def franja(pagina, ancho: int, banda: float, alto: int, desplaza: int = 0) -> Image.Image:
    """Una franja del póster a ese ancho en píxeles, colocada donde le toca.

    `desplaza` va en puntos del `.ai`, no en píxeles: se multiplica por la escala
    de esta salida, para que el desplazamiento sea el mismo en las dos versiones
    del fondo y no 1 px en la chica y 3 en la grande.
    """
    z = ancho / ANCHO
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False,
                            clip=pymupdf.Rect(0, banda, ANCHO, banda + alto))
    arte = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
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
        print("Es un .ai, y NO esta en git -pesa demasiado-. Solo existe en el")
        print("equipo donde se dibuja. Copialo a la raiz del proyecto, o pasale")
        print("su ruta:  python preparar_mapa.py otra/ruta/poster.ai")
        return 1

    doc = pymupdf.open(origen)
    pagina = doc[0]
    alto_esperado = ALTO_MAPA + 2 * ALTO_BANNER
    print(f"{origen.name}: {origen.stat().st_size / 1e6:.0f} MB, "
          f"{pagina.rect.width:.0f} x {pagina.rect.height:.0f} pt")
    if (abs(pagina.rect.width - ANCHO) > 1
            or abs(pagina.rect.height - alto_esperado) > 1):
        print(f"OJO: el poster deberia medir {ANCHO:.0f} x {alto_esperado:.0f} pt "
              f"y mide {pagina.rect.width:.0f} x {pagina.rect.height:.0f}.\n"
              f"     Las tres franjas se sacan por la ALTURA y el mapa se "
              f"coloca con un\n     desplazamiento medido contra el fondo "
              f"anterior: si el poster ha cambiado de alto, las dos\n"
              f"     cosas ya no valen y los iconos quedarian donde no toca.")

    salidas = []

    # --- El fondo, en dos versiones ------------------------------------------
    print()
    for nombre, ancho in (("rectoria-chico.webp", ANCHO_CHICO),
                          ("rectoria.webp", ANCHO_GRANDE)):
        foto = franja(pagina, ancho, Y_MAPA, ALTO_MAPA, DESPLAZE_Y)
        salidas.append(guarda(foto, nombre))
        mb = foto.width * foto.height * 4 / 1e6
        print(f"  {nombre:<22} {foto.width}x{foto.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB  {mb:>4.1f} MB en memoria")

    # --- Los banners, en una sola version cada uno ---------------------------
    print()
    for nombre, y in (("banner-arriba", 0), ("banner-abajo", Y_ABAJO)):
        foto = franja(pagina, ANCHO_CHICO, y, ALTO_BANNER)
        salidas.append(guarda(foto, nombre + ".webp"))
        print(f"  {(nombre + '.webp'):<22} {foto.width}x{foto.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB")

    doc.close()
    print(f"""
  El mapa se ha colocado en y={DESPLAZE_Y:+d}, medido, para que los cuarenta y seis
  iconos y las diez zonas sigan encima de lo de siempre. La tabla de dónde sale
  ese número está en el docstring de este script.

  ARTE_URL en croquis.html tiene que apuntar a rectoria.webp, la grande: ahora
  sí hay version en alta, porque el origen es vectorial.""")

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, _, sha in salidas:
        print(f'  {nombre}?v={sha}')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
