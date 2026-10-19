"""Anbieter für das Sprachmodell: lokal (Ollama) oder ein gehosteter Dienst.

Alle Anbieter sprechen die verbreitete OpenAI-Schnittstelle (POST <Adresse>/chat/completions mit
"Authorization: Bearer <Schlüssel>"). Pro Anbieter stehen hier nur die Besonderheiten: Adresse,
Standardmodell, Zusatzfelder. Die Einstellungen liegen in `henri-config.json` (nicht im Git).
Ohne diese Datei gilt wie bisher: lokal mit Ollama.

Nur Standardbibliothek. Der Schlüssel wird nie zurückgegeben oder geloggt.
"""
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("HENRI_CONFIG") or os.path.join(HERE, "henri-config.json")

LOCAL = "ollama"
CUSTOM = "custom"

# id, Name, gehostet?, Adresse, Standardmodell, Schlüssel nötig?, Seite für den Schlüssel, Hinweis,
# Zusatzfelder im Anfragekörper, zusätzliche Header
PRESETS = [
    dict(
        id=LOCAL, name="Lokal (Ollama)", hosted=False,
        base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
        model=os.environ.get("HENRI_MODEL", "gemma3:4b"), needs_key=False, key_url="",
        note="Läuft auf diesem Rechner, kein Text verlässt das Haus. Kein Konto nötig.",
        extra_body={}, extra_headers={},
    ),
    dict(
        id="groq", name="Groq", hosted=True, base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile", needs_key=True, key_url="https://console.groq.com/keys",
        note="Sehr schnell. Kostenlose Stufe mit Tages- und Minutenlimits.",
        extra_body={}, extra_headers={},
    ),
    dict(
        id="mistral", name="Mistral", hosted=True, base_url="https://api.mistral.ai/v1",
        model="mistral-small-latest", needs_key=True, key_url="https://console.mistral.ai/api-keys/",
        note="Europäischer Anbieter. Für echte Nachrichten ein bezahltes Konto wählen.",
        extra_body={}, extra_headers={},
    ),
    dict(
        id="gemini", name="Google Gemini", hosted=True,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-flash-lite-latest", needs_key=True, key_url="https://aistudio.google.com/apikey",
        note="Kostenlose Stufe: Eingaben dürfen laut Anbieter zur Verbesserung genutzt werden. Nicht für echte Nachrichten.",
        extra_body={}, extra_headers={},
    ),
    dict(
        id="openrouter", name="OpenRouter", hosted=True, base_url="https://openrouter.ai/api/v1",
        model="meta-llama/llama-3.3-70b-instruct", needs_key=True, key_url="https://openrouter.ai/keys",
        note="Ein Zugang zu vielen Modellen, auch kostenlosen (Namen mit \":free\").",
        extra_body={}, extra_headers={"X-Title": "Henri Tastatur"},
    ),
    dict(
        id=CUSTOM, name="Eigener (OpenAI-kompatibel)", hosted=True, base_url="",
        model="", needs_key=False, key_url="",
        note="Jeder Dienst mit OpenAI-Schnittstelle: Adresse bis einschließlich /v1 eintragen.",
        extra_body={}, extra_headers={},
    ),
]


def preset(provider_id):
    return next((p for p in PRESETS if p["id"] == provider_id), PRESETS[0])


class Resolved:
    """Die Einstellungen des gewählten Anbieters mit allen Standardwerten ausgefüllt."""

    def __init__(self, p, saved):
        self.id = p["id"]
        self.name = p["name"]
        self.hosted = p["hosted"]
        self.base_url = (saved.get("base_url") or p["base_url"]).rstrip("/")
        self.key = saved.get("key", "") if p["needs_key"] or p["id"] == CUSTOM else ""
        if p["id"] == LOCAL:
            self.model = saved.get("model") or p["model"]
            self.reword_model = saved.get("reword_model") or os.environ.get("HENRI_REWORD_MODEL", "") or self.model
        else:
            self.model = saved.get("model") or p["model"]
            self.reword_model = saved.get("reword_model") or self.model
        self.extra_body = dict(p["extra_body"])
        self.extra_headers = dict(p["extra_headers"])


def load():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            cfg.setdefault("provider", LOCAL)
            cfg.setdefault("settings", {})
            return cfg
    except (OSError, ValueError):
        pass
    return {"provider": LOCAL, "settings": {}}


