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

Las reglas no están escritas dos veces: viven en `editor/validar.py` y la
prueba las importa. Son las mismas que usa el editor para decidir si deja
guardar, así que no pueden separarse sin que salte una prueba.

`el croquis publicado no edita nada` es la que protege lo que ve el público:
comprueba que `croquis.html` no tenga ni formularios, ni `fetch`, ni
`localStorage`, ni nada que cargue código de fuera. `el editor rechaza lo
ajeno` levanta el servidor del editor en un puerto libre y le ataca con un
`Host` que no es localhost, con dos zonas solapadas y con un icono de un tipo
inventado: los tres tienen que rebotar, y el croquis no puede cambiar ni un
byte.

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
editor/            Herramienta de edición. NO se publica.
  editor.py        Servidor local: el único que puede escribir el croquis
  editor.html      La interfaz de edición
  validar.py       Las reglas, compartidas con las pruebas
  _respaldo/       Copia del croquis antes de cada guardado (fuera de git)
  iconos/          PNG de los iconos propios, para reutilizarlos (fuera de git)
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
| Tocar el botón del programa | Abre, en otra pestaña, el programa alojado en el ownCloud de la UABC |
| Tocar en cualquier parte | Vuelve a la vista general |

**Al tocar solo se hace zoom.** Las zonas son polígonos transparentes: existen
para recibir el toque, no para dibujar nada encima del arte. Un primer diseño
oscurecía el resto del mapa y contorneaba la zona activa; se quitó porque el
diseño de Illustrator ya se lee solo y cualquier adorno encima lo ensucia.

**El zoom se deshace tocando en cualquier parte.** Antes sólo servía tocar el
fondo, y eso casi nunca ocurría: al ampliar, la zona ocupa casi toda la
pantalla y no queda fondo donde pulsar.

### Las zonas

Las zonas y sus textos los define `ZONAS` en el propio `croquis.html`, y se
editan con el editor. La lista no se copia aquí a propósito: cambia cada vez
que se ajusta el mapa, y una copia acabaría mintiendo. El archivo es la única
fuente.

Las calles del perímetro sí se pueden anotar, porque vienen del dibujo y no
cambian: Calle Guillermo Prieto (norte), Av. Reforma (poniente),
Av. Sebastián Lerdo de Tejada (oriente) y Calle Julián Carrillo (sur).

### El botón del programa

Debajo de los accesos rápidos hay un botón que **sale del mapa**: el programa
del evento, alojado en el ownCloud de la UABC. Va aparte y con un filo que lo
separa de los chips porque es otra cosa: los chips llevan a una zona del mapa,
este lleva a otro sitio.

Abre en pestaña nueva para que la persona no pierda el mapa, y lleva el icono
de salir a otro sitio porque, sin esa pista, que el mapa no cambie al pulsar
desconcierta.

