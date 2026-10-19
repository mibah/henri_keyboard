"""Gemeinsame Hilfen für die Tests (nur Standardbibliothek).

HENRI_ROOT zeigt auf den zu prüfenden Projektordner. Standard: dieses Repository.
So lässt sich dieselbe Testreihe auch gegen einen älteren Stand laufen lassen.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("HENRI_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY = os.path.join(ROOT, "proxy")
KEYBOARD_SRC = os.path.join(ROOT, "keyboard", "app", "src", "main")
if PROXY not in sys.path:
    sys.path.insert(0, PROXY)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def http(method, url, data=None, headers=None, timeout=30):
    """Gibt (Statuscode, JSON-Objekt) zurück; bei Nicht-JSON-Antworten der Text."""
    body = None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())
    req = urllib.request.Request(url, body, dict(headers or {}), method=method)
    if body is not None and "Content-Type" not in req.headers:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw.decode("utf-8", "replace")


class FakeLLM:
    """Schein-Sprachmodell mit OpenAI-Schnittstelle. Merkt sich alle Anfragen.

    reply: Funktion (Anfragekörper) -> Antworttext oder (Statuscode, Antworttext).
    """

    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply or (lambda body: "OK")
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                result = outer.reply(body)
                code, text = result if isinstance(result, tuple) else (200, result)
                if code == 200:
                    payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
                else:
                    payload = {"error": {"message": text}}
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