def save(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)  # enthält Schlüssel: nur für den Benutzer lesbar (unter Windows wirkungslos)
    except OSError:
        pass
    os.replace(tmp, CONFIG_PATH)


def resolve(cfg=None):
    cfg = cfg or load()
    p = preset(cfg.get("provider", LOCAL))
    return Resolved(p, cfg.get("settings", {}).get(p["id"], {}))


def public_view(cfg=None):
    """Alles für die Oberfläche, ohne die Schlüssel selbst (nur die letzten 4 Zeichen als Hinweis)."""
    cfg = cfg or load()
    out = []
    for p in PRESETS:
        r = Resolved(p, cfg.get("settings", {}).get(p["id"], {}))
        saved_key = cfg.get("settings", {}).get(p["id"], {}).get("key", "")
        out.append(dict(
            id=p["id"], name=p["name"], hosted=p["hosted"], needsKey=p["needs_key"], keyUrl=p["key_url"],
            note=p["note"], baseUrl=r.base_url, model=r.model,
            rewordModel=cfg.get("settings", {}).get(p["id"], {}).get("reword_model", ""),
            hasKey=bool(saved_key), keyHint=("…" + saved_key[-4:]) if len(saved_key) >= 8 else "",
            editableUrl=p["id"] == CUSTOM,
        ))
    return dict(active=preset(cfg.get("provider", LOCAL))["id"], providers=out)


def update_settings(cfg, provider_id, key=None, model=None, reword_model=None, base_url=None, clear_key=False):
    """Übernimmt die Eingaben. Ein leerer Schlüssel lässt den gespeicherten unverändert."""
    p = preset(provider_id)
    s = cfg.setdefault("settings", {}).setdefault(p["id"], {})
    if clear_key:
        s.pop("key", None)
    elif key:
        s["key"] = key.strip()
    if model is not None:
        s["model"] = model.strip()
    if reword_model is not None:
        s["reword_model"] = reword_model.strip()
    if base_url is not None and p["id"] == CUSTOM:
        s["base_url"] = base_url.strip()
    cfg["provider"] = p["id"]
    return cfg


# ---------- Verbindungstest und verständliche Fehlermeldungen ----------

def explain_code(what):
    """Kurze deutsche Erklärung zu "HTTP 429" o. ä. (so merkt sich der Server Fehler, ohne Inhalte)."""
    if not what:
        return ""
    if what.startswith("HTTP "):
        code = what[5:]
        return {
            "401": "Der Anbieter nimmt den Schlüssel nicht an.",
            "403": "Der Anbieter verweigert den Zugriff (Schlüssel oder Land).",
            "404": "Modell oder Adresse beim Anbieter nicht gefunden.",
            "429": "Der Anbieter meldet: zu viele Anfragen oder Tageslimit erreicht.",
        }.get(code, "Der Anbieter hat gerade ein Problem (" + what + ")." if code.startswith("5") else "Der Anbieter meldet einen Fehler (" + what + ").")
    return "Keine Verbindung zum Anbieter."


def test(base_url, key, model, extra_body=None, extra_headers=None, timeout=30):
    """Schickt eine winzige Testanfrage. Gibt (ok, Meldung auf Deutsch) zurück."""
    if not base_url:
        return False, "Bitte die Adresse des Anbieters eintragen."
    if not model:
        return False, "Bitte ein Modell eintragen."
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "user", "content": "Antworte nur mit dem Wort OK."}]}
    body.update(extra_body or {})
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    headers.update(extra_headers or {})
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        if not data.get("choices"):
            return False, "Der Anbieter antwortet in einem unerwarteten Format."
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.load(e).get("error", {})
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            pass
        msg = explain_code("HTTP %d" % e.code)
        if e.code == 400:
            msg = "Der Anbieter lehnt die Anfrage ab. Modellname und Einstellungen prüfen."
        if detail and key not in detail:  # niemals den Schlüssel anzeigen
            msg += " (" + detail[:140] + ")"
        return False, msg
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Der Anbieter ist nicht erreichbar. Internetverbindung und Adresse prüfen."
    except ValueError:
        return False, "Der Anbieter antwortet in einem unerwarteten Format."
    return True, "Verbindung ok (Antwort nach %.1f s)." % (time.time() - started)
