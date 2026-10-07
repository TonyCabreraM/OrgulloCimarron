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

import re

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

# Lo que mide un icono, en unidades del mapa. El de por defecto es el que
# tenian todos antes de que se pudieran ajustar; el minimo se sigue leyendo
# en la vista general y el maximo no llega a tapar una zona entera.
TAM_ICONO = 46
MIN_TAM_ICONO = 16
MAX_TAM_ICONO = 160

# Los iconos propios son imagenes guardadas DENTRO del propio croquis, en
# base64. El archivo publicado no puede pedir nada de fuera (hay una prueba
# que lo vigila), asi que la imagen tiene que viajar con el. Eso significa
# que cada byte pesa dos veces: una en los datos y otra en el texto base64.
# Con 160 px de lado ninguna imagen decente pasa de 64 KB, y el tope del
# total esta para que un descuido no convierta la pagina del movil en algo
# que tarda en abrir.
MAX_ICONO = 64_000
MAX_ICONOS_PROPIOS = 800_000

# Un icono en SVG no se mide en pixeles sino en peso de texto. Y no se reduce
# como una imagen: es vector, asi que se ve igual de nitido a cualquier
# tamano. Por eso el tope es mas alto que el de un PNG: un SVG de 100 KB da
# mejor resultado que 64 KB de mapa de bits, y aun asi cabe de sobra.
MAX_VECTOR = 120_000

# Los nombres de los iconos propios van tal cual dentro del HTML, asi que se
# limitan a minusculas, numeros y guiones. Es lo mismo que hace el editor al
# preparar la imagen, y evita que un nombre raro rompa el archivo.
NOMBRE_PROPIO = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")

# Lo que mide un icono, en unidades del mapa. El de por defecto es el que
# tenian todos antes de que se pudieran ajustar; el minimo se sigue leyendo
# en la vista general y el maximo no llega a tapar una zona entera.
TAM_ICONO = 46
MIN_TAM_ICONO = 16
MAX_TAM_ICONO = 160

# La rotacion, en grados. Se admiten vueltas completas porque girar un icono
# es girarlo: -90 y 270 son lo mismo y no hay razon para rechazar ninguna.
MIN_ROT = -360
MAX_ROT = 360

# Las animaciones que el croquis sabe hacer. Se mueven cosas baratas de
# dibujar (transform y opacidad) y son suaves a proposito: esto es un mapa,
# no un anuncio, y un icono que llama demasiado la atencion molesta.
ANIMACIONES = {
    "": "Quieto",
    "late": "Late",
    "flota": "Flota",
    "gira": "Gira",
    "brilla": "Brilla",
    "ondas": "Ondas",
    "vibra": "Vibra",
    "viento": "Viento",
}

# Las que no tienen intensidad. `gira` da una vuelta completa: no hay nada que
# ampliar ni que reducir, asi que la intensidad no le hace nada y el editor no
# ofrece el control. Se dice aqui y no en el editor para que las dos partes
# lean lo mismo.
ANIMACIONES_SIN_INTENSIDAD = frozenset({"gira"})

# La intensidad del movimiento: cuanto se mueve, no a que velocidad. 1 es lo
# normal; por debajo se mueve menos y por encima mas. No se baja de 0.2 porque
# ahi ya no se ve que se mueve, y no se pasa de 2.5 porque un icono que salta
# media zona ensucia el mapa en vez de llamar la atencion.
INTENSIDAD = 1.0
MIN_INTENSIDAD = 0.2
MAX_INTENSIDAD = 2.5

# --- Los adornos de una zona ------------------------------------------------
# Una zona nace invisible: es un poligono transparente que solo existe para
# recibir el toque, para no tapar el dibujo del mapa. A partir de aqui se le
# puede dar relleno, linea y movimiento, y sigue siendo opcional: sin adornos
# se comporta como siempre.
#
# Las animaciones van en dos listas separadas porque son dos cosas distintas:
# la de la zona mueve el relleno Y la linea, y la del borde mueve SOLO la
# linea. Por eso hay nombres que estan en las dos.
ANIMACIONES_ZONA = {
    "": "Quieta",
    "late": "Late",
    "brilla": "Brilla",
    "destello": "Destello",
}

# La del borde. `camina` es la de la carretera: la linea va avanzando por todo
# el borde. Necesita guiones, asi que la pone ella misma aunque no se haya
# pedido la linea punteada.
ANIMACIONES_BORDE = {
    "": "Quieta",
    "camina": "Camina",
    "late": "Late",
    "brilla": "Brilla",
}

# Hacia donde avanza la linea de `camina`.
#
# Solo la tiene `camina`, porque es la unica que RECORRE el borde: `late` y
# `brilla` van y vienen en el sitio, asi que no hay nada que invertir.
#
# El sentido normal es aquel en el que estan escritos los puntos del poligono,
# que es lo que sale solo. El de al reves se guarda; el normal no, para que una
# zona sin tocar siga escribiendose igual que antes.
SENTIDO_NORMAL = 1
SENTIDO_REVES = -1
SENTIDOS_CAMINA = {SENTIDO_NORMAL: "Normal", SENTIDO_REVES: "Al revés"}