Es una etiqueta `<a>` escrita a mano en el HTML, no una zona ni un icono: el
editor no la toca. La prueba `el croquis publicado no edita nada` vigila que
los enlaces de salida no sean `javascript:` y que, si abren en pestaña nueva,
lleven `rel="noopener"`. Sin ese atributo, la página de destino puede
manipular la del mapa.

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
/* === INICIO ZONAS === */
var ZONAS = [
  ["Rectoría · Exposición CGECDC", "Rectoría",
   [[540,330],[788,330],[788,582],[540,582]],
   "La exposición del CGECDC, en el edificio de Rectoría."],
  …
];
/* === FIN ZONAS === */
```

Cada zona es `[nombre, nombre corto, polígono, descripción]`. La caja que se
encuadra al ampliar **no se guarda**: se calcula del polígono con `caja()`.
Tener las dos cosas era pedir que se desincronizaran, y de hecho pasó — al
ajustar los polígonos las cajas se quedaron viejas y el zoom dejaba parte de
la zona fuera de cuadro.

Los comentarios `INICIO`/`FIN` los usa el editor para saber qué trozo
reescribir. Se explican más abajo.

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
  solo y no hay JavaScript por fotograma. El `<g>` lleva `will-change:
  transform` para que el navegador lo tenga en su propia capa y no repinte el
  mapa entero en cada fotograma.
- **El panel no lleva desenfoque de fondo.** Tenía un `backdrop-filter` de
  14 px que se quitó: con el fondo al 97% de opacidad no se veía nada de lo de
  detrás, y en cambio obligaba a recalcular el desenfoque en *cada* fotograma
  del zoom, porque debajo hay un mapa moviéndose. Pagaba un precio alto por un
efecto invisible.
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

### Los iconos

Los símbolos de punto del mapa (baños, primeros auxilios, comida) van en un
array de objetos, uno por icono:

```javascript
/* === INICIO ICONOS === */
var ICONOS = [
  {"t": "bano", "x": 300, "y": 250, "n": "Baños junto al escenario", "i": ["Baños", "Los baños están junto al escenario."]},
  {"t": "estrella", "x": 500, "y": 400, "n": "Punto de interés", "s": 70, "r": -15, "a": "late"}
];
/* === FIN ICONOS === */
```

| Clave | Qué es | ¿Hace falta? |
| --- | --- | --- |
| `t` | El tipo: un símbolo de serie o un icono propio | Sí |
| `x`, `y` | Dónde va, en las coordenadas del mapa | Sí |
| `n` | El nombre que se lee al pasar el ratón | No |
| `s` | Lo que mide, de 16 a 160 unidades | No, 46 |
| `r` | El giro, en grados | No, 0 |
| `a` | La animación | No, ninguna |
| `c` | `0` para quitarle el círculo de fondo | No, lo lleva |
| `i` | `[título, texto]`: la ventana que sale al pulsarlo | No, y sin esto no se puede pulsar |

**Antes era una tupla posicional** y creció hasta siete campos, que es donde uno
empieza a contar comas con la vista. Con nombres, cada dato se lee solo, se
pueden dejar fuera los que no hacen falta y añadir uno nuevo no rompe los
iconos que ya había. El serializador escribe siempre el mismo orden y omite lo
vacío, así que un icono normal ocupa una línea corta y el diff de git enseña lo
que de verdad se tocó.

**El tamaño va en unidades del mapa, no en píxeles**: los iconos son parte del
plano y crecen con el zoom igual que las calles.

### Con círculo o sin él

Por defecto un icono lleva el círculo claro con filo detrás, que es lo que lo
despega del pasto. Se le puede quitar, y entonces se ve solo el dibujo.

**El `0` se comprueba con `in`, no por lo que vale.** Un `if (!ic.c)` tomaría el
`0` por ausencia y el círculo seguiría saliendo: es un valor legítimo, no un
«no está». Hay una prueba que vigila las tres partes —el servidor que lo
escribe, el croquis que lo lee y el editor que lo enseña— precisamente porque
es un fallo fácil de cometer en cualquiera de ellas.

Sin círculo, los símbolos vectoriales llevan un **halo blanco** alrededor del
trazo (`drop-shadow` en las cuatro direcciones, dos veces). El pasto es una
textura cargada y se come las líneas finas. A una imagen propia se le quita
además el recorte en círculo: si se quita el círculo, se quita entero, y una
foto sale como es. Media medida dejaría la imagen redonda sin nada que lo
explique.

**Los iconos no reciben el toque**, salvo los que llevan información. El grupo
va con `pointer-events: none`, que heredan los hijos, así que un icono plantado
en medio de un estacionamiento no se come esa parte del estacionamiento. Los
que llevan ventana se lo devuelven uno por uno: son pocos y pequeños, y a
cambio de un trozo mínimo de zona se puede consultar algo.

### Los modelos

Un **modelo** es un icono guardado entero —tipo, tamaño, giro, animación,
círculo e información— menos la posición. Se guarda desde el panel con
**Guardar como modelo**, aparece en la caja **Modelos** y al pulsarlo cada clic
en el mapa pone uno igual.

Es lo que hace que poner veinte puestos de comida iguales sean veinte clics y no
veinte veces de configurarlos a mano. En la lista se ve la miniatura con su
tamaño, su giro, su animación y su círculo de verdad, y debajo una nota corta
(`late · 70 · sin aro · info`) para saber qué lleva cada uno sin abrirlo.

Guardar con un nombre que ya existe **reemplaza** en vez de acumular: al volver
a guardar «Puesto de comida», el de antes pasa a ser el de ahora. Si se
acumularan, la lista se llenaría de variantes y no se sabría cuál es la buena.

**Los modelos no van dentro del croquis.** Viven en `editor/modelos.json`, que
está fuera de git como la biblioteca de imágenes. Son una herramienta de quien
edita, no contenido del mapa: el archivo publicado no los necesita y cada byte
suyo lo descarga un móvil por nada. El croquis solo lleva lo que se ve.

### Poner varios seguidos

Al pulsar un símbolo de la paleta o un modelo, el editor se queda **en modo
estampado**: cada clic en el mapa añade uno con esa configuración, y el modo no
se suelta hasta que se sale. Se sale con `Escape` o volviendo a pulsar lo mismo.

Antes se soltaba al primer clic, que está bien para poner uno y mal para poner
quince. Arrastrar, en cambio, sí estampa una sola vez y suelta: un arrastre es
una acción suelta, no un modo.

Mientras está puesto, la barra de arriba lo dice y el botón de la paleta queda
marcado, porque si no es fácil quedarse pulsando el mapa sin saber por qué sale
un icono cada vez.

### La ventana de información

Al pulsar un icono con `i` sale una ventana con su título y su texto. Es la
misma ventana para todos: se le cambia el contenido y se muestra, así que no
hay forma de que queden dos abiertas ni de que se acumulen en el DOM.

En el móvil se pega abajo y ocupa el ancho, en pantalla ancha sale centrada, y
en los dos casos lleva el mismo fondo, el mismo filo y el mismo verde que el
panel: se tiene que ver que es algo que se abre encima del mapa y no una
pantalla aparte.

Se cierra con el botón, tocando el fondo o con `Escape`. Empieza en `hidden`,
que además de esconderla la saca del alcance del teclado; y al cerrarse espera a
que acabe la transición antes de volver a esconderla, porque si no el fondo
seguiría interceptando el toque y el mapa dejaría de responder.

El toque sobre un icono **corta la propagación** en el `pointerdown`. Si no, el
`<svg>` lo recibiría también y además de abrir la ventana desharía el zoom por
detrás.

### Las animaciones

Hay cinco, y todas se mueven con `transform` y `opacidad`, que el navegador
compone sin repintar. Son suaves a propósito: esto es un mapa, no un anuncio.

| Nombre | Qué hace |
| --- | --- |
| `late` | El icono crece y vuelve, como un latido |
| `flota` | Sube y baja despacio |
| `gira` | Da vueltas despacio |
| `brilla` | Aparece y desaparece |
| `ondas` | Un anillo que se expande y se desvanece, como un radar |

**Se aplican a un `<g>` interior, nunca al que lleva la posición.** En SVG el
`transform` de CSS pisa al atributo `transform`, así que animar el grupo de
fuera borraría el `translate` que pone el icono en su sitio y todos se
apilarían en la esquina. Ese grupo interior lleva `transform-box: fill-box` y
`transform-origin: center` para que giren y latan sobre su propio centro.

Si el sistema pide menos movimiento (`prefers-reduced-motion`), se quedan
quietos.

### Los iconos propios

Además de los símbolos de serie se pueden usar imágenes propias. Van en otro
bloque, un diccionario de nombre a imagen:

```javascript
var PROPIOS = {
  "logo-facultad": "data:image/png;base64,iVBORw0KGgo…"
};
```

**Van incrustadas como data URL y no en un archivo aparte** porque el croquis
tiene que abrirse solo, sin pedirle nada a nadie: es lo que abre un QR escaneado
en la calle, y hay una prueba que vigila que no cargue nada de fuera. El precio
es que cada byte pesa dos veces, los datos y el texto base64, así que el editor
las guarda pequeñas: **160 px de lado** y en PNG.

Se dibujan recortadas en círculo, con un `clipPath` que vive en `<defs>`, para
que se lean como iconos del mapa y no como fotos pegadas encima. Como el aro ya
es redondo, una imagen cuadrada pierde un poco de las esquinas; el editor
enseña la vista previa con el recorte puesto para que se vea antes de guardar.

Los topes de peso están en `editor/validar.py`: 64 KB por imagen y 800 KB entre
todas. Con 160 px de lado no se llega ni de lejos, y los topes están para que un
descuido no convierta la página del móvil en algo que tarda en abrir.

#### La biblioteca

Cada imagen que se sube se guarda también en `editor/iconos/`, en PNG ya
recortado y reducido. Esa carpeta está fuera de git y es la despensa del
editor: al quitar un icono propio del croquis, la imagen **no se pierde**,
baja a la lista **Guardados** del panel y se vuelve a poner con un clic, sin
tener que buscarla otra vez en el disco.

El croquis sigue siendo la única fuente de lo que se publica: la biblioteca
solo sirve para no repetir el trabajo de subir y recortar.

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

Para mover zonas e iconos sin tocar las coordenadas a mano está el editor, que
es la sección siguiente.

## El editor

Mover once polígonos a mano sobre un archivo de 18 KB es una forma segura de
romper el croquis. `editor/` es una herramienta aparte para hacerlo con el
ratón, y es **lo único que puede modificar el mapa**.

```bash
python editor/editor.py
```

Abre el navegador en `http://127.0.0.1:8730/` y no necesita nada instalado más
allá de Python: el servidor es `http.server` de la biblioteca estándar y la
interfaz es un HTML suelto.

