# Orgullo Cimarrón — QR que abre el croquis del campus

Un código QR que, al escanearlo con cualquier dispositivo, abre un croquis
interactivo del campus Mexicali de la UABC. Tocar un edificio lo amplía y
muestra su ficha.

El QR **no lleva el HTML dentro**: lleva la dirección del HTML, que ya está
publicado en GitHub Pages.

```
https://tonycabreram.github.io/OrgulloCimarron/plantilla/croquis.html
└────────────── 69 caracteres ──────────────┘
```

Eso son 49×49 módulos. La versión anterior, con el HTML comprimido dentro del
propio QR, ocupaba 149×149: **90% más cuadros**, y además había que regenerar
el QR cada vez que se editaba el HTML.

## Los tres modos

| Modo | Qué lleva el QR | Módulos | Cuándo usarlo |
| --- | --- | --- | --- |
| `enlace` *(por defecto)* | Solo la URL del HTML | **49×49** | El normal. Editas el HTML, subes el cambio, y el QR ya abre la versión nueva |
| `servidor` | URL de una página base + el HTML comprimido en el `#` | 149×149 | Si quieres que el QR no dependa del hosting, o una versión congelada |
| `sin-servidor` | URL `javascript:` con el HTML dentro | 149×149 | **No sirve para imprimir**: Chrome en Android y Safari en iOS la bloquean |

> **En los tres modos hace falta hosting.** En `enlace` y `servidor` el móvil
> descarga el HTML de la red; en `servidor` además descarga la página base.
> Lo único que cambia es de dónde sale el contenido.

## Publicar

El modo `enlace` necesita una sola cosa: que el HTML esté en la URL que lleva
el QR. En este repo ya lo está, así que basta con subir el cambio cuando
edites el croquis.

| Servicio | Cómo |
| --- | --- |
| **GitHub Pages** *(el de este repo)* | Sube el repo y activa Pages desde la rama |
| **Netlify Drop** | Arrastra la carpeta, usa la URL que te den |
| **Cloudflare Pages** | Conecta el repo o sube la carpeta |

Para el modo `servidor` hay que subir además `d.html` en la raíz del repo. Es
un archivo único que sirve para todos los QR: solo lee `location.hash` y nunca
cambia.

## El color del QR

El QR usa la paleta institucional de la UABC, sacada del **Manual de Identidad
Gráfica (2022)**. Se elige con `--color`:

| Opción | Módulos | Contraste | Cuándo |
| --- | --- | --- | --- |
| `uabc` *(por defecto)* | `#EC008C` | 4.25:1 color, 7.2:1 gris | El magenta primario, tal cual |
| `uabc-oscuro` | `#C90077` | 5.60:1 color, 8.9:1 gris | El mismo magenta un 15% más oscuro |
| `azul` | `#204199` | 9.22:1 color, 10.2:1 gris | Azul oscuro institucional, el más seguro de color |
| `verde` | `#00723F` | 6.04:1 color, 8.9:1 gris | Verde institucional |
| `negro` | `#231F20` | 16.30:1 | Negro tinta, el más seguro de todos |

### Por qué el contraste se mide dos veces

Un lector de QR **termina binarizando la imagen**, así que lo que decide si
encuentra el código no es el color, sino cuántos píxeles se ven claros u
oscuros **en gris**. El magenta puro tiene 4.25:1 en color pero 7.2:1 en gris, y
por eso funciona.

El generador mide ambos y avisa:

```
Contraste        : 4.25:1 en color, 7.23:1 en gris
Aviso            : color muy saturado (236,0,140): al quedarse en gris pierde
                   contraste, y así es como leen la mayoría de los lectores
```

La prueba `colores institucionales legibles` genera el QR con **las cinco
paletas** y lo lee con zxing-cpp en cinco situaciones: normal, al 55% de tamaño,
con la mitad de contraste, con poca luz y en blanco y negro. Las cinco paletas
superan las cinco.