# Las claves de los adornos, que van en un objeto aparte dentro de la zona:
#
#   f   el color de relleno, "#rrggbb", o nada si no lleva
#   l   el color de la linea, "#rrggbb", o nada si no lleva
#   p   la linea punteada (solo tiene sentido con linea)
#   rd  cuanto se redondean las esquinas, en puntos del mapa
#   a   la animacion de la zona entera
#   b   la animacion del borde
#   d   hacia donde avanza el borde, solo con `camina`
#   m   la intensidad, la misma cuenta que en los iconos
#
# Van con nombres y no sueltos al final de la tupla de la zona a proposito: la
# tupla ya tiene cuatro campos de siempre -nombre, corto, poligono y
# descripcion- y meterle ocho mas seria volver a contar comas con la vista,
# que es justo el problema que se quito de los iconos.
CLAVES_ZONA = {"f", "l", "p", "rd", "a", "b", "d", "m"}

# El redondeo de las esquinas, en puntos del mapa.
#
# El maximo es 60 porque las zonas del mapa miden unos 300 pt de lado: con mas
# de 60 una zona pequena se quedaria como un circulo y dejaria de leerse como
# la banda que es. El minimo util es 1; por debajo, el redondeo no se ve y lo
# que se guarda es un ajuste que no hace nada.
MAX_REDONDEO = 60
MIN_REDONDEO = 1

# El patron de los guiones de la linea, en puntos.
#
# El punteado normal es corto y apretado, para que se lea como un filo
# punteado. El de `camina` es mas largo y con mas hueco, que es lo que hace que
# se lea como la linea de una carretera en movimiento.
GUIONES_PUNTEADA = "3 4"
GUIONES_CAMINA = "9 7"

# El aro: el circulo claro con filo que llevan los iconos detras. Por defecto
# SI se lleva, que es como estaban todos antes de que se pudiera elegir, asi
# que en el archivo solo aparece cuando se quita, como `"c": 0`.
CON_ARO = 1
SIN_ARO = 0


def es_color(valor) -> bool:
    """Si un valor es un color utilizable, en la forma `#rrggbb`.

    Se exige la forma larga y en hexadecimal a proposito, aunque el navegador
    entienda `red` o `#abc`: el color lo elige un selector del editor, que
    siempre da `#rrggbb`, y aceptar mas formas es aceptar mas sitios por donde
    colar algo que no es un color. En un `fill` de SVG, ademas, un valor raro
    no da error: el navegador lo ignora y la zona sale sin pintar.

    No se admite `none` ni la cadena vacia: para "sin relleno" esta no poner la
    clave, que es lo que hace que el archivo quede corto.
    """
    if not isinstance(valor, str) or len(valor) != 7 or valor[0] != "#":
        return False
    return all(c in "0123456789abcdefABCDEF" for c in valor[1:])

# Los modelos: iconos guardados enteros, con su tamano, su giro, su animacion
# y su informacion, para poder estampar varios iguales de un clic. Viven en
# editor/modelos.json y no dentro del croquis, porque son una herramienta de
# quien edita y no contenido del mapa: el archivo publicado no los necesita y
# cada byte suyo lo descarga un movil por nada.
MAX_MODELOS = 60
MAX_NOMBRE_MODELO = 40

# Las claves de un icono. Se rechaza cualquier otra: un nombre mal escrito
# (`X` por `x`) dejaria el icono sin ese dato y no se notaria hasta verlo en
# el mapa, que es la peor forma de enterarse.
CLAVES_ICONO = {"t", "x", "y", "n", "s", "r", "a", "c", "m", "i", "u"}

# El texto que sale en la ventana al tocar un icono. Va dentro del croquis,
# asi que se limita: una parrafada convertiria la pagina del movil en algo
# que tarda en abrir, y en una ventana tampoco se lee.
MAX_TITULO = 60
MAX_TEXTO = 600

# El boton con enlace que puede llevar la ventana. Es [texto, direccion].
#
# La direccion solo puede ser http o https, y se comprueba aqui ademas de en
# el croquis: aqui se avisa al escribirla, y alli se vuelve a mirar antes de
# pintarla. En el archivo publicado acaba en un `href`, y una `javascript:`
# ahi seria una forma de ejecutar codigo en la pagina de quien mira el mapa.
# Dos comprobaciones para lo mismo porque el editor escribe el archivo y el
# croquis lo lee, y cualquiera de los dos se puede cambiar sin el otro.
MAX_BOTON = 40
MAX_URL = 300
ESQUEMAS = ("http://", "https://")


def enlace_seguro(url) -> bool:
    """Si una direccion se puede poner en un `href` sin riesgo.

    Se exige el dominio entero. Una direccion sin esquema, como
    `owncloud.rec.uabc.mx`, el navegador la toma por una ruta relativa a la
    pagina y no lleva a ninguna parte; y un esquema raro (`javascript:`) es
    codigo disfrazado de direccion.
    """
    if not isinstance(url, str):
        return False
    limpia = url.strip().lower()
    return limpia.startswith(ESQUEMAS) and " " not in url.strip()


