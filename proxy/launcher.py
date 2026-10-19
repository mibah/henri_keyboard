"""Steuerungsseite: Ollama und Proxy per Knopfdruck starten, beenden und überwachen.

  python3 launcher.py

Öffnet http://127.0.0.1:8790 im Browser. Nur Standardbibliothek. Das manuelle Starten
(python3 server.py) funktioniert weiterhin; ein so gestarteter Proxy wird erkannt.

  HENRI_MODEL  Modell (Standard gemma3:4b)
  HENRI_REWORD_MODEL  optional anderes Modell für "anderes Wort vorschlagen" (z. B. qwen2.5:7b)
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
REWORD_MODEL = os.environ.get("HENRI_REWORD_MODEL", "") or MODEL  # optional anderes Modell für "anderes Wort"
MODELS = list(dict.fromkeys([MODEL, REWORD_MODEL]))
PROXY_PORT = int(os.environ.get("PORT", "8787"))
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8790"))
OLLAMA = "http://127.0.0.1:11434"

# Der Proxy läuft in diesem Prozess (als Thread), damit Start und Stopp sauber gehen.
os.environ["LLM_MODEL"] = MODEL
os.environ["LLM_REWORD_MODEL"] = REWORD_MODEL
import server  # noqa: E402
import providers  # noqa: E402

ENV_API_KEY = os.environ.get("LLM_API_KEY", "")
ACTIVE = None  # gewählter Anbieter (providers.Resolved), siehe apply_config()


def apply_config():
    """Liest die Anbieter-Einstellungen und gibt sie an den Server weiter.

    Ohne Konfigurationsdatei gilt wie bisher: lokal mit Ollama und den Modellen aus HENRI_MODEL.
    """
    global ACTIVE, MODEL, REWORD_MODEL, MODELS
    ACTIVE = providers.resolve()
    MODEL = ACTIVE.model
    REWORD_MODEL = ACTIVE.reword_model
    MODELS = list(dict.fromkeys([MODEL, REWORD_MODEL]))
    server.BASE_URL = ACTIVE.base_url
    server.API_KEY = ACTIVE.key if ACTIVE.hosted else ENV_API_KEY
    server.MODEL = MODEL
    server.REWORD_MODEL = REWORD_MODEL
    server.EXTRA_BODY = ACTIVE.extra_body
    server.EXTRA_HEADERS = ACTIVE.extra_headers
    server.HEALTH_SUFFIX = " (Cloud)" if ACTIVE.hosted else ""


apply_config()

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


def model_present(name=None):
    name = name or MODEL
    try:
        names = {m["name"] for m in get_json(OLLAMA + "/api/tags")["models"]}
    except Exception:
        return False
    return name in names or (":" not in name and name + ":latest" in names)


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


def pull_model(name):
    update(step=f"Sprachmodell {name} wird geladen (einmalig, mehrere GB) …", pull=0)
    req = urllib.request.Request(
        OLLAMA + "/api/pull",
        json.dumps({"name": name, "stream": True}).encode(),
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


def ensure_local():
    """Lokaler Anbieter (Ollama): starten und Modelle bei Bedarf laden. Unverändert wie bisher."""
    if not ollama_up():
        exe = find_ollama()
        if not exe:
            raise Problem("Ollama ist nicht installiert. Bitte von ollama.com installieren und erneut starten.")
        update(step="Ollama wird gestartet …")
        own["ollama"] = quiet_popen([exe, "serve"])
        if not wait_for(ollama_up, 40):
            raise Problem("Ollama startet nicht. Bitte die Ollama-App von Hand öffnen.")
    for name in MODELS:
        if not model_present(name):
            try:
                pull_model(name)
            except Problem:
                raise
            except Exception:
                raise Problem("Das Sprachmodell konnte nicht geladen werden. Internetverbindung prüfen.")


def ensure_hosted():
    """Gehosteter Anbieter: nur prüfen, ob Schlüssel und Modell funktionieren. Kein Ollama nötig."""
    for name in MODELS:
        update(step=f"Verbindung zu {ACTIVE.name} wird geprüft …")
        ok, message = providers.test(ACTIVE.base_url, ACTIVE.key, name, ACTIVE.extra_body, ACTIVE.extra_headers)
        if not ok:
            raise Problem(f"{ACTIVE.name}: {message}")


def start_all():
    try:
        apply_config()
        update(phase="startet", error="", step="Ollama wird geprüft …", pull=None)
        if ACTIVE.hosted:
            ensure_hosted()
        else:
            ensure_local()
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


def last_error(health):
    """Letzter Fehler des Anbieters in einfachem Deutsch, nur wenn er vor kurzem auftrat."""
    e = None if health is None else health.get("last_error")
    if not e or e.get("ago", 10**9) > 900:
        return None
    return {"text": providers.explain_code(e.get("what")), "ago": e["ago"]}


def status():
    hosted = ACTIVE.hosted
    up = ollama_up()
    health = proxy_health()
    mine = own["httpd"] is not None
    # Gehosteter Anbieter: kein Ollama und keine lokalen Modelle nötig
    models_ok = hosted or (up and all(model_present(n) for n in MODELS))
    with lock:
        s = dict(state)
    if s["phase"] != "startet":
        if health is not None and models_ok:
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
        "model": models_ok,
        "modelName": " + ".join(MODELS),
        "hosted": hosted,
        "providerName": ACTIVE.name,
        "lastError": last_error(health),
        "proxy": health is not None,
        "external": health is not None and not mine,
        "url": f"http://{ip}:{PROXY_PORT}" if ip else None,
        "lastUse": None if health is None else health.get("last_correction_ago"),
        "corrections": 0 if health is None else health.get("corrections", 0),
    }


def _text(data, key):
    v = data.get(key)
    return v.strip()[:500] if isinstance(v, str) else None


def _candidate(data):
    """Gespeicherte Einstellungen plus die eingegebenen Werte, ohne etwas zu speichern."""
    cfg = json.loads(json.dumps(providers.load()))
    providers.update_settings(
        cfg, _text(data, "provider") or providers.LOCAL, key=_text(data, "key"), model=_text(data, "model"),
        reword_model=_text(data, "reword_model"), base_url=_text(data, "base_url"),
    )
    return cfg


def provider_test(data):
    """Prüft die eingegebenen Werte (Schlüssel und Modell), ohne sie zu speichern."""
    r = providers.resolve(_candidate(data))
    if not r.hosted:
        if not ollama_up():
            return {"ok": False, "message": "Ollama läuft gerade nicht. Es wird beim Starten gestartet, falls installiert."}
        missing = [n for n in dict.fromkeys([r.model, r.reword_model]) if not model_present(n)]
        if missing:
            return {"ok": True, "message": "Ollama läuft. Fehlt noch und wird beim Starten geladen: " + ", ".join(missing) + "."}
        return {"ok": True, "message": "Ollama läuft, die Modelle sind vorhanden."}
    for name in dict.fromkeys([r.model, r.reword_model]):
        ok, message = providers.test(r.base_url, r.key, name, r.extra_body, r.extra_headers)
        if not ok:
            return {"ok": False, "message": (f"Modell {name}: " if name != r.model else "") + message}
    return {"ok": True, "message": message}


def provider_save(data):
    """Speichert den gewählten Anbieter und startet den Server damit neu, falls er lief."""
    with lock:
        if state["phase"] == "startet":
            return {"ok": False, "message": "Bitte warten, bis der Start fertig ist."}
    cfg = json.loads(json.dumps(providers.load()))
    providers.update_settings(
        cfg, _text(data, "provider") or providers.LOCAL, key=_text(data, "key"), model=_text(data, "model"),
        reword_model=_text(data, "reword_model"), base_url=_text(data, "base_url"),
        clear_key=bool(data.get("clearKey")),
    )
    providers.save(cfg)
    external = proxy_health() is not None and own["httpd"] is None
    running = own["httpd"] is not None
    apply_config()
    if external:
        return {"ok": True, "message": "Gespeichert. Der Server wurde von Hand gestartet und übernimmt das erst nach einem Neustart."}
    if running:
        stop_all()
        threading.Thread(target=start_all, daemon=True).start()
        return {"ok": True, "message": "Gespeichert. Der Server startet mit den neuen Einstellungen neu."}
    return {"ok": True, "message": "Gespeichert. Mit Starten geht es los."}


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

    def _json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 20000:
            return {}
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path == "/api/status":
            return self._send(200, status())
        if self.path == "/api/providers":
            return self._send(200, providers.public_view())
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
        if self.path == "/api/provider/test":
            return self._send(200, provider_test(self._json()))
        if self.path == "/api/provider/save":
            return self._send(200, provider_save(self._json()))
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
