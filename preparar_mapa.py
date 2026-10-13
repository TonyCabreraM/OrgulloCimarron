# -*- coding: utf-8 -*-
"""
Prepara el fondo y los banners del croquis a partir del archivo de Illustrator.

USO
---
    python preparar_mapa.py
    python preparar_mapa.py otra/ruta/poster.ai

Saca, en plantilla/:

    rectoria-chico.webp  1600 px de ancho   ~175 KB   la que se abre siempre
    rectoria.webp        3400 px de ancho   ~483 KB   la que entra al acercar

    banner-arriba-chico.webp  1224 px       30 KB     con el titulo
    banner-arriba.webp        2448 px       59 KB
    banner-abajo-chico.webp   1224 px       20 KB     solo el dibujo
    banner-abajo.webp         2448 px       40 KB

TODO SALE DE UN SOLO ARCHIVO
-----------------------------
El poster, «Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL2.ai», de 1224 x 1224
pt, que son tres franjas:

    y     0 a  216   banner de arriba, con el titulo
    y   216 to 1008   el mapa
    y  1008 to 1224   banner de abajo, solo el dibujo

Antes el fondo salia de CroquisSolo.ai y los banners de este, porque el fondo del
poster traia el mapa redibujado -fondo gris en vez de verde palido, filas de
puestos numerados, pictogramas nuevos- y las zonas de croquis.html se escribieron
contra el dibujo anterior. Se comprobo que el mapa del poster y el anterior estan
en el mismo sitio (correlacion 0.91) y se publico este.

EL MAPA NO ESTA EN SU SITIO, Y POR ESO SE COLOCA
-------------------------------------------------
En el poster el mapa va de y=216 a y=1008. En el croquis tiene que ir de 0 a 792,
porque las diez zonas y los cuarenta y seis iconos estan escritos ahi y no se
tienen que reubicar.

Medido, no supuesto. Correlacion normalizada entre los dos dibujos, renderizados
a tamano nativo y buscando el desplazamiento:

    arte nuevo colocado en y=-2   0.7740
    arte nuevo colocado en y=-1   0.9054   <-- aqui
    arte nuevo colocado en y= 0   0.8539
    arte nuevo colocado en y=+1   0.7100

Un pico claro en -1. Se coloca ahi, y por el borde que queda libre se rellena con
el propio fondo del dibujo, para que no se note la franja.

Un pixel a tamano nativo son 2,8 px en la version grande, asi que el desplazamiento
se aplica en la escala de cada salida y no en pixeles fijos.

POR QUE DOS VERSIONES DEL FONDO Y UNA DE LOS BANNERS
-----------------------------------------------------
El fondo es el 90 % de lo que se descarga el movil, y ocupa 30 MB en memoria al
dibujarlo: 3400 x 2200 x 4 bytes. Medido: en un telefono en vertical el mapa se
ve a 375 x 242 px nada mas abrir, asi que se estaba bajando y decodificando la
imagen entera para ensenar la sexta parte de su ancho.

Con las dos versiones, el primer pintado pasa de 540 KB a unos 230 KB y de
30 MB a 7,4 MB. El detalle llega cuando alguien acerca una zona, que es
justo cuando hace falta. Quien solo mira el mapa no se baja nunca la grande.

Los banners van en dos tambien porque son baratos -50 KB los dos en la chica
contra los 276 KB de los PNG con los que se pasaron-, pero el croquis usa solo la
chica: no cambian con el zoom, se van con el mapa entero, asi que no hay ningun
momento en que haga falta una mas grande que la que se ve a pantalla.

Las dos versiones de cada dibujo salen del MISMO sitio y con los mismos ajustes,
para que el cambio de una a otra no se note: si se generaran por separado, un
color distinto en una seria un parpadeo en medio del zoom.

POR QUE WEBP CON PERDIDA
------------------------
Es lo que menos pesa para estos dibujos, y esta medido: el arte del mapa tiene
8150 colores distintos -los bordes van rebajados-, asi que PNG-8 y WebP sin
perdida salen mucho peores (721 KB y 1437 KB). Y no se convierte a PNG para el
movil: la base64 de un PNG no se puede comprimir con gzip, mientras que el texto
de un SVG si.

El numero de `?v=` de cada archivo lo imprime esto al final, y hay que copiarlo
en plantilla/croquis.html. No se escribe a mano porque un numero que se queda
viejo no da ningun error: solo un mapa que no cambia, que es justo el fallo que
parece «no se subio».
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageStat

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"

ANCHO_PAGINA = 1224.0        # el ancho del poster y del lienzo del croquis
ALTO_MAPA = 792              # el alto del mapa; las zonas se miden en esto
ALTO_BANNER = 216            # el alto de cada banner
Y_MAPA_POSTER = 216          # donde empieza el mapa dentro del poster
Y_ABAJO_POSTER = ANCHO_PAGINA - ALTO_BANNER   # 1008

# Donde hay que colocar el mapa para que las zonas sigan encima de lo de siempre.
# El valor esta medido, con la tabla del docstring; el signo es el que dice que
# el arte del poster va UN pixel mas abajo que el anterior.
DESPLAZE_Y = -1

# El ancho en pixeles de cada version del fondo. El chico tiene que cubrir el
# mapa entero a una pantalla normal; el grande, el mapa entero con el zoom a tope.
# Con 1600 sobra para el primero y con 3400 para el segundo en un movil de
# densidad 3; bajarlos mas se notaria al acercar, y subirlos no se ve.
VERSIONES = (("rectoria-chico.webp", 1600), ("rectoria.webp", 3400))
VERSIONES_BANNER = ((1224, "-chico"), (2448, ""))
CALIDAD = 88

BANNERS = (
    # (archivo,          banda del poster,   y en el croquis,  que es)
    ("banner-arriba", 0, -ALTO_BANNER, "el titulo"),
    ("banner-abajo", Y_ABAJO_POSTER, ALTO_MAPA, "solo el dibujo"),
)


def render(pagina, ancho: int, banda: float, alto: int, desplaza: int = 0) -> Image.Image:
    """Una franja del .ai a ese ancho, colocada donde le toca.

    `desplaza` va en puntos del .ai, no en pixeles: se multiplica por la escala de
    esta salida, para que el desplazamiento sea el mismo en las dos versiones y
    no 1 px en la chica y 3 en la grande.
    """
    z = ancho / ANCHO_PAGINA
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False,
                            clip=pymupdf.Rect(0, banda, ANCHO_PAGINA, banda + alto))
    arte = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if not desplaza:
        return arte

    dx = round(desplaza * z)
    # El fondo se saca del BORDE INFERIOR del propio dibujo, que es papel liso, y
    # no de un color escrito aqui: asi el relleno del hueco es del mismo color
    # que el arte aunque el diseno cambie de fondo otro dia.
    fondo = ImageStat.Stat(
        arte.crop((0, arte.height - 2, arte.width, arte.height))).median
    lienzo = Image.new("RGB", arte.size, tuple(int(c) for c in fondo))
    lienzo.paste(arte, (0, dx))
    return lienzo


def guarda(imagen: Image.Image, nombre: str) -> tuple:
    """Lo escribe y devuelve (nombre, ancho, alto, bytes, sha1)."""
    destino = PLANTILLA / nombre
    imagen.save(destino, "WEBP", quality=CALIDAD, method=6)
    datos = destino.read_bytes()
    return (nombre, imagen.width, imagen.height, len(datos),
            hashlib.sha1(datos).hexdigest()[:8])


def main() -> int:
    origen = RAIZ / (sys.argv[1] if len(sys.argv) > 1
                     else "Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL2.ai")
    if not origen.is_file():
        print(f"No encuentro {origen.name}.\n")
        print("El .ai no esta en git -pesa demasiado-, asi que solo existe en")
        print("el equipo donde se dibujo. Copialo a la raiz del proyecto, o")
        print("pasale su ruta:  python preparar_mapa.py otra/ruta/poster.ai")
        return 1

    doc = pymupdf.open(origen)
    pagina = doc[0]
    alto_esperado = ALTO_MAPA + 2 * ALTO_BANNER
    print(f"{origen.name}: {origen.stat().st_size // 1024} KB, "
          f"{pagina.rect.width:.0f} x {pagina.rect.height:.0f} pt")
    if (abs(pagina.rect.width - ANCHO_PAGINA) > 1
            or abs(pagina.rect.height - alto_esperado) > 1):
        print(f"OJO: el poster deberia medir {ANCHO_PAGINA:.0f} x "
              f"{alto_esperado:.0f} pt y mide {pagina.rect.width:.0f} x "
              f"{pagina.rect.height:.0f}.\n"
              f"     Las tres franjas se sacan por la ALTURA y el mapa se coloca\n"
              f"     con un desplazamiento medido sobre el dibujo anterior: si el\n"
              f"     poster ha cambiado de alto, las dos cosas ya no valen.")
        print()

    PLANTILLA.mkdir(exist_ok=True)
    salidas = []

    # --- El fondo, con su desplazamiento -------------------------------------
    print()
    for nombre, ancho in VERSIONES:
        imagen = render(pagina, ancho, Y_MAPA_POSTER, ALTO_MAPA, DESPLAZE_Y)
        salidas.append(guarda(imagen, nombre))
        mb = imagen.width * imagen.height * 4 / 1e6
        print(f"  {nombre:<24} {imagen.width}x{imagen.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB  {mb:>4.1f} MB en memoria")

    # --- Los banners ---------------------------------------------------------
    print()
    for nombre, banda, y_croquis, que in BANNERS:
        for ancho, sufijo in VERSIONES_BANNER:
            imagen = render(pagina, ancho, banda, ALTO_BANNER)
            salidas.append(guarda(imagen, nombre + sufijo + ".webp"))
        tam = " + ".join(f"{s[3] // 1024} KB"
                         for s in salidas if s[0].startswith(nombre))
        print(f"  {nombre} ({que}): banda de y={banda:g} del poster, "
              f"y={y_croquis:g} del croquis   {tam}")

    doc.close()
    print(f"\n  el mapa se ha colocado en y={DESPLAZE_Y:+d} para que las zonas "
          f"sigan\n  encima de lo de siempre. De donde sale ese numero esta en "
          f"el\n  docstring de este script.")

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, _, sha in salidas:
        print(f'  {nombre}?v={sha}')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