# Los archivos que se pueden enlazar desde el croquis. Viven en RecursosExtra,
# en la raiz del repositorio, al lado de plantilla/: el croquis esta dentro de
# plantilla/ y los alcanza con `../RecursosExtra/`.
#
# No se meten dentro del propio croquis por un motivo que importa mas de lo que
# parece: el croquis se descarga ENTERO con el QR, asi que un PDF de unos megas
# en base64 dentro del HTML dejaria el mapa inservible en un movil. Como
# archivos sueltos, el navegador solo se baja el que se pide, y solo si se pide.
CARPETA_RECURSOS = "RecursosExtra"
MAX_RECURSO = 80

# Lo que no puede llevar un nombre de archivo. Se dejan fuera todos los signos
# que significan algo en una direccion: la barra y la barra invertida, para
# que no se pueda apuntar a otra carpeta; los dos puntos, la interrogacion y el
# almohadilla, para que no se pueda colar un parametro o un fragmento.
SIGNOS_RAROS = "/\\:?#[]*\"<>|"


def es_recurso(valor) -> bool:
    """Si un destino es un archivo de RecursosExtra.

    Es la mitad interna de `es_destino`: un archivo del propio repositorio, en
    vez de una direccion de fuera. Se comprueba la forma entera, no que
    empiece por el prefijo: `RecursosExtra/../../etc` empieza bien y no vale.
    """
    if not isinstance(valor, str) or len(valor) > MAX_URL:
        return False
    partes = valor.split("/")
    if len(partes) != 2 or partes[0] != CARPETA_RECURSOS:
        return False
    nombre = partes[1]
    if not nombre or len(nombre) > MAX_RECURSO or nombre.startswith("."):
        return False
    if any(c in SIGNOS_RAROS or ord(c) < 32 for c in nombre):
        return False
    # Un archivo tiene extension, y la extension es lo que decide si se puede
    # ver dentro del mapa o se descarga.
    return "." in nombre[1:]


def es_destino(valor) -> bool:
    """Si un destino se puede poner en un `href` sin riesgo.

    Son dos cosas muy distintas y por eso se distinguen: una direccion de
    fuera, con su dominio y su esquema, o un archivo del propio RecursosExtra.
    Cualquier otra cosa -un esquema raro, una ruta relativa suelta- se rechaza.
    """
    return enlace_seguro(valor) or es_recurso(valor)


# Las extensiones que se ensenan en una vista previa al pulsarlas. Las demas se
# descargan, porque no hay nada que mirar dentro.
#
# La lista esta en los dos sitios: el croquis decide que hacer al pulsar, y el
# editor decide que decir al elegir el archivo. Es a proposito, porque ninguno
# de los dos puede preguntarle al otro en el momento del toque; una prueba
# comprueba que las dos listas dicen lo mismo.
EXTENSIONES_IMAGEN = ("png", "jpg", "jpeg", "webp", "gif", "avif", "svg", "bmp")

# Los tipos de imagen que se admiten como icono propio.
#
# El SVG va aparte de los demas porque no se trata igual: no se reduce ni se
# recorta, se limpia y se guarda tal cual. Es vector, asi que se ve nitido a
# cualquier tamano y un icono ampliado no se pixela, que es justo lo que se
# busca al subirlo en SVG.
TIPOS_IMAGEN = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
TIPOS_VECTOR = (".svg",)

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


