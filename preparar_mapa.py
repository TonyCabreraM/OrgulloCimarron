# -*- coding: utf-8 -*-
"""
Prepara el fondo del croquis a partir del archivo de Illustrator.

USO
---
    python preparar_mapa.py                 (usa CroquisSolo.ai)
    python preparar_mapa.py otro.ai

Saca DOS versiones del mismo dibujo, en plantilla/:

    rectoria-chico.webp  1600 px de ancho   ~175 KB   la que se abre siempre
    rectoria.webp        3400 px de ancho   ~483 KB   la que entra al acercar

POR QUE DOS Y NO UNA
--------------------
El fondo es el 90 % de lo que se descarga el movil, y ocupa 30 MB en memoria al
dibujarlo: 3400 x 2200 x 4 bytes. Medido: en un telefono en vertical el mapa se
ve a 375 x 242 px nada mas abrir, asi que se estaba bajando y decodificando la
imagen entera para ensenar la sexta parte de su ancho.

Con las dos versiones, el primer pintado pasa de 540 KB a unos 230 KB y de
30 MB a 7,4 MB. El detalle llega cuando alguien acerca una zona, que es
justo cuando hace falta. Quien solo mira el mapa no se baja nunca la grande.

Las dos salen del MISMO dibujo y con los mismos ajustes, para que el cambio de
una a otra no se note: si se generaran por separado, un color distinto en una
seria un parpadeo en medio del zoom.

POR QUE WEBP CON PERDIDA
------------------------
Es lo que menos pesa para este dibujo, y esta medido: el arte tiene 8150
colores distintos -los bordes van rebajados-, asi que PNG-8 y WebP sin perdida
salen mucho peores (721 KB y 1437 KB). Y no se convierte a PNG para el movil:
la base64 de un PNG no se puede comprimir con gzip, mientras que el texto de un
SVG si. Con los iconos en PNG el croquis pasaria de 55 KB a 100 KB al
descargarlo.

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
ANCHO_PAGINA = 1224.0        # el viewBox del croquis

# El ancho en pixeles de cada version. El chico tiene que cubrir el mapa
# entero a una pantalla normal; el grande, el mapa entero con el zoom a tope.
# Con 1600 sobra para el primero y con 3400 para el segundo en un movil de
# densidad 3; bajarlos mas se notaria al acercar, y subirlos no se ve.
VERSIONES = (("rectoria-chico.webp", 1600), ("rectoria.webp", 3400))
CALIDAD = 88


def render(pagina, ancho: int) -> Image.Image:
    """La pagina a ese ancho, en pixeles."""
    z = ancho / ANCHO_PAGINA
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main() -> int:
    origen = RAIZ / (sys.argv[1] if len(sys.argv) > 1 else "CroquisSolo.ai")
    if not origen.is_file():
        print(f"No encuentro {origen.name}.\n")
        print("El .ai no esta en git -pesa demasiado-, asi que solo existe en")
        print("el equipo donde se dibujo. Copialo a la raiz del proyecto, o")
        print("pasale su ruta:  python preparar_mapa.py otra/ruta/mapa.ai")
        return 1

    doc = pymupdf.open(origen)
    pagina = doc[0]
    if abs(pagina.rect.width - ANCHO_PAGINA) > 1:
        print(f"OJO: la pagina mide {pagina.rect.width:.1f} pt y el croquis")
        print(f"     espera {ANCHO_PAGINA:.0f}. Las zonas y los iconos no van a")
        print(f"     cuadrar con el dibujo.")

    PLANTILLA.mkdir(exist_ok=True)
    print(f"{origen.name}: {origen.stat().st_size // 1024} KB, "
          f"{pagina.rect.width:.0f} x {pagina.rect.height:.0f} pt\n")

    versiones = []
    for nombre, ancho in VERSIONES:
        imagen = render(pagina, ancho)
        destino = PLANTILLA / nombre
        imagen.save(destino, "WEBP", quality=CALIDAD, method=6)
        datos = destino.read_bytes()
        versiones.append((nombre, ancho, len(datos),
                          hashlib.sha1(datos).hexdigest()[:8]))
        mb = imagen.width * imagen.height * 4 / 1e6
        print(f"  {nombre:<22} {imagen.width}x{imagen.height} px  "
              f"{len(datos) // 1024:>4} KB  {mb:>4.1f} MB en memoria")

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, sha in versiones:
        print(f'  {nombre}?v={sha}')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