> **Sobre la suciedad:** si le pones un manchón grande encima, falla con
> cualquier color, incluido el negro. Eso no es culpa del color, es que el
> manchón tapa los patrones de referencia. El QR no se rompe, solo hay que
> limpiarlo.

Si vas a imprimir en color y no quieres riesgo, `--color uabc-oscuro` es el
mismo magenta con más margen. Para un cartel en blanco y negro, cualquier
paleta sirve: el lector hace la conversión por ti.

Cada módulo es un cuadrado, así que lo que manda es el **número de bytes de la
URL**, no el del documento. En modo `enlace` eso son 69 bytes y no hay nada que
recortar. Lo único que queda es acortar la URL:

| URL | Caracteres | Módulos (nivel H) |
| --- | --- | --- |
| `https://tonycabreram.github.io/OrgulloCimarron/plantilla/croquis.html` | 69 | 49×49 |
| `https://tonycabreram.github.io/OrgulloCimarron/c.html` *(copia en la raíz)* | 55 | 45×45 |
| Dominio propio, p. ej. `https://c.im/` | 12 | 25×25 |

### Elegir el nivel de corrección

Con tan pocos bytes hay sitio de sobra, así que se puede elegir el nivel más
robusto. **No es una decisión gratuita**: subir la corrección de errores obliga
a **más** módulos.

| Nivel | Corrección | Módulos | Cuándo |
| --- | --- | --- | --- |
| `H` *(por defecto)* | 30% | 49×49 | Cartel en la calle, sol, lluvia, que se raye |
| `M` | 15% | 37×37 | Folleto protegido, interior |
| `L` | 7% | 33×33 | Los menos cuadros posibles, en papel limpio |

## Cómo se lee en un teléfono (modo `servidor`)

Para el modo `servidor`, el QR apunta a la página base seguida del `#` y el
fragmento. La página base hace tres cosas:

1. Copia el fragmento de `location.hash` y traduce `-` y `_` a `+` y `/`, porque
   `atob` solo entiende el alfabeto base64 estándar.
2. Lo descomprime con `DecompressionStream('gzip')`.
3. Lo mete en un `<iframe>` con `srcdoc`.

Se usa un `iframe` y no `document.write` a propósito: `document.write` se
come la propia página base, así que el aviso de error desaparecería y un
segundo escaneo con la página ya abierta se quedaría en blanco. Con `iframe`
la base sigue viva, los errores se pueden mostrar y `hashchange` recarga.

## Uso

```bash
python generar_qr.py --html plantilla/croquis.html --salida salida/croquis --nivel H
```

Produce en `salida/`:

| Archivo | Para qué sirve |
| --- | --- |
| `croquis.png` | El QR listo para compartir |
| `croquis.svg` | El mismo QR como vector, para imprenta |

Para otro documento, cambia `--html` y `URL_HTML` en `generar_qr.py`.

Opciones útiles:

| Opción | Efecto |
| --- | --- |
| `--modo enlace\|servidor\|sin-servidor` | `enlace` (por defecto) es el más pequeño. Ver la tabla de modos |
| `--nivel H\|M\|L` | Corrección de errores. `H` es la más robusta; `L` da menos módulos |
| `--color uabc\|uabc-oscuro\|azul\|verde\|negro` | Color del QR, de la paleta institucional |
| `--publicar-en CARPETA` | Modo `servidor`: dónde dejar la página base |
| `--sin-comprimir` | No aplicar gzip: QR más grande (solo en modos con HTML dentro) |
| `--no-minificar` | Conservar el HTML tal cual |

El valor de `--html` no determina la URL del QR: esa es `URL_HTML`, la constante
de arriba del todo de `generar_qr.py`. Si cambias el archivo, cambia la
constante para que apunte al nuevo sitio.

Para usar otro documento:

```bash
python generar_qr.py --html mi/pagina.html --salida salida/mi-qr
```

## Presupuesto de bytes

Solo aplica a los modos que llevan el HTML **dentro** del QR (`servidor` y
`sin-servidor`). En modo `enlace` no hay presupuesto: lo único que cuenta es
la longitud de la URL, y son 69 bytes.