def revisar_adornos(adornos, sitio: str) -> list[str]:
    """Los problemas de los adornos de una zona. Vacia es que todo bien.

    Los adornos son el objeto opcional que puede ir en quinto lugar dentro de
    la zona. Se valida aparte de `revisar_zonas` porque son dos cosas
    distintas: una zona sin adornos es de fabrica y perfectamente valida, y
    ademas el editor los valida por su cuenta mientras se escriben, sin esperar
    a guardar.
    """
    problemas: list[str] = []
    if not isinstance(adornos, dict):
        return [f"{sitio}: los adornos tienen que ser un objeto como "
                f'{{"f": "#c8e6c9", "l": "#00723f"}}']

    raros = sorted(set(adornos) - CLAVES_ZONA)
    if raros:
        return [f"{sitio}: en los adornos no conozco {' ni '.join(raros)}. "
                f"Las claves son {', '.join(sorted(CLAVES_ZONA))} "
                f"(f=relleno, l=linea, p=punteada, a=animacion, b=borde, "
                f"d=sentido, m=intensidad)"]

    for clave, cual in (("f", "el relleno"), ("l", "la linea")):
        if clave in adornos and not es_color(adornos[clave]):
            problemas.append(
                f"{sitio}: {cual} tiene que ser un color en la forma #rrggbb, "
                f"y viene {adornos[clave]!r}")

    if "p" in adornos:
        # El punteado no es un adorno por si solo: es como se pinta la linea.
        # Sin linea no hay nada que puntear, y dejarlo pasar seria guardar un
        # ajuste que no hace nada.
        if adornos["p"] != 1 and adornos["p"] is not True:
            problemas.append(
                f"{sitio}: «p» solo puede ser 1 (punteada) y viene "
                f"{adornos['p']!r}")
        elif not adornos.get("l"):
            problemas.append(
                f"{sitio}: la linea esta puesta como punteada pero no tiene "
                f"color, asi que no hay linea que puntear")

    if "rd" in adornos:
        rd = adornos["rd"]
        if not isinstance(rd, (int, float)) or isinstance(rd, bool):
            problemas.append(
                f"{sitio}: el redondeo de las esquinas tiene que ser un numero")
        elif not MIN_REDONDEO <= rd <= MAX_REDONDEO:
            problemas.append(
                f"{sitio}: el redondeo {rd:.0f} se sale de {MIN_REDONDEO} a "
                f"{MAX_REDONDEO} puntos")

    for clave, lista, cual in (("a", ANIMACIONES_ZONA, "la zona"),
                               ("b", ANIMACIONES_BORDE, "el borde")):
        if clave not in adornos:
            continue
        if adornos[clave] not in lista:
            problemas.append(
                f"{sitio}: «{adornos[clave]}» no es una animacion de {cual} de "
                f"las que hay. Las que hay: "
                f"{', '.join(k for k in lista if k) or 'ninguna'}")
        # Una animacion de borde sin linea no se ve: el borde es la linea.
        if clave == "b" and adornos[clave] and not adornos.get("l"):
            problemas.append(
                f"{sitio}: el borde tiene animacion pero la linea no tiene "
                f"color, asi que no hay nada que animar")

    if "d" in adornos:
        # El sentido solo vale para `camina`: es la unica que recorre el borde
        # de punta a punta. En las demas no hay nada que invertir, y guardarlo
        # seria un ajuste que no hace nada.
        sentido = adornos["d"]
        if isinstance(sentido, bool) or sentido not in SENTIDOS_CAMINA:
            problemas.append(
                f"{sitio}: «{sentido!r}» no es un sentido valido. Los que hay: "
                f"{', '.join(str(k) for k in SENTIDOS_CAMINA)}")
        elif adornos.get("b") != "camina":
            problemas.append(
                f"{sitio}: el sentido es cosa de la animacion «Camina», y el "
                f"borde esta en «{adornos.get('b') or 'Quieta'}»")

    if "m" in adornos:
        inte = adornos["m"]
        if not isinstance(inte, (int, float)) or isinstance(inte, bool):
            problemas.append(f"{sitio}: la intensidad tiene que ser un numero")
        elif not MIN_INTENSIDAD <= inte <= MAX_INTENSIDAD:
            problemas.append(
                f"{sitio}: la intensidad {inte:.2f} se sale de "
                f"{MIN_INTENSIDAD} a {MAX_INTENSIDAD}")
        elif not (adornos.get("a") or adornos.get("b")):
            # La intensidad modula un movimiento: sin movimiento no modula
            # nada, y seria un ajuste que se guarda y no se ve.
            problemas.append(
                f"{sitio}: hay intensidad pero no hay ninguna animacion que "
                f"ajustar")

    return problemas


def limpiar_adornos(adornos) -> dict:
    """Los adornos sin lo que sobra, para que el archivo quede corto.

    Se llama al guardarlos desde el editor, que manda lo que tiene en pantalla
    y no siempre esta todo. Se descarta lo vacio y lo que vale por defecto, por
    el mismo motivo que en los ajustes de los iconos: una zona sin adornos
    tiene que seguir guardandose igual que antes de que esto existiera.
    """
    if not isinstance(adornos, dict):
        return {}
    limpio: dict = {}
    for clave in ("f", "l", "a", "b"):
        valor = adornos.get(clave)
        if valor not in ("", None):
            limpio[clave] = valor
    # El punteado solo se escribe cuando esta puesto, y el 0 no vale: es lo de
    # siempre. Se mira por lo que vale y no con `in` porque aqui el 0 y la
    # ausencia significan lo mismo, al reves que en el circulo de los iconos.
    if adornos.get("p"):
        limpio["p"] = 1
    # El redondeo, igual: 0 es «esquinas en angulo recto», o sea lo de siempre.
    if adornos.get("rd"):
        limpio["rd"] = adornos["rd"]
    # Y el sentido, solo cuando va al reves: el normal es el que sale solo, el
    # mismo motivo por el que no se escribe el punteado ni el redondeo en 0.
    if adornos.get("d") == SENTIDO_REVES:
        limpio["d"] = SENTIDO_REVES
    if adornos.get("m") and adornos["m"] != INTENSIDAD:
        limpio["m"] = adornos["m"]
    return limpio


def revisar_zonas(zonas: list) -> list[str]:
    """Devuelve la lista de problemas de las zonas. Vacia es que todo bien.

    Cada zona es [nombre, nombre corto, poligono, descripcion], con el
    poligono como lista de puntos [x, y]. Opcionalmente puede llevar un quinto
    elemento con los adornos (relleno, linea y animaciones); las zonas que no
    lo llevan son las de siempre y se comportan igual que antes de que
    existiera.
    """
    problemas: list[str] = []

    if not zonas:
        return ["no hay ninguna zona: el mapa se quedaria sin nada que tocar"]

    poligonos = []
    for k, z in enumerate(zonas):
        sitio = f"zona {k + 1}"
        if not isinstance(z, (list, tuple)) or len(z) not in (4, 5):
            problemas.append(
                f"{sitio}: tiene que ser [nombre, corto, poligono, descripcion] "
                f"y, si lleva adornos, un quinto elemento")
            poligonos.append(None)
            continue

        nombre, corto, poligono, desc = z[:4]
        if len(z) == 5:
            problemas.extend(revisar_adornos(z[4], sitio))
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


