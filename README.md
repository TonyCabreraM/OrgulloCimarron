# Orgullo Cimarron — QR que ejecuta HTML sin servidor

Un código QR que, al escanearlo en cualquier dispositivo, abre una página HTML
completa con transiciones y animaciones. Sin hosting, sin backend, sin que el
móvil descargue nada del servidor.

## La idea

Una URL puede llevar un **fragmento** (lo que va después del `#`). Los fragmentos
**nunca se envían al servidor**: el navegador hace el `GET` normal de la URL base
y luego usa el fragmento para construir el documento. Eso permite codificar un
HTML entero dentro del propio QR.

```
https://mi-sitio/pagina.html#PD94bWwgTGVzPC9odG1sPjwvc3R5bGU+…
                            └──── el HTML viaja aquí ────┘
```

Al escanear, el lector abre esa dirección. La URL base responde algo simple, y
el fragmento se convierte en el documento que se muestra, con su CSS, sus
animaciones y su JavaScript.

## Uso

```bash
python generar_qr.py
```

Produce tres archivos en `salida/`:

| Archivo | Para que sirve |
| --- | --- |
| `orgullo.png` | El QR listo para imprimir o compartir |
| `orgullo.svg` | El mismo QR como vector, para imprenta |
| `orgullo.html` | Copia del HTML minificado, para depurar o publicar |

Para usar otro documento:

```bash
python generar_qr.py --html mi/pagina.html --salida salida/mi-qr
```

Opciones útiles:

| Opción | Efecto |
| --- | --- |
| `--nivel L` / `M` / `H` | Corrección de errores. `L` cabe más (2953 bytes), `H` es el más compacto (1273) |
| `--url-base URL` | Dirección a la que apunta el QR. Por defecto `https://x.to/a`, un ejemplo que debes cambiar por la tuya |
| `--no-minificar` | Conserva el HTML tal cual, útil para leer la salida |

## Publicar la URL base

Antes de generar un QR usable, cambia la URL base por una tuya real:

```bash
python generar_qr.py --url-base https://usuario.github.io/OrgulloCimarron/
```

El QR apunta a esa dirección, que debe existir y ser accesible. Opciones gratuitas:

- **GitHub Pages**: publica el repositorio y usa `https://usuario.github.io/repositorio/`
- **Netlify Drop**: arrastra la carpeta y obtienes una URL en segundos
- **Cloudflare Pages**, **Vercel** o cualquier hosting estático

Da igual lo que devuelva esa página: el contenido que ve el usuario viene del
fragmento del QR.

## Presupuesto de bytes

Este es el límite real del proyecto. El QR más grande (versión 40) admite:

| Nivel | Corrección | Bytes de URL |
| --- | --- | --- |
| L | 7% | 2953 |
| M | 15% | 2331 |
| H | 30% | 1273 |

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

## Pruebas

```bash
python test_qr.py
```

Verifica el ciclo completo: genera el QR, lo lee con **zxing-cpp** (la misma
librería que usan los lectores de móvil), decodifica el fragmento y confirma que
el HTML recuperado es idéntico al original.

> OpenCV no sirve para esta comprobación: su detector falla a partir de la
> versión ~20 del QR, muy por debajo de lo que decodifica un teléfono.

## Estructura

```
generar_qr.py      Generador: minifica, empaqueta y dibuja el QR
test_qr.py         Pruebas del ciclo completo
plantilla/
  plantilla.html   Documento de ejemplo, aquí se edita
  croquis.html     Croquis interactivo del campus Mexicali
  planos/          Croquis oficiales descargados (referencia)
salida/            Resultados generados
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

Calles del perímetro: Av. López Rayón (norte), Blvd. Benito Juárez (poniente),
Río Churubusco (oriente), Calle de la Normal (sur), Av. José A. Torres,
Av. Monclova, Río Mocrorito, Blvd. Río Nuevo.

Dirección del campus: Blvd. Benito Juárez 2500, Parcela 44, 21280 Mexicali, B.C.

### Por qué no están todos los edificios

El documento va comprimido en gzip dentro del QR, así que el presupuesto es
duro: **2953 bytes de URL en nivel L**. El croquis con las 10 zonas actuales
ocupa el 97%. Sacar del croquis lo que sí está en el plano oficial es una
decisión de bytes, no un olvido:

| Fuera | Motivo |
| --- | --- |
| Zonas B, F, E1 | Centro de Evaluación y su anexo: 3 edificios pequeños, poco uso en el croquis |
| Rótulos de las calles | 4 textos únicos que comprimían mal; las calles sí están dibujadas en el SVG |
| Estacionamientos G, H | Decorativos, no interactivos |
| Páginas 2 y 3 del plano | Son otro sector del campus (Pedagogía, Deportes, FCA) |

Para reincorporarlos, basta con añadir la entrada a `BZ` y el nombre a `NM` y
`DS`, y medir con `generar_qr.py`. Si no cabe, `plantilla/planos/` tiene las
tres páginas para consultar las coordenadas.

### Al sustituir el SVG de Illustrator

El mapa se dibuja con JavaScript a partir de un solo array:

```javascript
var BZ = "A 654 599 115 106;1 311 628 131 39;…";  // sigla x y ancho alto
```

`BZ[i].split(" ")` da `[sigla, x, y, ancho, alto]`. Con el SVG definitivo se
reemplazan esas cajas y nada más: el zoom, el encuadre y la ficha se calculan
solos.

> Ojo: `BZ` es un **texto**, hay que partirlo con `BZ.split(";")` antes de
> recorrerlo. Iterar `BZ` directamente recorre caracteres sueltos y todas las
> coordenadas salen `NaN`.

## Nota sobre el minificador

`generar_qr.py` incluye un minificador propio para no depender de herramientas
externas. Conserva a propósito lo que suele romperse al comprimir:

- El contenido de `<style>`, `<script>`, `<pre>` y `<textarea>`
- Las comillas de los atributos con texto o manejadores (`onclick="f('a')"`)
- El doctype y el `charset`, sin los cuales el texto sale con acentos rotos

## Trampas del navegador que ya están resueltas

Están documentadas porque son fáciles de volver a tropezar al reescribir el
croquis:

- **`atob` solo acepta base64 estándar**, no base64url. Como el fragmento se
  genera con `-` y `_`, el decodificador los traduce a `+` y `/` antes de
  llamar a `atob`. Sin eso: `InvalidCharacterError`.
- **En SVG, `el.className = "x"` no hace nada**: es un `SVGAnimatedString` de
  solo lectura. Hay que usar `setAttribute("class", …)`, o el resaltado de la
  zona activa nunca se aplica.
- **Un `<svg>` sin `viewBox` no escala**: dibuja 1 unidad por píxel y se
  recorta. El `viewBox` va en el marcado, no sólo en el zoom por JavaScript.
