"""
Validacion de las zonas y los iconos del croquis.

Vive aqui, en el editor, y no en test_qr.py porque la usan dos cosas: las
pruebas y el editor. El editor no puede escribir un croquis invalido y las
pruebas no pueden dejar pasar uno. Si cada uno tuviera su copia, un dia
dirian cosas distintas y la que estuviera mas floja seria la que decidiera.

Todo se mide en el espacio de coordenadas del mapa: 1224 x 792 pt, que es el
tamano de pagina del archivo de Illustrator y el viewBox del SVG.
"""
from __future__ import annotations

ANCHO, ALTO = 1224, 792

# Los simbolos que el croquis sabe dibujar. La clave es lo que se guarda en
# cada icono; los paths SVG que los dibujan estan en croquis.html, y hay una
# prueba que comprueba que las dos listas no se separen.
SIMBOLOS = {
    "bano": "Baños",
    "primeros": "Primeros auxilios",
    "comida": "Alimentos",
    "bebida": "Bebidas",
    "escenario": "Escenario",
    "entrada": "Entrada",
    "informacion": "Información",
    "auto": "Estacionamiento",
    "agua": "Agua",
    "basura": "Basura",
    "sonido": "Audio",
    "estrella": "Punto de interés",
}

# Un icono no pegado a la orilla: si cae justo en el filo, la mitad se sale
# de la hoja y no se entiende que senala.
MARGEN_ICONO = 12

MIN_LADOS = 3  # un poligono de verdad
MIN_LADO_PT = 20  # mas chico que esto no se puede tocar con el dedo
MIN_AREA_PT = 400  # 20x20, el mismo criterio que el lado
MIN_DESC = 10  # una descripcion de menos no dice nada


def caja(puntos: list) -> list:
    """La caja [x, y, ancho, alto] que contiene al poligono.

    Es la misma cuenta que hace caja() en croquis.html. La caja no se guarda:
    se calcula, para que no se desincronice del poligono.
    """
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    x, y = min(xs), min(ys)
    return [x, y, max(xs) - x, max(ys) - y]