def _revisar_icono(ic, sitio: str, conocidos: set, con_posicion: bool) -> list[str]:
    """Los problemas de un icono suelto.

    `con_posicion` distingue un icono del mapa de un modelo guardado. Un modelo
    no lleva x ni y, porque el sitio se elige al estamparlo; si se le
    exigieran, guardar un modelo seria imposible.
    """
    problemas: list[str] = []
    if not isinstance(ic, dict):
        ejemplo = ('{t:"bano", x:499, y:470}' if con_posicion
                   else '{t:"bano", s:60, a:"late"}')
        return [f"{sitio}: tiene que ser un objeto como {ejemplo}"]

    raros = sorted(set(ic) - CLAVES_ICONO)
    if raros:
        return [f"{sitio}: no conozco {' ni '.join(raros)}. "
                f"Las claves son {', '.join(sorted(CLAVES_ICONO))} "
                f"(t=tipo, x, y, n=etiqueta, s=tamaño, r=rotación, "
                f"a=animación, c=círculo, m=intensidad, i=información, "
                f"u=botón con enlace)"]

    tipo = ic.get("t")
    if tipo not in conocidos:
        return [f"{sitio}: «{tipo}» no es un simbolo conocido ni un icono tuyo. "
                f"Los que hay: {', '.join(sorted(conocidos))}"]

    if con_posicion:
        x, y = ic.get("x"), ic.get("y")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (x, y)):
            return [f"{sitio}: hacen falta las coordenadas x e y como numeros"]
        if not (MARGEN_ICONO <= x <= ANCHO - MARGEN_ICONO and
                MARGEN_ICONO <= y <= ALTO - MARGEN_ICONO):
            problemas.append(
                f"{sitio} ({titulo_de(tipo, conocidos)}): esta pegado al borde del "
                f"mapa ({x:.0f}, {y:.0f}); el centro tiene que caer dentro")

    if "n" in ic and not isinstance(ic["n"], str):
        problemas.append(f"{sitio}: la etiqueta tiene que ser texto")

    if "s" in ic:
        tam = ic["s"]
        if not isinstance(tam, (int, float)) or isinstance(tam, bool):
            problemas.append(f"{sitio}: el tamaño tiene que ser un numero")
        elif not MIN_TAM_ICONO <= tam <= MAX_TAM_ICONO:
            problemas.append(
                f"{sitio}: el tamaño {tam:.0f} se sale del rango de "
                f"{MIN_TAM_ICONO} a {MAX_TAM_ICONO}")

    if "r" in ic:
        rot = ic["r"]
        if not isinstance(rot, (int, float)) or isinstance(rot, bool):
            problemas.append(f"{sitio}: la rotación tiene que ser un numero")
        elif not MIN_ROT <= rot <= MAX_ROT:
            problemas.append(
                f"{sitio}: la rotación {rot:.0f}° se sale de "
                f"{MIN_ROT} a {MAX_ROT}")

    if "a" in ic and ic["a"] not in ANIMACIONES:
        problemas.append(
            f"{sitio}: «{ic['a']}» no es una animación de las que hay. "
            f"Las que hay: {', '.join(k for k in ANIMACIONES if k) or 'ninguna'}")

    if "m" in ic:
        inte = ic["m"]
        if not isinstance(inte, (int, float)) or isinstance(inte, bool):
            problemas.append(f"{sitio}: la intensidad tiene que ser un numero")
        elif not MIN_INTENSIDAD <= inte <= MAX_INTENSIDAD:
            problemas.append(
                f"{sitio}: la intensidad {inte:.2f} se sale de "
                f"{MIN_INTENSIDAD} a {MAX_INTENSIDAD}")
        elif ic.get("a") in ANIMACIONES_SIN_INTENSIDAD:
            problemas.append(
                f"{sitio}: la animación «{ic['a']}» da una vuelta completa y no "
                f"tiene intensidad que ajustar; quita el «m»")

    if "c" in ic and ic["c"] not in (CON_ARO, SIN_ARO):
        problemas.append(
            f"{sitio}: «c» solo puede ser {SIN_ARO} (sin el círculo) o "
            f"{CON_ARO} (con él), y viene {ic['c']!r}")

    if "i" in ic:
        info = ic["i"]
        if (not isinstance(info, (list, tuple)) or len(info) != 2
                or not all(isinstance(t, str) for t in info)):
            problemas.append(
                f'{sitio}: la información tiene que ser [título, texto]')
        else:
            titulo, texto = info
            if not titulo.strip():
                problemas.append(f"{sitio}: la información no tiene título")
            elif len(titulo) > MAX_TITULO:
                problemas.append(
                    f"{sitio}: el título pasa de {MAX_TITULO} caracteres")
            if not texto.strip():
                problemas.append(f"{sitio}: la información no tiene texto")
            elif len(texto) > MAX_TEXTO:
                problemas.append(
                    f"{sitio}: el texto de la información pasa de "
                    f"{MAX_TEXTO} caracteres y no se lee en una ventana")

    if "u" in ic:
        boton = ic["u"]
        if (not isinstance(boton, (list, tuple)) or len(boton) != 2
                or not all(isinstance(t, str) for t in boton)):
            problemas.append(f"{sitio}: el botón tiene que ser [texto, dirección]")
        else:
            texto, url = boton
            if not texto.strip():
                problemas.append(f"{sitio}: el botón no tiene texto")
            elif len(texto) > MAX_BOTON:
                problemas.append(
                    f"{sitio}: el texto del botón pasa de {MAX_BOTON} caracteres "
                    f"y no cabe en el botón")
            if len(url) > MAX_URL:
                problemas.append(
                    f"{sitio}: la dirección pasa de {MAX_URL} caracteres")
            elif not es_destino(url):
                problemas.append(
                    f"{sitio}: «{url[:40]}» no es un destino válido. Tiene que "
                    f"empezar por https:// o http://, o ser un archivo de "
                    f"{CARPETA_RECURSOS}. Un enlace sin esquema se toma por "
                    f"una ruta de esta misma página, y uno con otro esquema "
                    f"(javascript:) es código disfrazado de dirección")
            if not ic.get("i"):
                problemas.append(
                    f"{sitio}: tiene un botón con enlace pero no tiene "
                    f"información, y el botón sale dentro de esa ventana: sin "
                    f"título ni texto no hay dónde ponerlo")

    return problemas