El QR más grande (versión 40) admite, en modo byte:

| Nivel | Corrección | Bytes de URL |
| --- | --- | --- |
| L | 7% | 2951 |
| M | 15% | 2327 |
| H | 30% | 1271 |

Y cada versión trae un salto grande de módulos, que es lo que más pesa:

| Versión | Módulos | Cabe en nivel L |
| --- | --- | --- |
| 4 | 33×33 | 78 |
| 8 | 49×49 | 242 |
| 30 | 137×137 | 1727 |
| 33 | 149×149 | 2063 |
| 38 | 169×169 | 2693 |

**En modo `servidor` el presupuesto real es 2065 bytes** (149×149, nivel L), y
se llega ahí sin margen: el HTML va comprimido con gzip y codificado en
base64url. Si añades contenido, mide con `generar_qr.py` antes de imprimir.

## Presupuesto de bytes

Este es el límite real del proyecto. El QR más grande (versión 40) admite:

| Nivel | Corrección | Bytes de URL |
| --- | --- | --- |
| L | 7% | 2953 |
| M | 15% | 2331 |
| H | 30% | 1273 |

Medido con esta QR, en modo byte (el que usa una URL en base64url):

| Versión | Módulos | Cabe en nivel L |
| --- | --- | --- |
| 30 | 137×137 | 1727 |
| 32 | 145×145 | 1949 |
| **33** | **149×149** | **2063** ← modo servidor, con 2065 bytes |
| 34 | 153×153 | 2183 |
| 38 | 169×169 | 2693 |

Nota: subir el nivel de corrección **no** reduce los módulos, al contrario:
`H` necesita más módulos para la misma información. Para menos cuadros, nivel
`L` y menos bytes.

El generador mide la URL **completa** y avisa antes de escribir nada. Se puede:

- Quitar texto innecesario y usar clases en vez de estilos inline
- Usar abreviaturas en los colores (`#f4d` en vez de `#ff44dd`)
- Reemplazar imágenes por CSS o SVG inline
- Subir a `L` si el documento es urgente

## Reglas para que el HTML sea autónomo

Todo lo que uses viaja dentro del QR, así que:

- **Sí**: CSS en un `<style>`, SVG inline, `data:` URIs, JavaScript inline
- **No**: `link` a hojas externas, `script src`, imágenes sueltas

El generador revisa esto y avisa si detecta recursos que se perderían.

> Esto aplica solo al documento que va **dentro** del QR. La página base
> (`croquis_base.html`) no tiene ninguna restricción: puede ser larga y
> legible. Lo único que tiene que caber en 2953 bytes es el fragmento.

## Pruebas

```bash
python test_qr.py
```

Verifica el ciclo completo: genera el QR, lo lee con **zxing-cpp** (la misma
librería que usan los lectores de móvil), decodifica el fragmento y confirma que
el HTML recuperado es idéntico al original.

La prueba `modo enlace: QR = URL` comprueba que el QR por defecto sea
exactamente la URL del HTML, sin fragmento ni `javascript:`, y que ese HTML
esté en el repo y sea autónomo (sin recursos externos). Sin eso, el QR podría
apuntar a un archivo que no abre nada.

`URL publicada responde` hace un GET a la URL real: si da 404, se puede
imprimir un QR que no abre nada. Se omite si no hay conexión.

`escaneo desde un movil` recorre el flujo del modo `servidor` (QR → página
base → documento) y que la base lea el fragmento y escuche `hashchange`.

Y `atributos sin comillas no se tragan` y `croquis con zonas coherentes` vigilan
dos fallos que **no dan error en la consola** pero dejan el croquis en negro o
vacío. Son la razón de que existan.

> OpenCV no sirve para esta comprobación: su detector falla a partir de la
> versión ~20 del QR, muy por debajo de lo que decodifica un teléfono.

## Estructura