| Se puede hacer | Cómo |
| --- | --- |
| Mover una esquina | Arrastrar el punto blanco |
| Mover una zona entera | Arrastrar su interior |
| Mover con precisión | Flechas del teclado (con Mayús, de 10 en 10) |
| Añadir una esquina | Botón **Añadir vértice**, luego clic en el borde |
| Quitar una esquina | Doble clic sobre el punto, o `Supr` |
| Poner un icono | Arrastrarlo de la paleta al mapa, o pulsarlo y hacer clic |
| Ajustar su tamaño | El deslizador **Tamaño**; los nuevos salen con el que diga **Tamaño de los nuevos** |
| Girarlo | El deslizador **Giro**, o los botones de ±15° y ±90° |
| Animarlo | El desplegable **Animación** |
| Quitarle el círculo | La casilla **Con círculo de fondo** |
| Ponerle información | Los campos de **Información que sale al pulsarlo**; si se dejan vacíos, el icono no se puede pulsar |
| Guardar el icono entero | **Guardar como modelo** |
| Poner varios iguales | Pulsar el modelo en **Modelos** y hacer clic en el mapa todas las veces que haga falta |
| Crear un icono propio | **Subir una imagen…**; queda en la paleta con el borde discontinuo |
| Volver a poner uno guardado | Pulsarlo en **Guardados** |
| Quitar un icono propio | Pulsarlo en **En el croquis**; la imagen baja a **Guardados** |
| Alinear varios | Marcarlos con Mayús y usar **En fila**, **En columna** o **En rejilla** |
| Acercar | Rueda del ratón, o los botones **+** y **−** |