def revisar_iconos(iconos: list, propios=None) -> list[str]:
    """Devuelve la lista de problemas de los iconos del mapa.

    Cada icono es un objeto, y solo hacen falta el tipo y el sitio:

        {t: "bano", x: 499, y: 470}
        {t: "informacion", x: 620, y: 300, s: 60, r: -15, a: "late",
         n: "Módulo de información",
         i: ["Información", "Aquí puedes preguntar por el programa..."]}

    Los nombres de las claves son cortos porque se repiten en cada icono y el
    archivo se escribe a mano. Antes era una tupla posicional y creció hasta
    siete campos, que es donde uno empieza a contar comas con la vista; con
    nombres cada dato se lee solo y se pueden dejar fuera los que no hacen
    falta.

    El tipo puede ser uno de los simbolos de SIMBOLOS o un icono propio, que
    son los que vienen en `propios`. Uno que no este en ninguna de las dos
    listas saldria como un hueco sin nada y sin ningun error en consola.
    """
    if not isinstance(iconos, (list, tuple)):
        return ["los iconos tienen que ser una lista"]

    conocidos = set(SIMBOLOS) | set(propios or {})
    problemas: list[str] = []
    for k, ic in enumerate(iconos):
        problemas.extend(_revisar_icono(ic, f"icono {k + 1}", conocidos, True))
    return problemas


def revisar_modelos(modelos, propios=None) -> list[str]:
    """Los problemas de los modelos guardados.

    Un modelo es `{nombre, i: {...}}`, donde el icono lleva todo menos la
    posicion: eso es justo lo que se estampa al hacer clic. Se valida con las
    mismas reglas que un icono del mapa, que es la unica forma de que un
    modelo guardado no acabe dando un icono que el croquis rechace.

    Los modelos NO van dentro del croquis: son una herramienta de quien edita
    y viven en editor/modelos.json. El archivo publicado no los necesita, y
    cada byte de mas lo descarga un movil por nada.
    """
    if modelos is None:
        return []
    if not isinstance(modelos, (list, tuple)):
        return ["los modelos tienen que ser una lista"]

    conocidos = set(SIMBOLOS) | set(propios or {})
    problemas: list[str] = []
    if len(modelos) > MAX_MODELOS:
        problemas.append(
            f"Hay {len(modelos)} modelos y el tope son {MAX_MODELOS}. "
            f"Quita alguno: esta lista es para tener a mano los de este "
            f"evento, no un catálogo")

    vistos = set()
    for k, m in enumerate(modelos):
        sitio = f"modelo {k + 1}"
        if not isinstance(m, dict) or "nombre" not in m or "i" not in m:
            problemas.append(
                f'{sitio}: tiene que ser {{"nombre": "...", "i": {{...}}}}')
            continue

        nombre = m["nombre"]
        if not isinstance(nombre, str) or not nombre.strip():
            problemas.append(f"{sitio}: le falta el nombre")
        elif len(nombre) > MAX_NOMBRE_MODELO:
            problemas.append(
                f"{sitio}: el nombre pasa de {MAX_NOMBRE_MODELO} caracteres")
        elif nombre.strip().lower() in vistos:
            problemas.append(
                f"{sitio}: hay dos modelos que se llaman «{nombre.strip()}». "
                f"Con dos iguales no se sabe cuál se está estampando")
        else:
            vistos.add(nombre.strip().lower())

        icono = m["i"]
        # Un modelo no puede llevar posicion: la elige quien estampa. Se
        # comprueba aqui porque es lo unico del modelo que las reglas del
        # icono no pueden ver.
        if isinstance(icono, dict) and ({"x", "y"} & set(icono)):
            problemas.append(
                f"{sitio}: el icono no puede llevar x ni y; la posición se "
                f"elige al pulsar en el mapa")
            continue

        # Se le añade una posicion de mentira para reutilizar la validacion
        # del mapa, que exige x e y. El centro del mapa siempre vale.
        if isinstance(icono, dict):
            icono = dict(icono, x=ANCHO / 2, y=ALTO / 2)
        problemas.extend(_revisar_icono(
            icono, f"{sitio} «{m['nombre']}»", conocidos, True))

    return problemas


