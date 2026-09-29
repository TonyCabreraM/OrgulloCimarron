# Orgullo Cimarrón — QR que abre el mapa del evento

Un código QR que, al escanearlo con cualquier dispositivo, abre el mapa
interactivo de la Rectoría de la UABC en Mexicali para el **Día del Orgullo
Cimarrón 2026**. Tocar una zona la amplía y muestra su ficha.

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

La identidad de la UABC es **verde y oro**, los colores del escudo. Los valores
de abajo salen de mirar el propio sitio `uabc.mx` y el escudo oficial, no de
suponerlos: el verde `#00723F` está en el escudo, en el manual y en el sitio, y
el oro `#DAB200` es uno de los colores de la paleta global del sitio.

Se elige con `--color`:

| Opción | Módulos | Contraste | Cuándo |
| --- | --- | --- | --- |
| `uabc` *(por defecto)* | `#00723F` | 6.04:1 color, 8.9:1 gris | El verde del escudo, el institucional |
| `verde-oscuro` | `#024731` | 10.78:1 color, 13.2:1 gris | Verde profundo, con más margen aún |
| `verde-claro` | `#007738` | 5.68:1 color, 8.6:1 gris | El verde más usado en el sitio |
| `azul` | `#204199` | 9.22:1 color, 10.2:1 gris | Azul para documentos administrativos |
| `negro` | `#231F20` | 16.30:1 | Negro tinta, el más seguro de todos |

**El oro no está en la lista, y es a propósito.** `#DAB200` es precioso como
acento pero clarísimo: sobre blanco da 2.03:1, muy por debajo del mínimo. En el
croquis se usa para la marca «UABC» sobre fondo oscuro, que es donde sí funciona
— igual que en el escudo, donde el oro es el campo y el verde el borde.

### Por qué el contraste se mide dos veces

Un lector de QR **termina binarizando la imagen**, así que lo que decide si
encuentra el código no es el color, sino cuántos píxeles se ven claros u
oscuros **en gris**. Por eso el generador mide las dos cosas:

```
Color            : uabc  (#00723F sobre #FFFFFF)
Contraste        : 6.04:1 en color, 8.86:1 en gris
```

La prueba `colores institucionales legibles` genera el QR con **todas las
paletas** y lo lee con zxing-cpp en cinco situaciones: normal, al 55% de tamaño,
con la mitad de contraste, con poca luz y en blanco y negro.

> **Sobre la suciedad:** si le pones un manchón grande encima, falla con
> cualquier color, incluido el negro. Eso no es culpa del color, es que el
> manchón tapa los patrones de referencia. El QR no se rompe, solo hay que
> limpiarlo.

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
| `--color uabc\|verde-oscuro\|verde-claro\|azul\|negro` | Color del QR, de la paleta institucional |
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

`croquis con zonas coherentes` merece un párrafo aparte, porque cubre cinco
cosas que se rompen calladas: que cada zona tenga sus cuatro campos, que su
polígono tenga al menos 3 puntos y 20 pt² de área, que quepa dentro del mapa,
que la descripción pase de 10 caracteres y que **ningún par de zonas se
solape**. Lo último se comprueba con el teorema de los ejes separadores, no
comparando cajas: dos bandas diagonales tienen cajas que se cruzan sin que los
polígonos se toquen, y comparar cajas daba falsos positivos. También verifica
que el `<image href>` apunte a un archivo que exista de verdad.

> OpenCV no sirve para esta comprobación: su detector falla a partir de la
> versión ~20 del QR, muy por debajo de lo que decodifica un teléfono.

## Estructura

```
Mapa Dia del Orgullo Cimarron 2026 VERSION 2.ai   Arte original de Illustrator
generar_qr.py      Generador: mide, empaqueta y dibuja el QR
test_qr.py         Pruebas del ciclo completo
d.html             Página base, solo para el modo servidor
plantilla/
  croquis.html     El mapa interactivo (este es el que se publica)
  rectoria.webp    El arte, en ráster: 3400 x 2200 px, ~0.50 MB
  plantilla.html   Documento de ejemplo
  planos/          Croquis del campus descargados (referencia vieja)
salida/            QR generado
```

## El croquis de la Rectoría