Abajo a la izquierda del mapa están las mismas instrucciones.

Una nota sobre las dos «Guardados» y «Modelos», que es fácil de confundir:

| | Qué guarda | Para qué |
| --- | --- | --- |
| **Guardados** | Una imagen (PNG) | Volver a poner un icono propio sin buscar el archivo |
| **Modelos** | Un icono configurado entero | Poner muchos iguales de un clic |

### Marcar varios iconos y alinearlos

Con **Mayús + clic** se van marcando iconos, y salen tres formas de colocarlos
de golpe. Se calculan a partir de donde están ahora: los iconos se ordenan
según su posición actual y se reparten parejos, así que el resultado es el que
uno espera sin tener que decir dónde va cada uno.

| Botón | Qué hace |
| --- | --- |
| **En fila** | Todos a la misma altura, repartidos en horizontal |
| **En columna** | Todos a la misma columna, repartidos en vertical |
| **En rejilla** | En cuadrícula, empezando por arriba a la izquierda |

El hueco entre uno y otro es el mayor entre el reparto exacto y lo que mide el
icono más grande de los marcados. Con eso casi nunca se tocan; si no caben, se
quedan pegados, que es mejor que meterlos donde no van. Al final se comprueba
que el grupo entero quepa en el mapa y, si se sale, se mete hacia dentro de una
pieza: mover uno solo deformaría la alineación recién hecha.

