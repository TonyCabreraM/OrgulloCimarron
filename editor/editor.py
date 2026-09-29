# -*- coding: utf-8 -*-
"""
Editor local del croquis. Es el unico que puede modificar el mapa.

POR QUE EXISTE ESTE ARCHIVO
---------------------------
El croquis que se publica en GitHub Pages es un HTML suelto, sin servidor y
sin backend: quien lo abre solo puede mirarlo. Eso no se toca. Lo que hace
falta es una herramienta aparte, para la persona que organiza el evento, que
pueda mover las zonas y los iconos sin editar el HTML a mano.

Esta es esa herramienta, y vive en tu maquina:

  - Escucha solo en 127.0.0.1, no en la red. Desde otro equipo no se llega.
  - Rechaza las peticiones cuyo Host no sea localhost, para que una pagina
    web abierta en este equipo no pueda apuntar un dominio a 127.0.0.1 y
    colarse por el navegador.
  - No sirve archivos por ruta: solo responde a las direcciones de la lista.
  - Nada de esto se sube a GitHub Pages. Lo que se publica es croquis.html,
    que es solo lectura.

Si el archivo del editor acabara publicado por accidente, no pasaria nada
grave: no puede escribir en el croquis sin este servidor, y el servidor solo
existe mientras tu lo tengas abierto.

USO
---
    python editor/editor.py            (abre el navegador solo)
    python editor/editor.py --no-abrir
    python editor/editor.py --puerto 8730
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CROQUIS = RAIZ / "plantilla" / "croquis.html"
MAPA = RAIZ / "plantilla" / "rectoria.webp"
EDITOR_HTML = Path(__file__).resolve().parent / "editor.html"
RESPALDO = Path(__file__).resolve().parent / "_respaldo"

# validar.py vive junto a este archivo, pero cuando el proyecto se importa
# desde fuera (test_qr.py lo hace) el paquete se llama editor. Se admiten las
# dos formas para que funcione igual ejecutado que importado.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validar import (  # noqa: E402  (va despues del sys.path a proposito)
    ALTO,
    ANCHO,
    SIMBOLOS,
    revisar,
)

HOSTS_LOCALES = {"127.0.0.1", "localhost", "::1", "[::1]"}


class ErrorEditor(Exception):
    """Un problema que se le puede contar a quien esta usando el editor."""


# ---------------------------------------------------------------------------
# Lectura y escritura del croquis
# ---------------------------------------------------------------------------
# El croquis lleva marcadores alrededor de los dos bloques que el editor
# reescribe. Se usan marcadores y no expresiones regulares sobre el codigo
# porque el dia que alguien reformatee el archivo, una expresion regular
# falla en silencio o, peor, se lleva por delante el bloque de al lado.
def _marcadores(nombre: str) -> tuple[str, str]:
    return f"/* === INICIO {nombre} === */", f"/* === FIN {nombre} === */"


def _tramos(texto: str, nombre: str) -> tuple[int, int, str]:
    """Posicion del bloque y su contenido, marcadores aparte."""
    ini, fin = _marcadores(nombre)
    a = texto.find(ini)
    b = texto.find(fin)
    if a < 0 or b < 0:
        raise ErrorEditor(
            f"No encuentro los marcadores de {nombre} en {CROQUIS.name}.\n"
            f"Tienen que estar estas dos lineas, y no se pueden borrar:\n"
            f"    {ini}\n    {fin}")
    if b < a:
        raise ErrorEditor(f"Los marcadores de {nombre} estan al reves.")
    return a, b, texto[a + len(ini):b]


def _valor(cuerpo: str, nombre: str):
    """El array de dentro del bloque, leido como JSON.

    El bloque es JavaScript, pero un array de numeros y textos con comillas
    dobles es JSON valido, asi que se lee con json en vez de con expresiones
    regulares. Un fallo de sintaxis aqui se convierte en un mensaje claro en
    lugar de en un croquis a medias.
    """
    a, b = cuerpo.find("["), cuerpo.rfind("]")
    if a < 0 or b < a:
        raise ErrorEditor(f"El bloque de {nombre} no tiene ningun array dentro.")
    try:
        return json.loads(cuerpo[a:b + 1])
    except json.JSONDecodeError as e:
        raise ErrorEditor(
            f"El bloque de {nombre} no se puede leer como JSON: {e}.\n"
            f"Si lo has editado a mano, revisa comas y comillas.") from None


def leer_croquis() -> dict:
    """Las zonas, los iconos y el encuadre por defecto que hay ahora mismo."""
    if not CROQUIS.is_file():
        raise ErrorEditor(f"No existe {CROQUIS}.")
    texto = CROQUIS.read_text(encoding="utf-8")
    _, _, cuerpo_zonas = _tramos(texto, "ZONAS")
    _, _, cuerpo_iconos = _tramos(texto, "ICONOS")
    vista = re.search(r"var VISTA = \[([-\d,\s]+)\]", texto)
    mapa = re.search(r'<image[^>]+href="([^"]+)"', texto)
    return {
        "zonas": _valor(cuerpo_zonas, "ZONAS"),
        "iconos": _valor(cuerpo_iconos, "ICONOS"),
        "vista": [int(v) for v in vista.group(1).split(",")] if vista else [0, 0, ANCHO, ALTO],
        "mapa": mapa.group(1) if mapa else "rectoria.webp",
    }


def formas_simbolos() -> dict:
    """Las formas SVG de los iconos, leidas del propio croquis.

    El editor dibuja la paleta con esto y no con una copia propia, para que no
    haya dos listas de iconos: lo que se ve en la paleta es exactamente lo que
    el croquis va a dibujar.

    Los simbolos estan escritos como trozos de texto encadenados con +, para
    que las lineas no se hagan kilometricas. Aqui se vuelven a pegar. Si
    alguien reformatea ese bloque y la lectura falla, se avisa en vez de
    dejar la paleta vacia sin decir por que.
    """
    texto = CROQUIS.read_text(encoding="utf-8")
    _, _, cuerpo = _tramos(texto, "SIMBOLOS")
    formas = {}
    for clave, trozos in re.findall(
            r"^\s*(\w+):\s*((?:\s*'[^']*'\s*\+?)+)", cuerpo, flags=re.M):
        formas[clave] = "".join(re.findall(r"'([^']*)'", trozos))
    if not formas:
        raise ErrorEditor(
            "No se pudo leer ningun simbolo del bloque SIMBOLOS de croquis.html.\n"
            "Cada uno tiene que verse asi, en una linea que empiece por su nombre:\n"
            "    bano: '<circle .../>' + '<path .../>',")
    return formas


def tipos_coinciden(formas: dict) -> list[str]:
    """Avisa si la lista de simbolos del croquis y la de validar.py se separaron.

    Son dos listas que tienen que decir lo mismo: validar.py decide que tipos
    se pueden guardar y croquis.html sabe dibujarlos. Si se separan, se puede
    guardar un icono que luego no se dibuja, y eso no da ningun error.
    """
    faltan_en_croquis = sorted(set(SIMBOLOS) - set(formas))
    sobran_en_croquis = sorted(set(formas) - set(SIMBOLOS))
    avisos = []
    if faltan_en_croquis:
        avisos.append(
            "Estos tipos estan en editor/validar.py pero el croquis no sabe "
            "dibujarlos: " + ", ".join(faltan_en_croquis))
    if sobran_en_croquis:
        avisos.append(
            "El croquis dibuja estos tipos, pero validar.py no deja usarlos: "
            + ", ".join(sobran_en_croquis))
    return avisos


def _n(v) -> str:
    return str(int(round(float(v))))


def _texto_zonas(zonas: list) -> str:
    """El array de zonas, formateado como estaba: una zona por parrafo.

    Los puntos van pegados con coma y sin espacio ([[330,108],[592,108]], no
    [[330,108], [592,108]]) para que al guardar sin mover una zona su linea no
    cambie y el diff de git ensene solo lo que de verdad se toco.
    """
    trozos = []
    for nombre, corto, poligono, desc in zonas:
        pts = ",".join(f"[{_n(x)},{_n(y)}]" for x, y in poligono)
        trozos.append(
            f"  [{json.dumps(nombre, ensure_ascii=False)}, "
            f"{json.dumps(corto, ensure_ascii=False)},\n"
            f"   [{pts}],\n"
            f"   {json.dumps(desc, ensure_ascii=False)}]")
    return "var ZONAS = [\n" + ",\n\n".join(trozos) + "\n];"


def _texto_iconos(iconos: list) -> str:
    if not iconos:
        return "var ICONOS = [];"
    trozos = [
        f"  [{json.dumps(t, ensure_ascii=False)}, {_n(x)}, {_n(y)}, "
        f"{json.dumps(e, ensure_ascii=False)}]"
        for t, x, y, e in iconos]
    return "var ICONOS = [\n" + ",\n".join(trozos) + "\n];"


def guardar_croquis(zonas: list, iconos: list) -> dict:
    """Valida y escribe las zonas y los iconos. Deja una copia de seguridad.

    Si algo no cuadra no se escribe NADA: ni las zonas, ni los iconos. A
    medias seria peor que no escribir, porque el croquis quedaria publicado
    con la mitad del cambio y sin forma de saber cual falta.
    """
    problemas = revisar(zonas, iconos)
    if problemas:
        raise ErrorEditor("\n".join(problemas))

    texto = CROQUIS.read_text(encoding="utf-8")

    # Una copia antes de tocar nada. Git ya es un respaldo, pero esta esta a
    # mano y no hay que saber git para encontrarla.
    RESPALDO.mkdir(exist_ok=True)
    (RESPALDO / "croquis.html").write_text(texto, encoding="utf-8")

    for nombre, cuerpo in (("ZONAS", _texto_zonas(zonas)), ("ICONOS", _texto_iconos(iconos))):
        a, b, _ = _tramos(texto, nombre)
        ini, fin = _marcadores(nombre)
        texto = texto[:a] + ini + "\n" + cuerpo + "\n" + fin + texto[b + len(fin):]

    CROQUIS.write_text(texto, encoding="utf-8")
    return {"zonas": len(zonas), "iconos": len(iconos)}


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
def git(*argumentos: str) -> subprocess.CompletedProcess:
    """Ejecuta git en la raiz del proyecto."""
    return subprocess.run(
        ["git", *argumentos], cwd=str(RAIZ), capture_output=True,
        text=True, encoding="utf-8", errors="replace")


def _salida(r: subprocess.CompletedProcess) -> str:
    return ((r.stdout or "") + (r.stderr or "")).strip()


def estado_git() -> dict:
    """Lo que hace falta para el boton de subir: rama, pendientes y si hay git."""
    if not shutil.which("git"):
        return {"hay": False, "error": "git no esta instalado o no esta en el PATH"}
    if not (RAIZ / ".git").is_dir():
        return {"hay": False, "error": f"{RAIZ} no es un repositorio de git"}

    rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if rama.returncode != 0:
        return {"hay": False, "error": _salida(rama)}

    pendientes = git("status", "--porcelain")
    delante = git("rev-list", "--count", "@{u}..HEAD")
    detras = git("rev-list", "--count", "HEAD..@{u}")
    siguiente = git("log", "-1", "--pretty=%s")
    return {
        "hay": True,
        "rama": (rama.stdout or "").strip(),
        "pendientes": len([l for l in (pendientes.stdout or "").splitlines() if l.strip()]),
        "sinSubir": int((delante.stdout or "0").strip() or 0),
        "sinBajar": int((detras.stdout or "0").strip() or 0),
        "ultimo": (siguiente.stdout or "").strip(),
        "detalle": (pendientes.stdout or "").strip(),
    }


def subir(mensaje: str) -> dict:
    """git add, commit y push. Cuenta lo que paso en cada paso.

    El push se hace aqui y no se deja para despues porque es justo lo que se
    pidio: que al guardar desde el editor la pagina publicada quede al dia.
    Si el push falla (red, permisos), el commit local ya esta hecho y se
    puede reintentar sin perder nada.
    """
    pasos = []
    cambios = git("status", "--porcelain")
    if not (cambios.stdout or "").strip():
        return {"ok": True, "pasos": pasos,
                "mensaje": "No hay nada que subir: el repositorio esta limpio."}

    anadir = git("add", "-A")
    pasos.append(("git add -A", _salida(anadir) or "ok"))
    if anadir.returncode != 0:
        return {"ok": False, "pasos": pasos, "mensaje": "No se pudo preparar el cambio."}

    commit = git("commit", "-m", mensaje)
    pasos.append(("git commit", _salida(commit) or "ok"))
    if commit.returncode != 0:
        return {"ok": False, "pasos": pasos,
                "mensaje": "El commit fallo. Arriba esta lo que dijo git."}

    push = git("push")
    pasos.append(("git push", _salida(push) or "ok"))
    if push.returncode != 0:
        return {"ok": False, "pasos": pasos, "commitHecho": True,
                "mensaje": "El commit quedo hecho, pero el push no subio.\n"
                           "El cambio esta a salvo en tu equipo: vuelve a "
                           "pulsar Subir para reintentarlo."}

    return {"ok": True, "pasos": pasos, "commitHecho": True,
            "mensaje": "Subido. GitHub Pages tarda uno o dos minutos en "
                       "reconstruir; despues el QR ya abre la version nueva."}


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
class Manejador(BaseHTTPRequestHandler):
    server_version = "EditorCroquis"

    def log_message(self, formato: str, *args) -> None:  # noqa: A003
        # El log por defecto llena la consola de cada imagen y cada sondeo.
        # Solo interesa lo que el usuario provoca.
        if self.path.startswith("/api/") and not self.path.endswith("/estado"):
            sys.stderr.write(f"  {self.command} {self.path}\n")

    # -- utilidades ---------------------------------------------------------
    def _host_local(self) -> bool:
        """Solo se atiende a quien llame por localhost.

        Sin esto, una pagina web abierta en este equipo puede apuntar un
        dominio propio a 127.0.0.1 y usar el navegador como puente para
        escribir en el croquis. El Host delata el intento: llegaria con el
        nombre del dominio, no con localhost.
        """
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in HOSTS_LOCALES

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, datos, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self._responder(codigo, cuerpo, "application/json; charset=utf-8")

    def _error(self, mensaje: str, codigo: int = 400) -> None:
        self._json({"ok": False, "mensaje": mensaje}, codigo)

    def _archivo(self, ruta: Path, tipo: str) -> None:
        if not ruta.is_file():
            self._error(f"No existe {ruta.name} en el proyecto.", 404)
            return
        self._responder(200, ruta.read_bytes(), tipo)

    def _cuerpo_json(self) -> dict:
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErrorEditor("Content-Length ilegible.") from None
        if largo <= 0 or largo > 4_000_000:
            raise ErrorEditor("El cuerpo de la peticion no tiene un tamano razonable.")
        crudo = self.rfile.read(largo)
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ErrorEditor(f"El cuerpo no es JSON valido: {e}") from None

    # -- rutas --------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_local():
            self._error("Esta herramienta solo atiende desde localhost.", 403)
            return
        ruta = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if ruta in ("/", "/editor.html"):
                self._archivo(EDITOR_HTML, "text/html; charset=utf-8")
            elif ruta == "/mapa":
                # La misma imagen que usa el croquis publicado. Se sirve desde
                # aqui y no desde la web para poder trabajar sin conexion y
                # para no depender de que Pages ya haya reconstruido.
                self._archivo(MAPA, "image/webp")
            elif ruta == "/api/estado":
                datos = leer_croquis()
                formas = formas_simbolos()
                datos["simbolos"] = SIMBOLOS
                datos["formas"] = formas
                datos["avisos"] = tipos_coinciden(formas)
                datos["ancho"], datos["alto"] = ANCHO, ALTO
                datos["git"] = estado_git()
                datos["publicado"] = "https://tonycabreram.github.io/OrgulloCimarron/plantilla/croquis.html"
                self._json(datos)
            elif ruta == "/api/git":
                self._json(estado_git())
            else:
                self._error("Esa direccion no existe en el editor.", 404)
        except ErrorEditor as e:
            self._error(str(e))

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_local():
            self._error("Esta herramienta solo atiende desde localhost.", 403)
            return
        ruta = self.path.split("?")[0].rstrip("/")
        try:
            datos = self._cuerpo_json()
            if ruta == "/api/guardar":
                zonas, iconos = datos.get("zonas"), datos.get("iconos")
                if not isinstance(zonas, list) or not isinstance(iconos, list):
                    raise ErrorEditor("Faltan las zonas o los iconos.")
                self._json({"ok": True, "guardado": guardar_croquis(zonas, iconos),
                            "git": estado_git()})
            elif ruta == "/api/subir":
                mensaje = str(datos.get("mensaje") or "").strip()
                if not mensaje:
                    raise ErrorEditor("Falta el mensaje del commit.")
                if len(mensaje) > 200:
                    raise ErrorEditor("El mensaje del commit es demasiado largo.")
                if "\n" in mensaje:
                    raise ErrorEditor("El mensaje del commit va en una sola linea.")
                self._json(subir(mensaje), 200)
            else:
                self._error("Esa direccion no existe en el editor.", 404)
        except ErrorEditor as e:
            self._error(str(e))


def puerto_libre(desde: int, intentos: int = 10) -> int:
    """El primer puerto libre a partir de `desde`."""
    for p in range(desde, desde + intentos):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
            return p
    raise SystemExit(f"No hay ningun puerto libre entre {desde} y {desde + intentos}.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Editor local del croquis del Dia del Orgullo Cimarron. "
                    "Abre el navegador en una direccion que solo funciona en este equipo.")
    ap.add_argument("--puerto", type=int, default=8730,
                    help="puerto a usar (si esta ocupado, se prueba el siguiente)")
    ap.add_argument("--no-abrir", action="store_true",
                    help="no abrir el navegador automaticamente")
    args = ap.parse_args()

    for imprescindible in (CROQUIS, MAPA, EDITOR_HTML):
        if not imprescindible.is_file():
            print(f"Falta {imprescindible}.")
            return 1

    puerto = puerto_libre(args.puerto)
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    url = f"http://127.0.0.1:{puerto}/"

    print()
    print("  Editor del croquis · Dia del Orgullo Cimarron 2026")
    print("  " + "-" * 52)
    print(f"  Abierto en      {url}")
    print(f"  Modifica        {CROQUIS.relative_to(RAIZ)}")
    print(f"  Copia de seg.   {RESPALDO.relative_to(RAIZ)}\\croquis.html")
    print()
    print("  Solo funciona en este equipo. Para cerrarlo, Ctrl+C.")
    print("  Esto no se publica: el croquis que abre el QR sigue siendo")
    print("  de solo lectura.")
    print()

    if not args.no_abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrado. El croquis no cambio si no pulsaste Guardar.\n")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
