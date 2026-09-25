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
salida/            Resultados generados
```

## Nota sobre el minificador

`generar_qr.py` incluye un minificador propio para no depender de herramientas
externas. Conserva a propósito lo que suele romperse al comprimir:

- El contenido de `<style>`, `<script>`, `<pre>` y `<textarea>`
- Las comillas de los atributos con texto o manejadores (`onclick="f('a')"`)
- El doctype y el `charset`, sin los cuales el texto sale con acentos rotos