def area(puntos: list) -> float:
    """Area del poligono por la formula del cordon (shoelace)."""
    a = 0.0
    n = len(puntos)
    for i in range(n):
        x1, y1 = puntos[i]
        x2, y2 = puntos[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def _proyectar(puntos: list, eje: tuple) -> tuple:
    valores = [p[0] * eje[0] + p[1] * eje[1] for p in puntos]
    return min(valores), max(valores)


def _eje_separador(a: list, b: list) -> tuple | None:
    """Un eje donde las proyecciones de a y b no se tocan, o None si no hay."""
    for poli in (a, b):
        for i in range(len(poli)):
            p1, p2 = poli[i], poli[(i + 1) % len(poli)]
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            largo = (dx * dx + dy * dy) ** 0.5
            if not largo:
                continue
            eje = (-dy / largo, dx / largo)
            amin, amax = _proyectar(a, eje)
            bmin, bmax = _proyectar(b, eje)
            if amax < bmin or bmax < amin:
                return eje
    return None


def solapan(a: list, b: list) -> bool:
    """Si dos poligonos convexos se pisan, por el teorema de los ejes separadores.

    Se comparan los POLIGONOS y no sus cajas. Las bandas diagonales tienen
    cajas que se cruzan en las esquinas aunque las bandas no se toquen, asi
    que comparar cajas da medio reporte de falsos positivos.
    """
    return _eje_separador(a, b) is None


def revisar_zonas(zonas: list) -> list[str]:
    """Devuelve la lista de problemas de las zonas. Vacia es que todo bien.

    Cada zona es [nombre, nombre corto, poligono, descripcion], con el
    poligono como lista de puntos [x, y].
    """
    problemas: list[str] = []

    if not zonas:
        return ["no hay ninguna zona: el mapa se quedaria sin nada que tocar"]

    poligonos = []
    for k, z in enumerate(zonas):
        sitio = f"zona {k + 1}"
        if not isinstance(z, (list, tuple)) or len(z) != 4:
            problemas.append(f"{sitio}: tiene que ser [nombre, corto, poligono, descripcion]")
            poligonos.append(None)
            continue

        nombre, corto, poligono, desc = z
        if not isinstance(corto, str) or not corto.strip():
            problemas.append(f"{sitio}: le falta el nombre corto, que es el del boton")
        elif len(corto) > 22:
            problemas.append(f"{sitio}: el nombre corto «{corto}» no cabe en el boton")
        if not isinstance(nombre, str) or not nombre.strip():
            problemas.append(f"{sitio}: le falta el nombre largo, que es el del titulo")
        if not isinstance(desc, str) or len(desc.strip()) < MIN_DESC:
            problemas.append(f"{sitio}: la descripcion es demasiado corta (minimo {MIN_DESC})")

        puntos = None
        if not isinstance(poligono, (list, tuple)) or len(poligono) < MIN_LADOS:
            problemas.append(f"{sitio}: el poligono necesita al menos {MIN_LADOS} puntos")
        else:
            puntos = []
            for p in poligono:
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    puntos = None
                    problemas.append(f"{sitio}: cada punto es [x, y]")
                    break
                if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p):
                    puntos = None
                    problemas.append(f"{sitio}: las coordenadas tienen que ser numeros")
                    break
                puntos.append((int(round(p[0])), int(round(p[1]))))

        if puntos:
            xs = [p[0] for p in puntos]
            ys = [p[1] for p in puntos]
            if min(xs) < 0 or min(ys) < 0 or max(xs) > ANCHO or max(ys) > ALTO:
                problemas.append(
                    f"{sitio}: se sale del mapa de {ANCHO}x{ALTO} pt "
                    f"(x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)})")
            ancho, alto = max(xs) - min(xs), max(ys) - min(ys)
            if ancho < MIN_LADO_PT or alto < MIN_LADO_PT:
                problemas.append(
                    f"{sitio}: es muy pequena para tocarla ({ancho}x{alto} pt, "
                    f"minimo {MIN_LADO_PT} por lado)")
            elif area(puntos) < MIN_AREA_PT:
                problemas.append(
                    f"{sitio}: el area es muy pequena ({area(puntos):.0f} pt², "
                    f"minimo {MIN_AREA_PT})")
        poligonos.append(puntos)

    # Dos zonas no pueden solaparse: al tocar caeria la que este encima y la
    # otra quedaria inalcanzable justo ahi.
    for a in range(len(zonas)):
        for b in range(a + 1, len(zonas)):
            if poligonos[a] and poligonos[b] and solapan(poligonos[a], poligonos[b]):
                corto_a = zonas[a][1] if isinstance(zonas[a], (list, tuple)) and len(zonas[a]) > 1 else f"zona {a + 1}"
                corto_b = zonas[b][1] if isinstance(zonas[b], (list, tuple)) and len(zonas[b]) > 1 else f"zona {b + 1}"
                problemas.append(
                    f"«{corto_a}» y «{corto_b}» se solapan: una tapa a la otra")

    return problemas


def revisar_iconos(iconos: list) -> list[str]:
    """Devuelve la lista de problemas de los iconos. Vacia es que todo bien.

    Cada icono es [tipo, x, y, etiqueta]. El tipo tiene que estar en SIMBOLOS,
    porque el croquis solo sabe dibujar esos; uno desconocido saldria como un
    hueco sin nada y sin ningun error en consola.
    """
    problemas: list[str] = []
    if not isinstance(iconos, (list, tuple)):
        return ["los iconos tienen que ser una lista"]

    for k, ic in enumerate(iconos):
        sitio = f"icono {k + 1}"
        if not isinstance(ic, (list, tuple)) or len(ic) != 4:
            problemas.append(f"{sitio}: tiene que ser [tipo, x, y, etiqueta]")
            continue
        tipo, x, y, etiqueta = ic
        if tipo not in SIMBOLOS:
            problemas.append(
                f"{sitio}: «{tipo}» no es un simbolo conocido. "
                f"Los que hay: {', '.join(sorted(SIMBOLOS))}")
            continue
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            problemas.append(f"{sitio}: las coordenadas tienen que ser numeros")
            continue
        if not (MARGEN_ICONO <= x <= ANCHO - MARGEN_ICONO and
                MARGEN_ICONO <= y <= ALTO - MARGEN_ICONO):
            problemas.append(
                f"{sitio} ({SIMBOLOS[tipo]}): esta pegado al borde del mapa "
                f"({x:.0f}, {y:.0f}); el centro tiene que caer dentro")
        if not isinstance(etiqueta, str):
            problemas.append(f"{sitio}: la etiqueta tiene que ser texto")

    return problemas


def revisar(zonas: list, iconos: list) -> list[str]:
    """Todos los problemas juntos: los de las zonas y los de los iconos."""
    return revisar_zonas(zonas) + revisar_iconos(iconos)