Los marcados también se mueven juntos: arrastrando uno se van todos, y las
flechas del teclado los mueven en bloque. Es la forma de cuadrar un grupo al
milímetro sin pelearse con el ratón.

Las marcas se guardan por posición, así que al borrar un icono se limpian y se
vuelven a poner: si no, quedarían corridas y marcarían a uno que no es.

### El zoom del editor

La rueda da un paso **continuo**, no un salto fijo por muesca: el factor sale
de `Math.exp(deltaY × 0.0016)`. Con un ratón, una muesca acerca un 17%; con un
trackpad, que manda decenas de eventos diminutos, acerca de forma suave. Antes
cada muesca multiplicaba por 1.18 y el resultado se veía a pasos.

Además, el zoom **no vuelve a dibujar el panel**: la rueda dispara decenas de
eventos por segundo y `dibuja()` reconstruye el mapa entero *y* las tres listas
de la derecha. Ahora el zoom solo toca lo que depende de la escala, que es el
`viewBox`, el radio de los tiradores y el tamaño de las etiquetas
(`reencuadra()`), y todo lo demás espera a que haya un cambio de verdad. Medido:
40 eventos de rueda pasaron de 40 redibujados completos a **un solo reencuadre**.

Los eventos se juntan y se aplican **una vez por fotograma**
(`requestAnimationFrame`), para que un trackpad que manda 100 eventos por
segundo no dispare 100 encuadres.

### Por qué el croquis público no puede editar nada

Es la razón de que esto sea un programa aparte y no un botón dentro del mapa.

El croquis que abre el QR es un HTML suelto en GitHub Pages: sin servidor, sin
backend y sin formularios. Quien lo escanea solo puede mirarlo, y una prueba
(`el croquis publicado no edita nada`) comprueba que siga siendo así.

El editor es lo contrario: escribe archivos y ejecuta `git push`. Por eso:

| Medida | Por qué |
| --- | --- |
| Escucha en `127.0.0.1`, no en `0.0.0.0` | Desde otro equipo de la red no se llega |
| Rechaza peticiones con `Host` que no sea localhost | Una web abierta en este equipo no puede apuntar un dominio a 127.0.0.1 y colarse por el navegador |
| No sirve archivos por ruta | Solo responde a las direcciones de una lista fija |
| Valida antes de escribir, y si algo falla no escribe nada | A medias sería peor: el croquis quedaría publicado con la mitad del cambio |
| `noindex` en la interfaz | Aunque acabe publicada, no aparece en buscadores |

Y si alguien llegara a abrir la interfaz del editor, no podría hacer nada: sin
el servidor local no hay quien reciba lo que edite. La interfaz sola no escribe
nada.

### Guardar y subir

**Guardar** valida y reescribe los bloques del croquis. Antes de tocar el
archivo deja una copia en `editor/_respaldo/croquis.html`, que está fuera de
git porque git ya guarda todas las versiones.

**Subir a GitHub** hace `git add -A`, `git commit` y `git push` con el mensaje
que se escriba. Si el push falla (la red, los permisos), el commit ya está
hecho y el aviso lo dice: se puede reintentar sin perder nada. Después hay que
esperar uno o dos minutos a que GitHub Pages reconstruya, y el QR ya abre la
versión nueva.

### Cómo reescribe el croquis

