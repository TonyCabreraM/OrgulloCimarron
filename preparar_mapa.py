# -*- coding: utf-8 -*-
"""
Prepara el fondo y los banners del croquis a partir del poster exportado.

USO
---
    python preparar_mapa.py
    python preparar_mapa.py otra/ruta/poster.webp

Saca, en plantilla/:

    rectoria-chico.webp  el mapa
    banner-arriba.webp   con el titulo
    banner-abajo.webp    solo el dibujo

Y, SOLO si el poster tiene mas de 1224 px de ancho, tambien:

    rectoria.webp        el mapa a 3400 px, la que entra al acercar

DE DONDE SALE
-------------
De «Logos/Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL2.webp», que es el
poster entero a 1224 x 1224 px, en tres franjas:

    y     0 a  216   banner de arriba, con el titulo
    y   216 to 1008   el mapa
    y  1008 to 1224   banner de abajo, solo el dibujo

El .ai del poster NO se usa para el fondo, y es a proposito. El .ai trae una
version del mapa con mas cosas dentro -tiras de puestos numeradas y pictogramas de
aseos, agua, primeros auxilios y parquimetro ya dibujados- y en el croquis eso se
ve MAL: el croquis pinta encima sus propios cuarenta y seis iconos, y en los
mismos sitios, con lo que cada icono salia dos veces. El .webp de Logos/ es la
misma composicion sin ese detalle, que es la que va bien.

QUE NO SE MUEVA NI UN ICONO
---------------------------
Las diez zonas y los cuarenta y seis iconos estan escritos a coordenadas fijas
contra el fondo anterior, asi que el mapa tiene que caer donde estaba. Y se
comprobo, no se supongo: correlacion normalizada entre el fondo viejo
y este, con el mapa colocado en cada posicion posible:

    dy=-2   0.8427
    dy=-1   0.9781   <-- aqui
    dy= 0   0.9222
    dy=+1   0.7707

Un pico claro en -1, y muy alto: 0.9781 es practicamente el mismo dibujo. Con el
.ai, que si traia detalle nuevo, la mejor correlacion era 0.9054.

UN PIXEL, Y LA FRANJA QUE QUEDA
-------------------------------
Al subir el mapa un pixel queda libre una fila de abajo. Se rellena con el color
que ya tiene el dibujo en su ultima fila, y no con uno escrito aqui: para que el
relleno sea del color del arte aunque el diseno cambie de fondo otro dia.

LO DE LAS DOS VERSIONES
-----------------------
El fondo era el 90 % de lo que se baja el movil y se sacaba en dos versiones
porque el origen era vectorial y se podia renderizar a 3400 px. Ese origen era el
.ai, que ya no se usa para el fondo. El poster de Logos/ es un WebP de 1224 px.

ASI QUE NO HAY VERSION EN ALTA, Y ESTO LO DICE
-----------------------------------------------
Este script no inventa una. Si el poster tiene mas de 1224 px de ancho, saca
ademas la version grande y todo sigue como antes. Si no la tiene, lo dice y solo
saca una, sin rellenar con una copia repetida: ampliar una imagen de 1224 a 3400
y guardarla como si fuera otra es gastar 400 KB para que se vea peor.

Con una sola version, el croquis apunta las dos al MISMO archivo, y el navegador
lo pide una vez. En cuanto haya un export de mas resolucion, este script lo
detecta, saca las dos, y no hay que tocar el croquis.

SI ALGUNA VEZ SE PUEDE MAS RESOLUCION
-------------------------------------
Exporta el poster a mas de 1224 px de ancho y guardalo con el mismo nombre. Las
coordenadas de las tres franjas se calculan con la escala del poster, asi que se
acomoda solo.

El numero de `?v=` de cada archivo lo imprime esto al final, y hay que copiarlo
en plantilla/croquis.html. No se escribe a mano porque un numero que se queda
viejo no da ningun error: solo un mapa que no cambia, que es justo el fallo que
parece «no se subio».
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageStat

RAIZ = Path(__file__).resolve().parent
PLANTILLA = RAIZ / "plantilla"
ORIGEN = RAIZ / "Logos" / "Mapa Dia del Orgullo Cimarron 2026 VERSION FINAL2.webp"

# El poster de referencia es de 1224 de ancho, en tres franjas de 216, 792 y 216.
ANCHO = 1224
ALTO_MAPA = 792
ALTO_BANNER = 216
Y_MAPA = 216
Y_ABAJO = ANCHO - ALTO_BANNER          # 1008

# El mapa va un pixel arriba de donde lo pone el poster. Medido; la tabla esta en
# el docstring. El signo es el que dice que en el poster el mapa esta un pixel mas
# abajo que en el croquis.
DESPLAZE_Y = -1

# Ancho de cada version del fondo. El primero es el que se abre siempre; el
# segundo solo se saca si el origen da para mas.
ANCHO_CHICO = 1224
ANCHO_GRANDE = 3400
CALIDAD = 88


def color_del_borde(imagen: Image.Image) -> tuple:
    """El color de la ultima fila, que es papel liso.

    Se usa para rellenar el borde que deja el desplazamiento. Sale del dibujo y
    no de aqui, para que el relleno sea del color del arte aunque el diseno
    cambie de fondo otro dia.

    Se pasa a RGB antes de medir porque la imagen trae alfa, y `median` devuelve
    una lista por banda: con cuatro bandas eso seria una lista de listas, que no
    es un color.
    """
    rgb = imagen.convert("RGB")
    return tuple(int(valor) for valor in ImageStat.Stat(
        rgb.crop((0, rgb.height - 2, rgb.width, rgb.height))
    ).median)


def coloca(imagen: Image.Image, desplaza: int) -> Image.Image:
    """La franja, movida lo que le toca y con el borde libre relleno."""
    if not desplaza:
        return imagen
    lienzo = Image.new("RGBA", imagen.size, color_del_borde(imagen) + (255,))
    lienzo.paste(imagen, (0, desplaza))
    return lienzo


def reescala(imagen: Image.Image, ancho: int) -> Image.Image:
    """La franja al ancho pedido, con el desplazamiento.scalado con ella.

    El desplazamiento va en pixeles del croquis, no de la imagen: multiplicado
    por la escala, para que siga siendo el mismo entre las dos versiones y no un
    pixel en la chica y tres en la grande.
    """
    if imagen.width == ancho:
        return coloca(imagen, DESPLAZE_Y)
    escala = ancho / imagen.width
    destino = imagen.resize((ancho, round(imagen.height * escala)), Image.LANCZOS)
    return coloca(destino, round(DESPLAZE_Y / imagen.width * ancho))


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
        print("Deberia ser el poster exportado, en Logos/. Se saca así:")
        print("  exportar el poster a WebP de 1224 px de ancho (o más) y")
        print("  guardarlo ahí con el nombre del poster.")
        print("\nO se le pasa la ruta:  python preparar_mapa.py otra.webp")
        return 1

    poster = Image.open(origen)
    if poster.mode != "RGBA":
        poster = poster.convert("RGBA")
    escala = poster.width / ANCHO
    print(f"{origen.name}: {origen.stat().st_size // 1024} KB, "
          f"{poster.width} x {poster.height} px")
    if abs(poster.height - poster.width) > 1:
        print(f"OJO: el poster debería ser cuadrado y mide "
              f"{poster.width} x {poster.height}. Las tres franjas se sacan "
              f"por la ALTURA\n     y el mapa se coloca con un desplazamiento "
              f"medido: si el alto cambió, las dos cosas\n     ya no valen.")

    y_mapa = round(Y_MAPA * escala)
    y_abajo = round(Y_ABAJO * escala)
    banda_mapa = poster.crop((0, y_mapa, poster.width, y_mapa + round(ALTO_MAPA * escala)))
    salidas = []
    print()

    # --- El fondo ------------------------------------------------------------
    if poster.width > ANCHO_CHICO:
        for nombre, ancho in (("rectoria-chico.webp", ANCHO_CHICO),
                              ("rectoria.webp", min(ANCHO_GRANDE, poster.width))):
            foto = reescala(banda_mapa, ancho)
            salidas.append(guarda(foto, nombre))
            mb = foto.width * foto.height * 4 / 1e6
            print(f"  {nombre:<22} {foto.width}x{foto.height} px  "
                  f"{salidas[-1][3] // 1024:>4} KB  {mb:>4.1f} MB en memoria")
    else:
        salidas.append(guarda(reescala(banda_mapa, ANCHO_CHICO), "rectoria-chico.webp"))
        print(f"  rectoria-chico.webp     {salidas[-1][1]}x{salidas[-1][2]} px  "
              f"{salidas[-1][3] // 1024:>4} KB")
        print(f"""
  AVISO: el poster es de {poster.width} px, que es justo el ancho del croquis.
  NO hay versión en alta, y no se va a fingir: repetirla a {ANCHO_GRANDE} serían
  ~400 KB para que se vea peor, no mejor.

  En croquis.html, ARTE_URL tiene que apuntar a rectoria-chico.webp y no a
  rectoria.webp: si no, se pediría un archivo que este script ya no saca. Con las
  dos en el mismo, el navegador lo pide una vez.

  Si algún día se exporta el poster a más de {ANCHO_CHICO} px de ancho, con el
  mismo nombre, esto lo detecta solo y vuelve a sacar las dos. No hay que tocar
  el croquis.""")

    # --- Los banners ---------------------------------------------------------
    print()
    for nombre, y in (("banner-arriba", 0), ("banner-abajo", y_abajo)):
        alto = round(ALTO_BANNER * escala)
        salidas.append(guarda(poster.crop((0, y, poster.width, y + alto)),
                              nombre + ".webp"))
        print(f"  {nombre + '.webp':<22} {salidas[-1][1]}x{salidas[-1][2]} px  "
              f"{salidas[-1][3] // 1024:>4} KB")

    print(f"""
  El mapa se ha colocado en y={DESPLAZE_Y:+d}, medido, para que los cuarenta y
  seis iconos y las diez zonas sigan encima de lo de siempre. La tabla de dónde
  sale ese número está en el docstring de este script.""")

    print("\nCopia estos numeros en plantilla/croquis.html:")
    for nombre, _, _, _, sha in salidas:
        print(f'  {nombre}?v={sha}')
    print("\nY comprueba con:  .venv\\Scripts\\python.exe test_qr.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
