# -*- coding: utf-8 -*-
"""
Prepara el fondo del croquis y los banners a partir del archivo de Illustrator.

USO
---
    python preparar_mapa.py                 (usa CroquisSolo.ai y FINAL2.ai)
    python preparar_mapa.py otro.ai otro_banners.ai

Saca DOS versiones del fondo, en plantilla/:

    rectoria-chico.webp  1600 px de ancho   ~175 KB   la que se abre siempre
    rectoria.webp        3400 px de ancho   ~483 KB   la que entra al acercar

Y DOS de cada banner:

    banner-arriba-chico.webp / banner-arriba.webp
    banner-abajo-chico.webp  / banner-abajo.webp

POR QUE DOS ARCHIVOS DE ORIGEN
-----------------------------
El fondo y los banners NO salen del mismo .ai, y es a proposito.

    CroquisSolo.ai   1224 x 792    solo el mapa
    FINAL2.ai        1224 x 1224   el poster entero, con los banners

El croquis publica el fondo viejo y los banners nuevos, porque el fondo nuevo
del poster todavia no esta ajustado a los puntos donde se tocan las zonas: las
zonas de `croquis.html` se escribieron contra el arte de `CroquisSolo.ai` y con
el arte del poster algunas se desvian. Son dos archivos porque el cambio de uno
no tiene que cambiar el otro.

Los dos banners SI salen enteros del .ai del poster, que es donde estan.

LA GEOMETRIA
------------
El poster es 1224 x 1224 y son tres franjas:

    y     0 a  216   banner de arriba, con el titulo
    y   216 a 1008   el mapa
    y 1008 a 1224   banner de abajo, solo el dibujo

En el croquis el mapa se queda donde estaba, en 0 a 792, y los banners se
colocan alrededor: el de arriba en y=-216 y el de abajo en y=792. Asi el mapa no
se mueve ni un pixel y ninguna zona, icono o coordenada cambia: lo unico que
cambia es el `viewBox`, que crece a 1224 x 1224.

POR QUE DOS VERSIONES Y NO UNA
------------------------------
El fondo es el 90 % de lo que se descarga el movil, y ocupa 30 MB en memoria al
dibujarlo: 3400 x 2200 x 4 bytes. Medido: en un telefono en vertical el mapa se
ve a 375 x 242 px nada mas abrir, asi que se estaba bajando y decodificando la
imagen entera para ensenar la sexta parte de su ancho.

Con las dos versiones, el primer pintado pasa de 540 KB a unos 230 KB y de
30 MB a 7,4 MB. El detalle llega cuando alguien acerca una zona, que es
justo cuando hace falta. Quien solo mira el mapa no se baja nunca la grande.

Los banners van en dos tambien, por lo mismo, y son mas baratos que el fondo:
los dos juntos son 50 KB en la chica y 99 KB en la grande, frente a los 276 KB
que ocupan los PNG con los que se pasaron.

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
from PIL import Image

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"
ANCHO_PAGINA = 1224.0        # el ancho del mapa, el del viewBox del croquis
ALTO_MAPA = 792               # el alto del mapa; las zonas se miden en esto

# El ancho en pixeles de cada version. El chico tiene que cubrir el mapa
# entero a una pantalla normal; el grande, el mapa entero con el zoom a tope.
# Con 1600 sobra para el primero y con 3400 para el segundo en un movil de
# densidad 3; bajarlos mas se notaria al acercar, y subirlos no se ve.
VERSIONES = (("rectoria-chico.webp", 1600), ("rectoria.webp", 3400))
CALIDAD = 88

# Los banners, que salen de otro archivo. Los anchos son menores porque el
# banner nunca se acerca: se ve siempre a la vez que el mapa entero, asi que con
# 1224 y 2448 se cubre cualquier pantalla, incluida la de densidad 3.
ALTO_BANNER = 216
VERSIONES_BANNER = ((1224, "-chico"), (2448, ""))
BANNERS = (
    # (archivo,        banda del poster,  y dentro del croquis,  nombre)
    ("banner-arriba", 0, -ALTO_BANNER, "el titulo"),
    ("banner-abajo", 1224 - ALTO_BANNER, ALTO_MAPA, "solo el dibujo"),
)


def render(pagina, ancho: int, banda=None) -> Image.Image:
    """La pagina a ese ancho, en pixeles. Con `banda`, solo esa franja."""
    z = ancho / ANCHO_PAGINA
    if banda is None:
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    else:
        y0 = banda
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False,
                                clip=pymupdf.Rect(0, y0, ANCHO_PAGINA, y0 + ALTO_BANNER))
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def guarda(imagen: Image.Image, nombre: str) -> tuple:
    """Lo escribe y devuelve (nombre, ancho, alto, bytes, sha1)."""
    destino = PLANTILLA / nombre
    imagen.save(destino, "WEBP", quality=CALIDAD, method=6)
    datos = destino.read_bytes()
    return (nombre, imagen.width, imagen.height, len(datos),
            hashlib.sha1(datos).hexdigest()[:8])


def main() -> int:
    origen = RAIZ / (sys.argv[1] if len(sys.argv) > 1 else "CroquisSolo.ai")
    origen_banners = RAIZ / (sys.argv[2] if len(sys.argv) > 2
                            else "Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL2.ai")
    if not origen.is_file():
        print(f"No encuentro {origen.name}.\n")
        print("El .ai no esta en git -pesa demasiado-, asi que solo existe en")
        print("el equipo donde se dibujo. Copialo a la raiz del proyecto, o")
        print("pasale su ruta:  python preparar_mapa.py otra/ruta/mapa.ai")
        return 1
    if not origen_banners.is_file():
        print(f"No encuentro {origen_banners.name}.\n")
        print("Sin ese archivo no hay banners: es el poster entero, con los dos")
        print("banners y el mapa, y de ahi se sacan las dos franjas.")
        return 1

    doc = pymupdf.open(origen)
    pagina = doc[0]
    if abs(pagina.rect.width - ANCHO_PAGINA) > 1:
        print(f"OJO: la pagina mide {pagina.rect.width:.1f} pt y el croquis")
        print(f"     espera {ANCHO_PAGINA:.0f}. Las zonas y los iconos no van a")
        print(f"     cuadrar con el dibujo.")

    PLANTILLA.mkdir(exist_ok=True)
    print(f"{origen.name}: {origen.stat().st_size // 1024} KB, "
          f"{pagina.rect.width:.0f} x {pagina.rect.height:.0f} pt  (el mapa)\n")

    salidas = []
    for nombre, ancho in VERSIONES:
        imagen = render(pagina, ancho)
        salidas.append(guarda(imagen, nombre))
        mb = imagen.width * imagen.height * 4 / 1e6
        print(f"  {nombre:<24} {imagen.width}x{imagen.height} px  "
              f"{salidas[-1][3] // 1024:>4} KB  {mb:>4.1f} MB en memoria")

    # --- Los banners, del otro archivo -------------------------------------
    doc_b = pymupdf.open(origen_banners)
    pagina_b = doc_b[0]
    alto_esperado = ALTO_MAPA + 2 * ALTO_BANNER
    print(f"\n{origen_banners.name}: {origen_banners.stat().st_size // 1024} KB, "
          f"{pagina_b.rect.width:.0f} x {pagina_b.rect.height:.0f} pt  (el poster)")
    if (abs(pagina_b.rect.width - ANCHO_PAGINA) > 1
            or abs(pagina_b.rect.height - alto_esperado) > 1):
        print(f"OJO: el poster deberia medir {ANCHO_PAGINA:.0f} x "
              f"{alto_esperado:.0f} pt y mide {pagina_b.rect.width:.0f} x "
              f"{pagina_b.rect.height:.0f}.\n"
              f"     Las franjas se sacan por la ALTURA, asi que si ha cambiado "
              f"los banners\n"
              f"     pueden no salir de donde deben. Mira las imagenes antes de "
              f"subirlas.")
    print()
    for nombre, y_poster, y_croquis, que in BANNERS:
        for ancho, sufijo in VERSIONES_BANNER:
            imagen = render(pagina_b, ancho, banda=y_poster)
            salidas.append(guarda(imagen, nombre + sufijo + ".webp"))
        ficheros = [s for s in salidas if s[0].startswith(nombre)]
        tam = " + ".join(f"{s[3] // 1024} KB" for s in ficheros)
        print(f"  {nombre} ({que}): y {y_poster:g} del poster, "
              f"y {y_croquis:g} del croquis   {tam}")
    doc_b.close()
    doc.close()

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, _, sha in salidas:
        print(f'  {nombre}?v={sha}')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
