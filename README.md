# Orgullo Cimarron — QR que ejecuta HTML embebido

Un código QR que, al escanearlo en cualquier dispositivo, abre una página HTML
completa con transiciones y animaciones. Sin backend, sin que el móvil
descargue nada del servidor: el HTML viaja dentro del propio QR.

## La idea

Una URL puede llevar un **fragmento** (lo que va después del `#`). Los fragmentos
**nunca se envían al servidor**: el navegador hace el `GET` normal de la URL base
y luego usa el fragmento para construir el documento. Eso permite codificar un
HTML entero dentro del propio QR.

```
https://mi-sitio/pagina.html#H4sIAAAAA…
                            └─ el HTML viaja aquí ─┘
```

Al escanear, el lector abre esa dirección. La URL base es una página diminuta que
solo descomprime el fragmento, y el fragmento se convierte en el documento que
se muestra, con su CSS, sus animaciones y su JavaScript.

## Cómo se lee en un teléfono

El QR apunta a `URL_BASE` seguido de `#` y el fragmento. La página base es la
que se publica, y hace tres cosas:

1. Copia el fragmento de `location.hash` y traduce `-` y `_` a `+` y `/`, porque
   `atob` solo entiende el alfabeto base64 estándar.
2. Lo descomprime con `DecompressionStream('gzip')`.
3. Lo mete en un `<iframe>` con `srcdoc`.

Se usa un `iframe` y no `document.write` a propósito: `document.write` se
come la propia página base, así que el aviso de error desaparecería y un
segundo escaneo con la página ya abierta se quedaría en blanco. Con `iframe`
la base sigue viva, los errores se pueden mostrar y `hashchange` recarga.

## Publicar (obligatorio)

El modo por defecto es `servidor` y **no funciona hasta que publiques la página
base**. Genera el QR:

```bash
python generar_qr.py --html plantilla/croquis.html --salida salida/croquis --nivel L
```

 Luego sube `salida/croquis_base.html` a esa misma ruta y comprueba que abra en
el móvil antes de imprimir.

> **No uses `--modo sin-servidor` para imprimir.** Ese modo codifica una URL
> `javascript:`, y Chrome en Android y Safari en iOS la bloquean por seguridad:
> escanear el QR no haría nada. Está ahí solo para depurar en el escritorio.

Dónde publicarlo, todo gratis:

| Servicio | Cómo |
| --- | --- |
| **GitHub Pages** | Sube el repo, activa Pages desde la rama, cambia `URL_BASE` |
| **Netlify Drop** | Arrastra la carpeta, usa la URL que te den |
| **Cloudflare Pages** | Conecta el repo o sube la carpeta |

Si usas una URL larga, cambia `URL_BASE` en `generar_qr.py`: cada carácter de la
URL base ocupa bytes del QR.

## Uso

```bash
python generar_qr.py
```

Produce estos archivos en `salida/`:

| Archivo | Para qué sirve |
| --- | --- |
| `croquis.png` | El QR listo para imprimir o compartir |
| `croquis.svg` | El mismo QR como vector, para imprenta |
| `croquis_base.html` | **La página que hay que publicar** en `URL_BASE` |
| `croquis.html` | Copia del HTML minificado, para depurar |

Para usar otro documento:

```bash
python generar_qr.py --html mi/pagina.html --salida salida/mi-qr
```

Opciones útiles:

| Opción | Efecto |
| --- | --- |
| `--nivel L` / `M` / `H` | Corrección de errores. `L` cabe más (2953 bytes), `H` es el más compacto (1273) |
| `--url-base URL` | Dirección a la que apunta el QR. Debe ser donde publiques `croquis_base.html` |
| `--modo servidor\|sin-servidor` | `servidor` (por defecto) funciona en el móvil. `sin-servidor` solo para depurar |
| `--no-minificar` | Conserva el HTML tal cual, útil para leer la salida |
| `--sin-comprimir` | No aplicar gzip: sale un QR más grande pero sin comprimir |

El valor por defecto de `--url-base` está en `URL_BASE`, arriba de `generar_qr.py`.
Cámbialo ahí para notecordártelo en cada llamada, o pásalo por comando.

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

La prueba `escaneo desde un movil` es la que importa: comprueba el flujo real
de un teléfono (QR → URL http → página base → documento) y que la página base
lea el fragmento, escuche `hashchange` y avise de los errores. Si esa falla, el
QR no sirve para imprimir.

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

Estas son las 9 zonas que hay ahora en el croquis:

| Sigla | Edificio | ¿Viene del plano? |
| --- | --- | --- |
| A | Fac. de Ingeniería | Sí |
| 1, 2, 3, 4 | Fac. de Derecho | Sí (son 4 aulas del mismo bloque) |
| E | Fac. de Arq. y Diseño | Sí |
| V | Investigación y Posgrado | Octogonal; el plano lo llama "Posgrado Vicerrectoría" y el técnico "Investigación y Posgrado" |
| T | Teatro | Rotulado en el mapa, no en la leyenda |
| BIB | Biblioteca | Rotulado en el mapa |
| CC | Centro Comunitario | Rotulado en el mapa (fuera del croquis por bytes) |

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
- **La URL completa ronda los 2600 caracteres** porque el fragmento va dentro.
  Chrome y Safari manejan esas longitudes, pero si un lector concreto se
  trunca, hay que bajar el documento (menos texto o menos zonas) y regenerar.