El croquis lleva marcadores alrededor de los dos bloques que el editor toca:

```javascript
/* === INICIO ZONAS === */
var ZONAS = [ … ];
/* === FIN ZONAS === */
```

Se usan marcadores y no expresiones regulares sobre el código porque el día
que alguien reformatee el archivo, una expresión regular falla en silencio o,
peor, se lleva por delante el bloque de al lado. **Esas dos líneas no se pueden
borrar**: sin ellas el editor avisa de que no sabe qué trozo reescribir, en vez
de estropear el croquis.

El contenido de los bloques es JavaScript, pero también es JSON válido: un
array de números y textos con comillas dobles. Así que se lee con `json.loads`
en vez de con expresiones regulares, y un error de sintaxis se convierte en un
mensaje claro en lugar de en un croquis a medias.

La paleta de iconos no lleva su propia copia de los dibujos: el servidor los
lee del bloque `SIMBOLOS` del croquis y se los manda a la interfaz. Lo que se
ve en la paleta es exactamente lo que el croquis va a dibujar.

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
- **Un cierre de más o de menos en el `<script>` deja la página en blanco.** No
  se dibujan ni las zonas ni los iconos, y lo único que sale es un
  `Unexpected token` en la consola del navegador. Pasó al añadir el círculo
  opcional: un `)` de más en una función de tres líneas tumbó el mapa entero.
  La prueba `el javascript cuadra` no valida JavaScript, cuenta cierres: no
  entiende la sintaxis, pero caza el error de tecleo que más veces deja estos
  archivos muertos, y lo caza antes de abrir el navegador.
- **Un `if` mal anidado deja código muerto que parece vivo.** Al partir la
  validación de un icono en una función aparte, las comprobaciones de después
  se quedaron con la indentación del bucle que ya no existía, o sea dentro de
  un `if` de tres líneas. El resultado: `revisar_iconos` no comprobaba **nada**
  y devolvía la lista vacía, así que el editor aceptaba cualquier cosa. Y la
  prueba que lo vigilaba seguía en verde, porque mandaba las zonas vacías: el
  guardado rebotaba por «no hay ninguna zona» y parecía que había rechazado el
  icono. Dos lecciones: la prueba tiene que comprobar **por qué** falla y no
  solo que falle, y las reglas compartidas necesitan una prueba que las llame
  directamente, sin pasar por el servidor.
- **`0` no es «no está».** El círculo se apaga con `"c": 0`, así que hay que
  comprobarlo con `"c" in ic` y nunca con `if ic.get("c")`, que tomaría el cero
  por ausencia y dejaría el círculo puesto. Lo mismo al leerlo en el croquis.
- **Un atributo HTML sin comillas se traga la `/` que cierra la etiqueta.**
  `fill=#16241c/>` se parsea como `fill="#16241c/"`, la etiqueta nunca se
  cierra y se traga todo el dibujo: el mapa sale negro y **sin ningún error en
  la consola**. Hay que dejar un espacio: `fill=#16241c />`. La prueba
  `atributos sin comillas no se tragan` lo vigila.
- **Y su hermano: cerrar la etiqueta sin cerrar antes la comilla del
  atributo.** Al escribir el `transform` de los iconos quedó
  `')><title>'` en vez de `')"><title>'`. Falta la comilla, así que el
  navegador se traga media etiqueta, el atributo se queda con basura dentro y
  el elemento no se dibuja. En el croquis eso deja el mapa sin iconos y solo
  se ve un error en la consola, que nadie mira. **Pasó dos veces.**
  La primera prueba que lo vigilaba miraba cada trozo entrecomillado por su
  cuenta, y no bastaba: los trozos van encadenados con `+`, y la comilla que
  falta puede estar al final de un trozo y el `>` al principio del siguiente,
  con lo que ninguno de los dos tiene el rastro completo. Ahora la prueba
  (`etiqueta sin comilla de cierre`) pega los trozos de cada `return` como los
  pegaría el navegador y mira el resultado. Comprobado que falla de verdad
  metiendo el fallo a mano.
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
