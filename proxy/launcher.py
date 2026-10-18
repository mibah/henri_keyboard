"""Steuerungsseite: Ollama und Proxy per Knopfdruck starten, beenden und überwachen.

  python3 launcher.py

Öffnet http://127.0.0.1:8790 im Browser. Nur Standardbibliothek. Das manuelle Starten
(python3 server.py) funktioniert weiterhin; ein so gestarteter Proxy wird erkannt.

  HENRI_MODEL  Modell (Standard gemma3:4b)
  PORT         Port des Proxys (Standard 8787)
  PANEL_PORT   Port dieser Seite (Standard 8790, nur lokal erreichbar)
"""
import atexit
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("HENRI_MODEL", "gemma3:4b")
PROXY_PORT = int(os.environ.get("PORT", "8787"))
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8790"))
OLLAMA = "http://127.0.0.1:11434"

# Der Proxy läuft in diesem Prozess (als Thread), damit Start und Stopp sauber gehen.
os.environ["LLM_MODEL"] = MODEL
import server  # noqa: E402

state = {"phase": "aus", "step": "", "error": "", "pull": None}  # phase: aus|startet|bereit|fehler
lock = threading.Lock()
own = {"httpd": None, "ollama": None}


class Problem(Exception):
    """Fehler mit einer Meldung, die der Nutzer verstehen kann."""


def update(**kw):
    with lock:
        state.update(kw)


def get_json(url, data=None, timeout=1.5):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ollama_up():
    try:
        get_json(OLLAMA + "/api/version")
        return True
    except Exception:
        return False


def model_present():
    try:
        names = {m["name"] for m in get_json(OLLAMA + "/api/tags")["models"]}
    except Exception:
        return False
    return MODEL in names or (":" not in MODEL and MODEL + ":latest" in names)


def proxy_health():
    try:
        return get_json(f"http://127.0.0.1:{PROXY_PORT}/health")
    except Exception:
        return None


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # sendet nichts, ermittelt nur die passende Schnittstelle
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def find_ollama():
    found = shutil.which("ollama")
    if found:
        return found
    system = platform.system()
    if system == "Windows":
        candidates = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")]
    elif system == "Darwin":
        candidates = ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                      "/Applications/Ollama.app/Contents/Resources/ollama"]
    else:
        candidates = ["/usr/local/bin/ollama", "/usr/bin/ollama"]
    return next((c for c in candidates if os.path.exists(c)), None)


def quiet_popen(cmd):
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if platform.system() == "Windows":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kw)


def wait_for(check, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.5)
    return False


def pull_model():
    update(step=f"Sprachmodell {MODEL} wird geladen (einmalig, mehrere GB) …", pull=0)
    req = urllib.request.Request(
        OLLAMA + "/api/pull",
        json.dumps({"name": MODEL, "stream": True}).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        for line in r:
            d = json.loads(line)
            if "error" in d:
                raise Problem("Das Sprachmodell konnte nicht geladen werden: " + d["error"])
            if d.get("total"):
                update(pull=int(100 * d.get("completed", 0) / d["total"]))
    update(pull=None)


def start_all():
    try:
        update(phase="startet", error="", step="Ollama wird geprüft …", pull=None)
        if not ollama_up():
            exe = find_ollama()
            if not exe:
                raise Problem("Ollama ist nicht installiert. Bitte von ollama.com installieren und erneut starten.")
            update(step="Ollama wird gestartet …")
            own["ollama"] = quiet_popen([exe, "serve"])
            if not wait_for(ollama_up, 40):
                raise Problem("Ollama startet nicht. Bitte die Ollama-App von Hand öffnen.")
        if not model_present():
            try:
                pull_model()
            except Problem:
                raise
            except Exception:
                raise Problem("Das Sprachmodell konnte nicht geladen werden. Internetverbindung prüfen.")
        if proxy_health() is None:
            update(step="Server wird gestartet …")
            try:
                own["httpd"] = server.make_server(PROXY_PORT)
            except OSError:
                raise Problem(f"Port {PROXY_PORT} ist belegt. Läuft schon ein anderes Programm darauf?")
            threading.Thread(target=own["httpd"].serve_forever, daemon=True).start()
            if not wait_for(lambda: proxy_health() is not None, 10):
                raise Problem("Der Server startet nicht.")
        update(phase="bereit", step="", pull=None)
    except Problem as e:
        update(phase="fehler", error=str(e), step="", pull=None)
    except Exception as e:
        update(phase="fehler", error=f"Unerwarteter Fehler ({type(e).__name__}).", step="", pull=None)


def stop_all():
    httpd = own["httpd"]
    if httpd is not None:
        httpd.shutdown()
        httpd.server_close()
        own["httpd"] = None
    proc = own["ollama"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    own["ollama"] = None
    update(phase="aus", error="", step="", pull=None)


def status():
    up = ollama_up()
    health = proxy_health()
    mine = own["httpd"] is not None
    with lock:
        s = dict(state)
    if s["phase"] != "startet":
        if up and health is not None and model_present():
            s["phase"] = "bereit"
        elif s["phase"] == "bereit":
            s["phase"] = "aus"
    ip = local_ip()
    return {
        "phase": s["phase"],
        "step": s["step"],
        "error": s["error"],
        "pull": s["pull"],
        "ollama": up,
        "model": up and model_present(),
        "modelName": MODEL,
        "proxy": health is not None,
        "external": health is not None and not mine,
        "url": f"http://{ip}:{PROXY_PORT}" if ip else None,
        "lastUse": None if health is None else health.get("last_correction_ago"),
        "corrections": 0 if health is None else health.get("corrections", 0),
    }


class Panel(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        # Schutz gegen fremde Webseiten, die localhost ansprechen (DNS-Rebinding).
        return self.headers.get("Host", "") in (f"127.0.0.1:{PANEL_PORT}", f"localhost:{PANEL_PORT}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path == "/api/status":
            return self._send(200, status())
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "panel.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Der eigene Header verhindert, dass andere Webseiten Aktionen auslösen können.
        if not self._host_ok() or self.headers.get("X-Henri") != "1":
            return self._send(403, {"error": "forbidden"})
        if self.path == "/api/start":
            with lock:
                busy = state["phase"] == "startet"
            if not busy:
                threading.Thread(target=start_all, daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path == "/api/stop":
            stop_all()
            return self._send(200, {"ok": True})
        if self.path == "/api/quit":
            self._send(200, {"ok": True})
            threading.Thread(target=shutdown, daemon=True).start()
            return
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def shutdown(*_):
    stop_all()
    os._exit(0)


def main():
    try:
        panel = ThreadingHTTPServer(("127.0.0.1", PANEL_PORT), Panel)
    except OSError:
        print("Die Steuerungsseite läuft schon, öffne sie im Browser.")
        webbrowser.open(f"http://127.0.0.1:{PANEL_PORT}")
        return
    atexit.register(stop_all)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    url = f"http://127.0.0.1:{PANEL_PORT}"
    print(f"Henri Steuerung läuft: {url}")
    print("Dieses Fenster offen lassen. Zum Beenden: Strg+C oder auf der Seite \"Programm beenden\".")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    panel.serve_forever()


if __name__ == "__main__":
    main()