```
generar_qr.py      Generador: mide, empaqueta y dibuja el QR
test_qr.py         Pruebas del ciclo completo
d.html             Página base, solo para el modo servidor
plantilla/
  croquis.html     El croquis interactivo (este es el que se publica)
  plantilla.html   Documento de ejemplo
  planos/          Croquis oficiales descargados (referencia)
salida/            QR generado
```

## El croquis de Mexicali

`plantilla/croquis.html` es un croquis interactivo del campus Mexicali. Tocar
un edificio hace zoom hacia él, lo resalta en naranja y muestra su ficha;
tocar el fondo vuelve a la vista general.

La geometría está trazada sobre el croquis oficial **"Mapa: Ubicación de
Edificios"** de la UABC (3 páginas, el mismo que reparten en automotores). Las
referencias originales quedaron en `plantilla/planos/`.

Nomenclatura del plano oficial, para cuando llegue el diseño de Illustrator:

| Zona | Edificio | | Zona | Edificio |
| --- | --- | --- | --- | --- |
| A | Fac. de Ingeniería | | E, E1 | Fac. de Arq. y Diseño |
| B | Anexo Centro de Evaluación | | F | Centro de Evaluación |
| 1, 2, 3, 4 | Fac. de Derecho | | I | Fac. de Idiomas |
| H | Fac. de Deportes | | J | Fac. de Pedagogía |
| L | Fac. de Ciencias Sociales y Políticas | | K | Fac. de Ciencias Administrativas |

Estas son las 6 zonas que hay ahora en el croquis:

| Sigla | Edificio | ¿Viene del plano? |
| --- | --- | --- |
| A | Fac. de Ingeniería | Sí |
| 1-4 | Fac. de Derecho | Sí, las 4 aulas del mismo bloque, agrupadas en una zona |
| E | Fac. de Arq. y Diseño | Sí |
| V | Investigación y Posgrado | Octogonal; el plano lo llama "Posgrado Vicerrectoría" y el técnico "Investigación y Posgrado" |
| T | Teatro | Rotulado en el mapa, no en la leyenda |
| BIB | Biblioteca | Rotulado en el mapa |

> **La Rectoria no está en este croquis, y no es un olvido.** El edificio de
> Rectoría de la UABC es el antiguo Palacio de Gobierno, en la Colonia Nueva,
> entre las avdas. Leyes de la Reforma y Sebastián Lerdo de Tejada. Está a unas
> calles del campus de Blvd. Benito Juárez 2500, no dentro. Se declaró
> Patrimonio Cultural de Baja California en 2022.

Calles del perímetro: Av. López Rayón (norte), Blvd. Benito Juárez (poniente),
Río Churubusco (oriente), Calle de la Normal (sur), Av. José A. Torres,
Av. Monclova, Río Mocrorito, Blvd. Río Nuevo.

Dirección del campus: Blvd. Benito Juárez 2500, Parcela 44, 21280 Mexicali, B.C.

### Por qué no están todos los edificios

El documento va comprimido en gzip dentro del QR, así que el presupuesto es
duro: **2953 bytes de URL en nivel L**. El croquis con las 9 zonas actuales
ocupa el 90% (versión 38, 169×169 módulos). Sacar del croquis lo que sí está
en el plano oficial es una decisión de bytes, no un olvido:

| Fuera | Motivo |
| --- | --- |
| Zonas B, F, E1 | Centro de Evaluación y su anexo: 3 edificios pequeños, poco uso en el croquis |
| Rótulos de las calles | 4 textos únicos que comprimían mal; las calles sí están dibujadas en el SVG |
| Estacionamientos G, H | Decorativos, no interactivos |
| Páginas 2 y 3 del plano | Son otro sector del campus (Pedagogía, Deportes, FCA) |

Para reincorporarlos, basta con añadir la entrada a `Z` y el nombre a `D`, y
medir con `generar_qr.py`. Si no cabe, `plantilla/planos/` tiene las tres
páginas para consultar las coordenadas.

### Al sustituir el SVG de Illustrator

El mapa se dibuja con JavaScript a partir de un solo array:

```javascript
var Z=[["A",654,599,115,106],["1-4",311,332,131,131],…];  // sigla x y ancho alto
```

`Z[i]` da `[sigla, x, y, ancho, alto]`. Con el SVG definitivo se reemplazan
esas cajas y nada más: el zoom, el encuadre y la ficha se calculan solos. Las
descripciones van aparte, en `D`, y ambas tienen que tener la misma longitud.

El zoom es un `transform` CSS sobre el `<g>` interior, no un `viewBox` animado:
así el navegador interpola solo y no hace falta ningún bucle de JavaScript.
Con `transform-box:view-box;transform-origin:0 0`, un `translate` en unidades
CSS equivale a unidades del dibujo, y `getScreenCTM()` del `<svg>` (que nunca se
transforma) dice cuántos píxeles mide una unidad.

## Nota sobre el minificador

`generar_qr.py` incluye un minificador propio para no depender de herramientas
externas. Conserva a propósito lo que suele romperse al comprimir:

- El contenido de `<style>`, `<script>`, `<pre>` y `<textarea>`
- Las comillas de los atributos con texto o manejadores (`onclick="f('a')"`)
- El doctype y el `charset`, sin los cuales el texto sale con acentos rotos

## Trampas del navegador que ya están resueltas

Están documentadas porque son fáciles de volver a tropezar al reescribir el
croquis o la página base:

- **`atob` solo acepta base64 estándar**, no base64url. Como el fragmento se
  genera con `-` y `_`, el decodificador los traduce a `+` y `/` antes de
  llamar a `atob`. Sin eso: `InvalidCharacterError`.
- **En SVG, `el.className = "x"` no hace nada**: es un `SVGAnimatedString` de
  solo lectura. Hay que usar `setAttribute("class", …)`, o el resaltado de la
  zona activa nunca se aplica.
- **Un `<svg>` sin `viewBox` no escala**: dibuja 1 unidad por píxel y se
  recorta. El `viewBox` va en el marcado, no sólo en el zoom por JavaScript.
- **Cambiar sólo el `#` no recarga el documento.** Por eso la página base
  escucha `hashchange`; si no, escanear un segundo QR con la página ya abierta
  la deja en blanco.
- **`document.write` se come la página base.** Hay que meter el documento en un
  `iframe` con `srcdoc`; si no, el aviso de error desaparece al primer escaneo
  correcto y no hay forma de mostrarlo después.
- **`overflow:hidden` en `html,body` de la página base**: con el iframe fijo, el
  padding del `body` desborda y aparece un scrollbar que no corresponde.
- **La URL completa ronda los 2100 caracteres** porque el fragmento va dentro.
  Chrome y Safari manejan esas longitudes, pero si un lector concreto se
  trunca, hay que bajar el documento (menos texto o menos zonas) y regenerar.
- **Un atributo HTML sin comillas se traga la `/` que cierra la etiqueta.**
  `fill=#16241c/>` se parsea como `fill="#16241c/"`, la etiqueta nunca se
  cierra y se traga todo el dibujo: el mapa sale negro y **sin ningún error en
  la consola**. Hay que dejar un espacio: `fill=#16241c />`. La prueba
  `atributos sin comillas no se tragan` lo vigila.
- **`.split()` aplicado a un texto concatenado con `+` solo afecta al último
  trozo.** `var Z="a"+"b".split(";")` deja `Z` como texto, no como array:
  `Z.length` da el número de caracteres, el bucle dibuja un grupo por carácter
  y todas las coordenadas salen `NaN`. Tampoco falla la consola. Por eso las
  zonas van en un **array literal**, que no tiene esa trampa.
- **`elemento.children` incluye los elementos del fondo.** Si el fondo y las
  zonas comparten `<g>`, los índices quedan desplazados y el resaltado se
  aplica al elemento equivocado. Hay que seleccionar solo las zonas.
- **Quitar comillas para ahorrar bytes es un arma de doble filo.** Ahorró 28
  bytes, pero provocó dos bugs silenciosos. Mide cada recorte.