def revisar_ajustes(ajustes) -> list[str]:
    """Los problemas de unos ajustes de icono propio. Vacia es que todo bien.

    Unos ajustes son la configuracion con la que se subio una imagen: el
    tamano, la animacion y si lleva circulo. Se guardan al lado del PNG, en la
    biblioteca, y son lo que hace que al volver a poner ese icono salga como se
    dejo en vez de con los valores de fabrica.

    Se validan con las mismas reglas que un icono del mapa. No es un capricho:
    unos ajustes malos no se notan al guardarlos, sino al estampar con ellos, y
    entonces ya hay veinte iconos mal puestos en el mapa.
    """
    if ajustes is None:
        return []
    if not isinstance(ajustes, dict):
        return ["los ajustes tienen que ser un objeto"]

    raros = sorted(set(ajustes) - {"s", "a", "m", "c"})
    if raros:
        return [f"en los ajustes no conozco {' ni '.join(raros)}. "
                f"Los que hay son s (tamaño), a (animación), m (intensidad) "
                f"y c (círculo)"]

    problemas: list[str] = []

    if "s" in ajustes:
        tam = ajustes["s"]
        if not isinstance(tam, (int, float)) or isinstance(tam, bool):
            problemas.append("el tamaño de los ajustes tiene que ser un numero")
        elif not MIN_TAM_ICONO <= tam <= MAX_TAM_ICONO:
            problemas.append(
                f"el tamaño {tam:.0f} de los ajustes se sale de "
                f"{MIN_TAM_ICONO} a {MAX_TAM_ICONO}")

    if "a" in ajustes and ajustes["a"] not in ANIMACIONES:
        problemas.append(
            f"«{ajustes['a']}» no es una animación de las que hay. "
            f"Las que hay: {', '.join(k for k in ANIMACIONES if k) or 'ninguna'}")

    if "m" in ajustes:
        inte = ajustes["m"]
        if not isinstance(inte, (int, float)) or isinstance(inte, bool):
            problemas.append("la intensidad de los ajustes tiene que ser un numero")
        elif not MIN_INTENSIDAD <= inte <= MAX_INTENSIDAD:
            problemas.append(
                f"la intensidad {inte:.2f} de los ajustes se sale de "
                f"{MIN_INTENSIDAD} a {MAX_INTENSIDAD}")
        elif ajustes.get("a") in ANIMACIONES_SIN_INTENSIDAD:
            problemas.append(
                f"la animación «{ajustes['a']}» da una vuelta completa y no tiene "
                f"intensidad que ajustar; quita la «m» de los ajustes")

    if "c" in ajustes and ajustes["c"] not in (CON_ARO, SIN_ARO):
        problemas.append(
            f"el círculo de los ajustes solo puede ser {SIN_ARO} (sin él) o "
            f"{CON_ARO} (con él), y viene {ajustes['c']!r}")

    return problemas


def limpiar_ajustes(ajustes) -> dict:
    """Los ajustes sin lo que sobra: solo s, a, m y c, y solo si valen.

    Se llama al guardarlos desde el editor, que manda lo que tiene en pantalla
    y no siempre esta todo. Se descarta lo vacio para que el archivo quede
    corto: unos ajustes con `a: ""` y `c: 1` son exactamente los de fabrica y
    no hace falta escribirlos.
    """
    limpio: dict = {}
    for clave in ("s", "a", "m", "c"):
        if clave not in ajustes:
            continue
        valor = ajustes[clave]
        if valor in ("", None):
            continue
        if clave == "c" and valor == CON_ARO:
            # Con circulo es lo de siempre: no se escribe.
            continue
        if clave == "m" and valor == INTENSIDAD:
            # La intensidad normal tampoco: es la de fabrica.
            continue
        limpio[clave] = valor
    return limpio


def titulo_de(tipo: str, conocidos=None) -> str:
    """Como se llama un icono para ensenarlo en un mensaje de error.

    `conocidos` puede ser el diccionario de propios, o el conjunto de tipos
    que hay: da igual, lo unico que importa es si el tipo esta en SIMBOLOS.
    """
    if tipo in SIMBOLOS:
        return SIMBOLOS[tipo]
    return f"icono propio «{tipo}»"