`plantilla/croquis.html` es el mapa interactivo del evento **Día del Orgullo
Cimarrón 2026**, en la Rectoría de la UABC en Mexicali. El arte es el mapa que
se hizo en Illustrator, no un dibujo generado por código.

| Acción | Resultado |
| --- | --- |
| Tocar una zona | Zoom hacia ella y la ficha muestra su nombre y su descripción |
| Tocar un acceso rápido del panel | Lo mismo, sin tener que acertarle a la zona en el mapa |
| Tocar en cualquier parte | Vuelve a la vista general |

**Al tocar solo se hace zoom.** Las zonas son polígonos transparentes: existen
para recibir el toque, no para dibujar nada encima del arte. Un primer diseño
oscurecía el resto del mapa y contorneaba la zona activa; se quitó porque el
diseño de Illustrator ya se lee solo y cualquier adorno encima lo ensucia.

**El zoom se deshace tocando en cualquier parte.** Antes sólo servía tocar el
fondo, y eso casi nunca ocurría: al ampliar, la zona ocupa casi toda la
pantalla y no queda fondo donde pulsar.

### Las 11 zonas

| Zona | Qué es |
| --- | --- |
| Teatro al aire libre | El foro del evento |
| Estacionamiento poniente | El más grande, sobre Av. Reforma |
| Estacionamiento oriente | Sobre Av. Sebastián Lerdo de Tejada |
| Zona recreativa | Descanso, en el paseo central |
| Estacionamiento invitado | Reservado para invitados |
| Rectoría · Exposición CGECDC | La exposición, dentro del edificio |
| Estacionamiento Norte 2 | Acceso por Calle Julián Carrillo |
| Stands de Unidades Académicas | Stands de las facultades |
| Estacionamiento Sur 2 | El más cercano a los stands |
| Stands de alimentos y bebidas | Puestos de comida y bebida |
| Entradas, escenario y servicios | Baños, primeros auxilios, escenario y las dos entradas |

Calles del perímetro: Calle Guillermo Prieto (norte), Av. Reforma (poniente),
Av. Sebastián Lerdo de Tejada (oriente) y Calle Julián Carrillo (sur).

### El arte viene de Illustrator

El original es `Mapa Dia del Orgullo Cimarron 2026 VERSION 2.ai`, en la raíz
del repo. Un `.ai` de Illustrator es un PDF por dentro, así que se abre con
PyMuPDF y se convierte a ráster:

| | |
| --- | --- |
| Tamaño de página | 1224 × 792 pt (432 × 279 mm), una sola página |
| Dibujos vectoriales | 142 443, unos 1 037 150 segmentos |
| Ráster que se publica | `plantilla/rectoria.webp`, 3400 × 2200 px, ~0.50 MB |

**Por qué un WebP y no el SVG.** Exportar el `.ai` a SVG da ~45 MB: el 73% del
archivo es la textura de pasto, repetida en miles de trazados diminutos.
Ningún teléfono va a bajar eso al escanear un QR. El WebP conserva el dibujo a
resolución de sobra (3400 px de ancho para una pantalla de 400) y pesa 90
veces menos.

**El texto del mapa son contornos, no texto.** Al convertir las tipografías,
los rótulos dejaron de ser texto extraíble: la única cadena legible en el PDF
es «Zona recreativa». Por eso los nombres de las zonas viven en `croquis.html`
y no se pueden leer del `.ai`.

### Cómo está armado el HTML

El mapa se dibuja con un `<image>` dentro de un `<svg viewBox="0 0 1224 792">`,
en el mismo sistema de coordenadas que el archivo de Illustrator. Así los
números de `ZONAS` se leen directamente sobre el `.ai`.

```javascript
var ZONAS = [
  ["Rectoría · Exposición CGECDC", "Rectoría",
   [[540,330],[788,330],[788,582],[540,582]],
   "La exposición del CGECDC, en el edificio de Rectoría."],
  …
];
```

Cada zona es `[nombre, nombre corto, polígono, descripción]`. La caja que se
encuadra al ampliar **no se guarda**: se calcula del polígono con `caja()`.
Tener las dos cosas era pedir que se desincronizaran, y de hecho pasó — al
ajustar los polígonos las cajas se quedaron viejas y el zoom dejaba parte de
la zona fuera de cuadro.