def revisar_propios(propios) -> list[str]:
    """Devuelve la lista de problemas de los iconos propios.

    Cada uno es un nombre y una imagen metida en el propio HTML como data
    URL. Aqui se comprueba que sea de verdad una imagen, que el nombre se
    pueda escribir sin comillas raras y que el total no engorde el archivo
    mas de la cuenta.
    """
    problemas: list[str] = []
    if propios is None:
        return []
    if not isinstance(propios, dict):
        return ["los iconos propios tienen que ser un diccionario de nombre a imagen"]

    total = 0
    for nombre, datos in propios.items():
        if not NOMBRE_PROPIO.fullmatch(nombre or ""):
            problemas.append(
                f"«{nombre}» no sirve como nombre de icono: solo minusculas, "
                f"numeros y guiones, y hasta 24 caracteres")
            continue
        if nombre in SIMBOLOS:
            problemas.append(
                f"«{nombre}» ya es el nombre de un icono de los de siempre; "
                f"ponle otro para no confundirlos")
            continue
        if not isinstance(datos, str):
            problemas.append(f"«{nombre}»: la imagen tiene que ser texto")
            continue
        if not datos.startswith("data:image/"):
            lugares = [n for n, d in propios.items()
                       if isinstance(d, str) and d.startswith("data:image/")]
            pista = ""
            if not lugares:
                pista = ("\nSi lo has editado a mano: la imagen tiene que ser "
                         "una data URL que empiece por data:image/")
            problemas.append(f"«{nombre}»: eso no es una imagen incrustada{pista}")
            continue
        if ";base64," not in datos:
            problemas.append(f"«{nombre}»: la imagen tiene que venir en base64")
            continue
        # Los vectores llevan su propio tope, mas alto: no se reducen como una
        # imagen, asi que un SVG pesado sigue siendo nitido y vale la pena.
        es_vector = datos.startswith("data:image/svg+xml")
        tope = MAX_VECTOR if es_vector else MAX_ICONO
        if len(datos) > tope:
            problemas.append(
                f"«{nombre}»: {'el SVG' if es_vector else 'la imagen'} ocupa "
                f"{len(datos) // 1024} KB y el tope son {tope // 1024} KB. "
                f"{'Simplifícalo' if es_vector else 'Súbela más pequeña'}")
            continue
        total += len(datos)

    if total > MAX_ICONOS_PROPIOS:
        problemas.append(
            f"Entre todos los iconos propios suman {total // 1024} KB y el tope "
            f"son {MAX_ICONOS_PROPIOS // 1024} KB: el croquis tardaría en abrir. "
            f"Quita alguno o sube las imágenes más pequeñas")

    return problemas


# --- El boton del croquis ---------------------------------------------------
# El boton que sale debajo de los accesos rapidos: el programa del evento, una
# guia, un plano en PDF. Tiene su propio bloque en el archivo porque es otra
# cosa que las zonas y los iconos: hay uno solo, sale siempre en el mismo sitio
# y no se coloca en el mapa.
#
#   t   el texto que se lee en el boton
#   u   a donde lleva: una direccion http(s) o un archivo de RecursosExtra
#
# Vacio o ausente es un croquis sin boton, y es perfectamente valido.
CLAVES_ENLACE = {"t", "u"}


def revisar_enlace(enlace, sitio: str = "el botón del mapa") -> list[str]:
    """Los problemas del boton del croquis. Vacia es que todo bien."""
    if enlace is None or enlace == {}:
        return []
    if not isinstance(enlace, dict):
        return [f"{sitio}: tiene que ser un objeto como "
                f'{{"t": "Programa del evento", "u": "https://…"}}']
    problemas = []
    raros = sorted(set(enlace) - CLAVES_ENLACE)
    if raros:
        return [f"{sitio}: no conozco {' ni '.join(raros)}. Las claves son "
                f"t (el texto) y u (a dónde lleva)"]
    texto = enlace.get("t")
    if not isinstance(texto, str) or not texto.strip():
        problemas.append(f"{sitio}: le falta el texto que se lee en el botón")
    elif len(texto) > MAX_BOTON:
        problemas.append(
            f"{sitio}: el texto pasa de {MAX_BOTON} caracteres y no cabe en "
            f"el botón")
    destino = enlace.get("u")
    if not es_destino(destino):
        problemas.append(
            f"{sitio}: «{str(destino)[:40]}» no es un destino válido. Tiene que "
            f"empezar por https:// o http://, o ser un archivo de "
            f"{CARPETA_RECURSOS}")
    return problemas


def limpiar_enlace(enlace) -> dict | None:
    """El boton sin lo que sobra. None si no hay boton que poner.

    Se llama al guardar desde el editor, que manda los campos del formulario
    rellenos o no. Un boton al que le falte el texto o el destino no se guarda
    a medias: se guarda entero o no se guarda, porque medio boton no se puede
    pintar y dejaria un hueco sin explicacion en el croquis.
    """
    if not isinstance(enlace, dict):
        return None
    limpio = {}
    for clave in ("t", "u"):
        valor = enlace.get(clave)
        if isinstance(valor, str) and valor.strip():
            limpio[clave] = valor.strip()
    return limpio if len(limpio) == 2 else None


def revisar(zonas: list, iconos: list, propios=None, enlace=None) -> list[str]:
    """Todos los problemas juntos: zonas, iconos, iconos propios y el boton."""
    return (revisar_zonas(zonas) + revisar_propios(propios)
            + revisar_iconos(iconos, propios) + revisar_enlace(enlace))