- **Las bandas diagonales van como cuadriláteros**, no como rectángulos. Los
  estacionamientos y las hileras de stands están inclinados en el dibujo; un
  rectángulo normal que los cubriera incluiría medio prado al lado.
- **Dos zonas no pueden solaparse.** Al tocar caería la de encima y la otra
  quedaría inalcanzable justo ahí. Hay una prueba que lo comprueba con el
  teorema de los ejes separadores, y otra que verifica que todas quepan en el
  mapa.
- **El encuadre se calcula en JavaScript**, no se deja al `viewBox`: el mapa se
  centra y se amplía dentro del hueco libre que dejan el encabezado y el panel,
  midiéndolos con `getBoundingClientRect()`. Dejar el encuadre al `viewBox`
  hacía que el mapa quedara pequeño y que el panel tapara las zonas del borde.
- **El zoom es un `transform` CSS** sobre el `<g>` interior con una
  `transition`, no un bucle que anima el `viewBox`: el navegador lo interpola
  solo y no hay JavaScript por fotograma.
- **El panel es barra inferior en vertical y lateral en apaisado**
  (`@media (min-width:760px) and (orientation:landscape)`). En pantalla ancha
  una barra inferior desperdicia el ancho y deja el mapa chico y centrado.
- **Accesos rápidos**: los botones del panel. El mapa es apaisado y en un móvil
  vertical queda chico, así que tocar una banda diagonal con el dedo es difícil;
  el panel sirve para navegar además de para informar.

> **El croquis no cabe dentro del QR.** Pesa unos 12 KB más 0.50 MB de imagen,
> y los modos que embeben el documento (`servidor` y `sin-servidor`) admiten
> ~2950 bytes de URL. Por eso el modo por defecto es `enlace`, que lleva
> únicamente la dirección del HTML. La prueba `QR actual decodificable` usa
> `plantilla/plantilla.html` para verificar el mecanismo, no este documento.

### Al reemplazar el mapa por una versión nueva

Se sustituyen dos cosas y nada más:

1. `plantilla/rectoria.webp` — el ráster nuevo, siempre a 1224 × 792 de
   proporción (si cambia el tamaño de página, hay que cambiar el `viewBox`).
2. Los polígonos de `ZONAS` — las coordenadas en puntos, leídas sobre el `.ai`.

El zoom, el encuadre y la ficha se calculan solos. La prueba
`croquis con zonas coherentes` revisa que cada zona tenga los cuatro campos,
que quepa en el mapa, que su polígono tenga al menos 3 puntos y 20 pt² de
área, que la descripción pase de 10 caracteres, que ningún par de zonas se
solape y que el `<image href>` apunte a un archivo que exista.

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
  solo lectura. Hay que usar `setAttribute("class", …)` o `classList`, o la
  clase nunca se aplica y el elemento no cambia de aspecto.
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
  zonas comparten `<g>`, los índices quedan desplazados y el toque activa la
  zona equivocada. Por eso el código busca con `querySelectorAll(".g")`, que
  selecciona solo las zonas, y no con `children`.
- **Quitar comillas para ahorrar bytes es un arma de doble filo.** Ahorró 28
  bytes, pero provocó dos bugs silenciosos. Mide cada recorte.
- **`getScreenCTM()` tiene dos escalas distintas:** `a` para el eje X y `d` para
  el Y. Usar `a` en el eje Y hace que la zona salga descentrada al ampliar.
- **Centrar en el `svg` entero no basta si hay una ficha encima.** El centro
  útil es el del área que deja la ficha: `(alto - altoFicha) / 2`. Si no, la
  zona queda medio tapada.
- **En un zoom, "tocar el fondo para volver" casi nunca funciona**, porque la
  zona ampliada ocupa la pantalla entera. La condición correcta es mirar si ya
  hay una zona activa, no si el toque cayó en el fondo.
- **`getBoundingClientRect()` durante una transición devuelve la posición
  intermedia, no la final.** Medir justo después de disparar la animación da
  números falsos: parece que las zonas se salen de la pantalla cuando en
  realidad todavía van en camino. Hay que esperar a que la transición termine
  (0.65s aquí) antes de medir.
