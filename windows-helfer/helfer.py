"""Henri Windows-Helfer: findet heraus, warum das Handy den Rechner nicht erreicht, macht Lösungsvorschläge
und protokolliert alles.

Eigenständig und nur lesend: ändert NICHTS am Rechner (keine Firewall-Regel, keine Einstellung, kein Programm).
Ändert nichts an der Henri-Tastatur, am Server oder an der Steuerung. Liest keine Schlüssel.
Öffnet http://127.0.0.1:8791 im Browser. Nur Standardbibliothek (die Windows-Abfragen laufen über PowerShell).

Was er tut:
  * prüft Server, Ollama, Netzwerkadressen, Windows-Firewall (Regeln, Sperrregeln, Richtlinien), Sicherheitsprogramme
  * sagt in einfachen Worten, woran es liegt, und schlägt Lösungen vor (Befehle zum Kopieren, die man selbst ausführt)
  * hört auf Port 8788 mit, ob sich das Handy meldet (Handy-Test)
  * schreibt ein Protokoll und einen Bericht in den Ordner "protokoll" neben diesem Programm
"""
import atexit
import ctypes
import datetime
import getpass
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1"
HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_PORT = int(os.environ.get("HENRI_HELFER_PORT", "8791"))
HENRI_PORT = 8787
TEST_PORT = 8788
RULE_NAME = "Henri Proxy"
MODEL = "gemma3:4b"
OLLAMA = "http://127.0.0.1:11434"
IS_WINDOWS = platform.system() == "Windows"
CREATE_NO_WINDOW = 0x08000000

LOCK = threading.RLock()


# ---------- Protokoll ----------

def _private_words():
    """(Wort, Ersatz) für Benutzer- und Rechnername."""
    pairs = []
    for getter, name in ((getpass.getuser, "<benutzer>"), (socket.gethostname, "<rechner>")):
        try:
            w = getter()
            if w and len(w) >= 3:
                pairs.append((w, name))
        except Exception:
            pass
    return pairs


def redact(text):
    """Benutzer- und Rechnername und MAC-Adressen sollen nicht im Bericht stehen, den man weitergibt."""
    for word, name in _private_words():
        # nur ganze Wörter, sonst wird aus "macOS" bei einem Rechner namens "mac" "<rechner>OS"
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", name, text, flags=re.I)
    # zuletzt, damit der Platzhalter nicht selbst als Name erkannt wird
    return re.sub(r"\b[0-9A-Fa-f]{1,2}(?:[-:][0-9A-Fa-f]{1,2}){5}\b", "<mac>", text)


class Log:
    MAX = 400_000

    def __init__(self, folder=None):
        self.lines, self.size = [], 0
        self.dir = folder or self._pick_dir()
        self.path = os.path.join(self.dir, "helfer-%s.log" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))

    @staticmethod
    def _pick_dir():
        for base in (HERE, tempfile.gettempdir()):
            folder = os.path.join(base, "protokoll" if base == HERE else "HenriHelfer")
            try:
                os.makedirs(folder, exist_ok=True)
                probe = os.path.join(folder, ".schreibtest")
                with open(probe, "w") as f:
                    f.write("x")
                os.remove(probe)
                return folder
            except OSError:
                continue
        return tempfile.gettempdir()

    def write(self, text, level="INFO"):
        line = "%s [%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), level, redact(str(text)))
        with LOCK:
            self.lines.append(line)
            self.size += len(line)
            while self.size > self.MAX and len(self.lines) > 1:
                self.size -= len(self.lines.pop(0))
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def text(self, last=60_000):
        with LOCK:
            joined = "\n".join(self.lines)
        return joined[-last:]


LOG = Log()


# ---------- Befehle und Netzwerk ----------

def _decode(data):
    return (data or b"").decode("utf-8-sig", "replace")


def run(cmd, timeout=40, keep=2000):
    """Führt einen Befehl aus und protokolliert alles. Wirft nie eine Ausnahme."""
    started = time.time()
    rc, out, err = None, "", ""
    try:
        kw = {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, **kw)
        rc, out, err = p.returncode, _decode(p.stdout), _decode(p.stderr)
    except subprocess.TimeoutExpired:
        err = "Zeitüberschreitung nach %s s" % timeout
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    secs = time.time() - started
    LOG.write("$ %s\n  rc=%s (%.1f s)\n  stdout: %s\n  stderr: %s"
              % (" ".join(str(c) for c in cmd)[:300], rc, secs, out.strip()[:keep], err.strip()[:1000]), "CMD")
    return {"rc": rc, "out": out, "err": err, "secs": secs}


PS_PREFIX = "$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "


def ps(script, timeout=40, keep=2000):
    LOG.write("PowerShell-Skript: " + script[:1500], "PS")
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", PS_PREFIX + script], timeout, keep)


def ps_json(script, timeout=40):
    """Ergebnis einer PowerShell-Abfrage als Liste von Dicts; None, wenn die Abfrage nicht klappte."""
    r = ps("& { " + script + " } | ConvertTo-Json -Compress -Depth 4", timeout)
    text = r["out"].strip()
    if not text:
        return None if r["rc"] not in (0,) else []
    try:
        data = json.loads(text)
    except ValueError:
        LOG.write("Ausgabe war kein JSON.", "WARN")
        return None
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # kein System-Proxy für Adressen im Heimnetz


def http_get(url, timeout=4):
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            code, body = r.status, r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, body = e.code, ""
    except Exception as e:
        code, body = None, "%s: %s" % (type(e).__name__, e)
    LOG.write("GET %s -> %s %s" % (url, code, body[:120].replace("\n", " ") if code is None else ""), "NET")
    return code, body


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # sendet nichts, ermittelt nur die passende Schnittstelle
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# ---------- Prüfungen ----------

CHECKS = []
VIRTUAL = re.compile(r"vEthernet|VirtualBox|VMware|WSL|Hyper-V|\bTAP\b|VPN|Tailscale|ZeroTier|Loopback|Bluetooth|Docker|Npcap", re.I)


def F(id, title, status, detail):
    """status: ok | bad | warn | info | skip"""
    return {"id": id, "title": title, "status": status, "detail": detail, "solution": []}


def S(text, cmd=None, expect=None, fallback=False):
    """Ein Schritt im Arbeitsplan: was tun, optional ein Befehl zum Kopieren, und woran man sieht, dass es geklappt hat.
    Der Helfer führt nichts davon selbst aus."""
    return {"text": text, "cmd": cmd, "expect": expect, "fallback": fallback}


def check(id, title, windows=False):
    def register(fn):
        CHECKS.append((id, title, windows, fn))
        return fn
    return register


def truthy(v):
    return str(v).strip().lower() in ("true", "1", "yes", "ja")


def port_hit(spec, ports):
    """Trifft eine Port-Angabe wie "80, 8000-9000" einen der Ports?"""
    for token in re.split(r"[\s,]+", str(spec or "")):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            if any(lo <= p <= hi for p in ports):
                return True
    return False


@check("system", "Rechner")
def check_system(ctx):
    admin = ""
    if IS_WINDOWS:
        try:
            admin = ", Administrator" if ctypes.windll.shell32.IsUserAnAdmin() else ", normaler Benutzer"
        except Exception:
            pass
    return F("system", "Rechner", "info", "%s, Python %s%s" % (platform.platform(), platform.python_version(), admin))


@check("server", "Henri-Server auf diesem Rechner")
def check_server(ctx):
    code, text = http_get("http://127.0.0.1:%d/health" % HENRI_PORT)
    if code == 200:
        model = ""
        try:
            model = json.loads(text).get("model", "")
        except ValueError:
            pass
        ctx["server_up"], ctx["hosted"] = True, "(Cloud)" in model
        return F("server", "Henri-Server auf diesem Rechner", "ok", "läuft (Modell: %s)" % (model or "?"))
    ctx["server_up"] = False
    return F("server", "Henri-Server auf diesem Rechner", "bad",
             "läuft nicht. In der Henri-Steuerung (Start-Henri.bat) auf Starten drücken und warten, bis es grün ist.")


@check("ollama", "Ollama und Sprachmodell")
def check_ollama(ctx):
    if ctx.get("hosted"):
        return F("ollama", "Ollama und Sprachmodell", "info", "nicht nötig, es ist ein Cloud-Anbieter eingestellt")
    code, text = http_get(OLLAMA + "/api/tags")
    if code != 200:
        return F("ollama", "Ollama und Sprachmodell", "bad",
                 "Ollama antwortet nicht. Ollama aus dem Startmenü starten oder in der Henri-Steuerung auf Starten drücken.")
    try:
        names = [m.get("name", "") for m in json.loads(text).get("models", [])]
    except ValueError:
        names = []
    if any(n.startswith(MODEL) for n in names):
        return F("ollama", "Ollama und Sprachmodell", "ok", "Ollama läuft, %s ist geladen" % MODEL)
    return F("ollama", "Ollama und Sprachmodell", "warn",
             "Ollama läuft, aber %s fehlt noch (ca. 3 GB). In der Henri-Steuerung auf Starten drücken, sie lädt es."
             " Oder in der Eingabeaufforderung: ollama pull %s" % (MODEL, MODEL))


@check("listen", "Lauscht der Server für das Handy?", windows=True)
def check_listen(ctx):
    rows = ps_json("Get-NetTCPConnection -State Listen -LocalPort %d -ErrorAction SilentlyContinue | "
                   "Select-Object LocalAddress,OwningProcess,@{n='Name';e={(Get-Process -Id $_.OwningProcess "
                   "-ErrorAction SilentlyContinue).ProcessName}}" % HENRI_PORT)
    title = "Lauscht der Server für das Handy?"
    if rows is None:
        return F("listen", title, "warn", "Konnte nicht abgefragt werden (siehe Protokoll).")
    if not rows:
        if ctx.get("server_up"):
            return F("listen", title, "warn", "Der Server antwortet, aber es wurde kein lauschender Port gefunden.")
        return F("listen", title, "skip", "Der Server läuft nicht.")
    addrs = {str(r.get("LocalAddress")) for r in rows}
    names = ", ".join(sorted({str(r.get("Name") or "?") for r in rows}))
    if addrs & {"0.0.0.0", "::"}:
        extra = "" if re.search(r"python", names, re.I) else " (Achtung: Programm %s, erwartet wird python)" % names
        return F("listen", title, "ok" if not extra else "warn", "lauscht auf allen Netzwerkkarten, Programm: %s%s" % (names, extra))
    return F("listen", title, "bad",
             "lauscht nur auf %s, das Handy kann so nie verbinden (Programm: %s). Henri-Server beenden und neu starten."
             % (", ".join(sorted(addrs)), names))


@check("adapters", "Netzwerkadresse des Rechners")
def check_adapters(ctx):
    title = "Netzwerkadresse des Rechners"
    primary = local_ip()
    ctx["ip"] = primary
    rows = ps_json("Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object "
                   "{ $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | "
                   "Select-Object IPAddress,InterfaceAlias") if IS_WINDOWS else None
    real = []
    lines = []
    for r in rows or []:
        ip, name = str(r.get("IPAddress")), str(r.get("InterfaceAlias") or "")
        virtual = bool(VIRTUAL.search(name))
        lines.append("%s (%s%s)" % (ip, name, ", virtuell" if virtual else ""))
        if not virtual:
            real.append(ip)
    if primary and primary not in real and rows is None:
        real = [primary]
    ordered = ([primary] if primary and primary in real else []) + [i for i in real if i != primary]
    ctx["ips"] = ordered or ([primary] if primary else [])
    if not primary and not ordered:
        return F("adapters", title, "bad", "Keine Netzwerkadresse gefunden. Ist der Rechner mit dem WLAN oder Kabel verbunden?")
    detail = "; ".join(lines) if lines else str(primary)
    if rows is not None and primary and primary not in real:
        return F("adapters", title, "warn",
                 "Die automatisch gewählte Adresse %s gehört zu einem virtuellen Netz (VPN, WSL, Hyper-V). "
                 "Das Handy braucht die Adresse des WLANs oder Kabels. Alle Adressen: %s" % (primary, detail))
    if len(ordered) > 1:
        return F("adapters", title, "warn", "Mehrere Netzwerke gefunden. Für das Handy zählt die Adresse des Netzes, "
                 "in dem auch das Handy ist. Adressen: %s" % detail)
    return F("adapters", title, "ok", detail)


@check("self", "Erreicht sich der Rechner selbst über das Netzwerk?")
def check_self(ctx):
    title = "Erreicht sich der Rechner selbst über das Netzwerk?"
    if not ctx.get("server_up"):
        return F("self", title, "skip", "Der Server läuft nicht.")
    if not ctx.get("ips"):
        return F("self", title, "skip", "Keine Netzwerkadresse.")
    results = []
    for ip in ctx["ips"]:
        code, _ = http_get("http://%s:%d/health" % (ip, HENRI_PORT))
        results.append((ip, code == 200))
    detail = ", ".join("%s %s" % (ip, "ja" if ok else "nein") for ip, ok in results)
    if any(ok for _, ok in results):
        return F("self", title, "ok", detail)
    return F("self", title, "bad", "Der Rechner erreicht den Server nicht über seine Netzwerkadresse (%s). "
             "Daran scheitert auch das Handy. Ursachen: Firewall-Regel, Sperrregel oder ein Sicherheitsprogramm." % detail)


@check("profile", "Netzwerkart", windows=True)
def check_profile(ctx):
    rows = ps_json("Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select-Object InterfaceAlias,NetworkCategory")
    if rows is None or not rows:
        return F("profile", "Netzwerkart", "skip", "Nicht abfragbar.")
    cat = {"0": "Öffentlich", "public": "Öffentlich", "1": "Privat", "private": "Privat",
           "2": "Domäne", "domainauthenticated": "Domäne"}
    parts = ["%s: %s" % (r.get("InterfaceAlias"), cat.get(str(r.get("NetworkCategory")).lower(), r.get("NetworkCategory")))
             for r in rows]
    return F("profile", "Netzwerkart", "info", "; ".join(parts) + ". Die Henri-Regel gilt für alle Arten.")


@check("fw_state", "Windows-Firewall", windows=True)
def check_fw_state(ctx):
    rows = ps_json("Get-NetFirewallProfile -ErrorAction SilentlyContinue | Select-Object Name,Enabled")
    if rows is None:
        ctx["fw_enabled"] = None
        return F("fw_state", "Windows-Firewall", "warn", "Konnte nicht abgefragt werden (siehe Protokoll).")
    names = {"domain": "Domäne", "private": "Privat", "public": "Öffentlich"}
    parts = ["%s: %s" % (names.get(str(r.get("Name")).lower(), r.get("Name")), "an" if truthy(r.get("Enabled")) else "aus")
             for r in rows]
    ctx["fw_enabled"] = any(truthy(r.get("Enabled")) for r in rows)
    return F("fw_state", "Windows-Firewall", "info", "; ".join(parts))


RULE_QUERY = ("Get-NetFirewallRule -DisplayName '%s' -ErrorAction SilentlyContinue | ForEach-Object { "
              "$p = $_ | Get-NetFirewallPortFilter; [pscustomobject]@{Name=$_.Name;Enabled=[string]$_.Enabled;"
              "Direction=[string]$_.Direction;Action=[string]$_.Action;Profile=[string]$_.Profile;"
              "Protocol=[string]$p.Protocol;LocalPort=[string]$p.LocalPort} }" % RULE_NAME)


def rule_ok(r):
    profile = str(r.get("Profile"))
    profile_ok = profile.strip() == "Any" or {"Domain", "Private", "Public"} <= set(re.split(r"[\s,]+", profile))
    return (truthy(r.get("Enabled")) and str(r.get("Direction")) == "Inbound" and str(r.get("Action")) == "Allow"
            and str(r.get("Protocol")).upper() in ("TCP", "6") and port_hit(r.get("LocalPort"), [HENRI_PORT])
            and profile_ok)


@check("fw_rule", "Firewall-Regel für das Handy (Port %d)" % HENRI_PORT, windows=True)
def check_fw_rule(ctx):
    title = "Firewall-Regel für das Handy (Port %d)" % HENRI_PORT
    rows = ps_json(RULE_QUERY)
    if rows is None:
        return F("fw_rule", title, "warn", "Konnte nicht abgefragt werden (siehe Protokoll).")
    if any(rule_ok(r) for r in rows):
        return F("fw_rule", title, "ok", "Regel \"%s\" ist vorhanden und richtig." % RULE_NAME)
    if ctx.get("fw_enabled") is False:
        return F("fw_rule", title, "info", "Die Firewall ist aus, die Regel wäre im Moment nicht nötig.")
    what = "ist vorhanden, aber falsch eingestellt" if rows else "fehlt"
    return F("fw_rule", title, "bad", "Die Regel \"%s\" %s. Ohne sie blockiert die Firewall das Handy." % (RULE_NAME, what))


BLOCK_QUERY = ("Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True -ErrorAction SilentlyContinue | "
               "ForEach-Object { $p = $_ | Get-NetFirewallPortFilter; $a = $_ | Get-NetFirewallApplicationFilter; "
               "[pscustomobject]@{Name=$_.Name;Display=$_.DisplayName;Profile=[string]$_.Profile;"
               "Protocol=[string]$p.Protocol;LocalPort=[string]$p.LocalPort;Program=[string]$a.Program} }")


def blocks_henri(r):
    program = str(r.get("Program") or "")
    port = str(r.get("LocalPort") or "Any")
    if re.search(r"python|ollama", program, re.I):
        return True
    if port_hit(port, [HENRI_PORT, TEST_PORT]):
        return True
    return program in ("", "Any") and port in ("", "Any")


@check("fw_blocks", "Sperrregeln in der Firewall", windows=True)
def check_fw_blocks(ctx):
    title = "Sperrregeln in der Firewall"
    rows = ps_json(BLOCK_QUERY, timeout=120)
    ctx["block_names"] = []
    if rows is None:
        return F("fw_blocks", title, "warn", "Konnte nicht abgefragt werden (siehe Protokoll).")
    hits = [r for r in rows if blocks_henri(r)]
    if not hits:
        return F("fw_blocks", title, "ok", "keine Sperrregel gegen Python, Ollama oder Port %d gefunden" % HENRI_PORT)
    ctx["block_names"] = [str(r.get("Name")) for r in hits if r.get("Name")]
    desc = "; ".join("%s (%s)" % (r.get("Display"), r.get("Program") or r.get("LocalPort")) for r in hits)
    return F("fw_blocks", title, "bad",
             "Windows blockiert das Handy mit einer Sperrregel: %s. Das passiert, wenn man beim ersten Start der "
             "Firewall-Frage auf Abbrechen klickt. Sperrregeln gehen vor Erlauben-Regeln." % desc)


@check("antivirus", "Sicherheitsprogramme", windows=True)
def check_antivirus(ctx):
    title = "Sicherheitsprogramme"
    av = ps_json("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction SilentlyContinue | Select-Object displayName")
    fw = ps_json("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -ErrorAction SilentlyContinue | Select-Object displayName")
    if av is None and fw is None:
        return F("antivirus", title, "skip", "Nicht abfragbar.")
    names = sorted({str(r.get("displayName")) for r in (av or []) + (fw or []) if r.get("displayName")})
    other = [n for n in names if not re.search(r"Windows Defender|Microsoft Defender", n, re.I)]
    ctx["av_names"] = other
    if other:
        return F("antivirus", title, "warn", "Neben Windows ist %s installiert. Solche Programme haben oft eine eigene "
                 "Firewall, die das Handy blockiert, auch wenn die Windows-Firewall in Ordnung ist. Im Programm eine "
                 "Ausnahme für Python und Port %d anlegen oder es zum Test kurz ausschalten." % (", ".join(other), HENRI_PORT))
    return F("antivirus", title, "ok", ", ".join(names) or "nur Windows-eigener Schutz")


@check("fw_policy", "Firewall-Richtlinien (Firma, Schule, Verwaltung)", windows=True)
def check_fw_policy(ctx):
    title = "Firewall-Richtlinien (Firma, Schule, Verwaltung)"
    rows = ps_json("Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Select-Object "
                   "@{n='Name';e={[string]$_.Name}},@{n='Local';e={[string]$_.AllowLocalFirewallRules}},"
                   "@{n='Inbound';e={[string]$_.DefaultInboundAction}}")
    gpo = ps_json("Get-NetFirewallRule -PolicyStore ActiveStore -Direction Inbound -Action Block -Enabled True "
                  "-ErrorAction SilentlyContinue | Where-Object { $_.PolicyStoreSourceType -eq 'GroupPolicy' } | "
                  "Select-Object @{n='Display';e={$_.DisplayName}}")
    if rows is None and gpo is None:
        return F("fw_policy", title, "skip", "Nicht abfragbar.")
    ignoring = [str(r.get("Name")) for r in rows or [] if str(r.get("Local")).strip().lower() == "false"]
    managed = [str(r.get("Display")) for r in gpo or []]
    if ignoring:
        return F("fw_policy", title, "bad", "Eine Richtlinie sorgt dafür, dass Windows lokale Firewall-Regeln ignoriert "
                 "(Netzwerkarten: %s). Die Henri-Regel wirkt dann nicht. Das lässt sich nur vom Verwalter dieses "
                 "Rechners ändern, oder man nutzt den Notfall-Tunnel." % ", ".join(ignoring))
    if managed:
        return F("fw_policy", title, "warn", "Es gibt Sperrregeln aus einer Richtlinie (nicht lokal entfernbar): %s"
                 % "; ".join(managed[:8]))
    inbound = ", ".join("%s: %s" % (r.get("Name"), r.get("Inbound")) for r in rows or [])
    return F("fw_policy", title, "ok", "keine Richtlinie gefunden, die lokale Regeln aushebelt. Standard für eingehend: %s" % inbound)


@check("internet", "Internetzugang (für den Notfall-Tunnel)")
def check_internet(ctx):
    title = "Internetzugang (für den Notfall-Tunnel)"
    code, _ = http_get("https://1.1.1.1/cdn-cgi/trace", timeout=6)
    if code == 200:
        return F("internet", title, "ok", "Der Rechner kommt ins Internet.")
    return F("internet", title, "warn", "Kein Internetzugang oder blockiert. Ein Notfall-Tunnel würde so nicht gehen.")


DUMP_COMMANDS = [
    ("ipconfig /all", ["ipconfig", "/all"]),
    ("route print -4", ["route", "print", "-4"]),
    ("arp -a", ["arp", "-a"]),
    ("netstat -ano", ["netstat", "-ano"]),
    ("winhttp-Proxy", ["netsh", "winhttp", "show", "proxy"]),
    ("Windows-Version", ["cmd", "/c", "ver"]),
]
DUMP_POWERSHELL = [
    ("Netzwerkadapter", "Get-NetAdapter -ErrorAction SilentlyContinue | Format-Table Name,Status,LinkSpeed,InterfaceDescription -AutoSize | Out-String -Width 220"),
    ("Firewall-Profile", "Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Format-List Name,Enabled,DefaultInboundAction,AllowLocalFirewallRules,LogBlocked | Out-String"),
    ("Browser-Proxy", "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -ErrorAction SilentlyContinue | Select-Object ProxyEnable,ProxyServer,AutoConfigURL | Format-List | Out-String"),
    ("Sicherheitsprozesse", "Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'avast|avg|norton|mcafee|kaspersky|bitdefender|eset|sophos|trend|f-secure|malwarebytes|webroot|panda|avira|comodo|zonealarm|crowdstrike|sentinel|cylance|symantec|checkpoint|forti|cisco|vpn' } | Select-Object -ExpandProperty ProcessName -Unique | Out-String"),
]


@check("dump", "Netzwerkdaten für den Bericht", windows=True)
def check_dump(ctx):
    title = "Netzwerkdaten für den Bericht"
    parts = []
    for name, cmd in DUMP_COMMANDS:
        r = run(cmd, timeout=30, keep=15000)
        parts.append("--- %s (rc=%s)\n%s" % (name, r["rc"], (r["out"] or r["err"]).strip()))
    security = ""
    for name, script in DUMP_POWERSHELL:
        r = ps(script, timeout=40, keep=15000)
        parts.append("--- %s (rc=%s)\n%s" % (name, r["rc"], (r["out"] or r["err"]).strip()))
        if name == "Sicherheitsprozesse":
            security = " ".join(r["out"].split())
    with LOCK:
        STATE["dump"] = redact("\n\n".join(parts))
    detail = "gesammelt (stehen im Bericht)."
    if security:
        detail += " Laufende Sicherheits- oder VPN-Prozesse: %s." % security
    return F("dump", title, "info", detail)


IPV4 = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")
MAC = re.compile(r"\b[0-9a-f]{1,2}(?:[-:][0-9a-f]{1,2}){5}\b", re.I)


def valid_ip(ip):
    return bool(IPV4.match(str(ip or "").strip()))


@check("phone", "Sieht der Rechner das Handy im Netz?")
def check_phone(ctx):
    title = "Sieht der Rechner das Handy im Netz?"
    ip = (STATE.get("phone_ip") or "").strip()
    if not ip:
        return F("phone", title, "skip", "Keine Handy-IP eingetragen. (Android: Einstellungen, WLAN, Zahnrad beim WLAN, IP-Adresse.)")
    if not valid_ip(ip):
        return F("phone", title, "warn", "Die eingetragene Handy-IP ist keine gültige Adresse.")
    other_net = ""
    pc = [i for i in ctx.get("ips", []) if i]
    if pc and not any(ip.split(".")[:3] == i.split(".")[:3] for i in pc):
        other_net = (" Achtung: Das Handy ist anscheinend in einem anderen Netz als der Rechner (%s). "
                     "Beide müssen mit demselben WLAN verbunden sein, kein Gastnetz." % ", ".join(pc))
    ping = run(["ping", "-n", "2", "-w", "1500", ip] if IS_WINDOWS else ["ping", "-c", "2", "-W", "2", ip], timeout=20)
    arp = run(["arp", "-a", ip] if IS_WINDOWS else ["arp", "-n", ip], timeout=10)
    macs = [m for m in MAC.findall(arp["out"]) if m.lower().replace("-", ":") != "ff:ff:ff:ff:ff:ff"]
    if ping["rc"] == 0:
        return F("phone", title, "ok" if not other_net else "warn",
                 "Der Rechner erreicht das Handy %s. Beide sind im selben Netz.%s" % (ip, other_net))
    if macs:
        return F("phone", title, "ok" if not other_net else "warn",
                 "Das Handy %s ist im selben Netz sichtbar, antwortet aber nicht auf Ping (das ist bei Handys normal).%s"
                 % (ip, other_net))
    return F("phone", title, "bad", "Der Rechner sieht das Handy %s gar nicht. Entweder sind sie in verschiedenen Netzen, "
             "oder der Router trennt WLAN-Geräte voneinander (Gastnetz, AP-Isolation).%s" % (ip, other_net))


RULE_CMD = ('netsh advfirewall firewall add rule name="%s" dir=in action=allow protocol=TCP localport=%d,%d profile=any'
            % (RULE_NAME, HENRI_PORT, TEST_PORT))
VERIFY_RULE_CMD = 'netsh advfirewall firewall show rule name="%s"' % RULE_NAME


def q(s):
    return str(s).replace("'", "''")


CMD_ADMIN = S("Eingabeaufforderung als Administrator öffnen: Windows-Taste drücken, cmd tippen, mit der rechten Maustaste auf "
              "„Eingabeaufforderung“ klicken, „Als Administrator ausführen“ wählen, mit Ja bestätigen.",
              expect="Oben im Fenster steht „Administrator: Eingabeaufforderung“.")
PS_ADMIN = S("PowerShell als Administrator öffnen: Windows-Taste drücken, powershell tippen, mit der rechten Maustaste auf "
             "„Windows PowerShell“ klicken, „Als Administrator ausführen“ wählen, mit Ja bestätigen.",
             expect="Oben im Fenster steht „Administrator: Windows PowerShell“.")
START_HENRI = S("Im Henri-Ordner doppelt auf Start-Henri.bat klicken. Im Browser auf „Starten“ drücken und warten.",
                expect="Der große Punkt ist grün und es steht „Bereit“ da.")

TUNNEL = [
    S("TUNNEL (umgeht Router und Firewall; nur für kurze Tests: die Adresse ist öffentlich, die Texte laufen über "
      "den Dienst Cloudflare, deshalb der Token). Zuerst Henri beenden, damit Port %d frei ist: In der Steuerungsseite unten auf "
      "„Programm ganz beenden“ klicken, oder das schwarze Fenster schließen." % HENRI_PORT,
      expect="Im Browser unter http://127.0.0.1:%d/health kommt eine Fehlerseite („Seite nicht erreichbar“)." % HENRI_PORT),
    S("Eingabeaufforderung im Ordner proxy öffnen: Im Explorer den Henri-Ordner und darin den Ordner proxy öffnen, oben in die "
      "Adresszeile klicken, cmd tippen, Enter. Dort das Programm laden:",
      "curl.exe -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
      expect="Die Datei cloudflared.exe liegt danach im Ordner proxy (ca. 30 bis 60 MB)."),
    S("In diesem Fenster Henri mit Token starten (EIN-GEHEIMER-CODE durch ein eigenes Wort ersetzen, merken). Das Fenster offen lassen. "
      "Fehlermeldung „python wird nicht gefunden“: py -3 server.py statt python server.py.",
      "set APP_TOKEN=EIN-GEHEIMER-CODE&& set LLM_MODEL=%s&& python server.py" % MODEL,
      expect="Es erscheint eine Zeile „Proxy auf :%d -> …“." % HENRI_PORT),
    S("Ein zweites Fenster öffnen (wieder im Ordner proxy wie oben, cmd in die Adresszeile) und den Tunnel starten. Offen lassen.",
      "cloudflared.exe tunnel --url http://localhost:%d" % HENRI_PORT,
      expect="In der Ausgabe steht eine Adresse wie https://irgendwas-zufällig.trycloudflare.com."),
    S("Am Handy im Browser diese Adresse mit /health dahinter öffnen, zum Beispiel https://irgendwas-zufällig.trycloudflare.com/health",
      expect="Es erscheint {\"ok\": true, …}."),
    S("In der Henri-App bei „Adresse“ die https-Adresse (ohne /health) und bei „Token“ den Code eintragen, dann „Speichern und "
      "Verbindung testen“.", expect="„Verbunden, Modell: %s“." % MODEL),
]

TUNNEL = [dict(st, fallback=True) for st in TUNNEL]

AV_HINTS = [
    (r"norton", "Norton öffnen → Einstellungen → Firewall → Datenverkehrsregeln → Hinzufügen: Eingehend, Zulassen, TCP, Port %d."),
    (r"mcafee", "McAfee öffnen → Mein Schutz → Firewall → Ports und Systemdienste → Hinzufügen: Port %d, TCP, eingehend zulassen."),
    (r"kaspersky", "Kaspersky öffnen → Einstellungen → Schutz → Firewall → Netzwerkregeln → Regel für Python (python.exe) hinzufügen: "
                   "eingehend zulassen, TCP, Port %d."),
    (r"avast|avg", "Avast/AVG öffnen → Menü → Einstellungen → Schutz → Kernschutz → Firewall → Anwendungsregeln: für Python "
                   "(python.exe) eingehende Verbindungen zulassen (Port %d, TCP)."),
    (r"bitdefender", "Bitdefender öffnen → Schutz → Firewall → Einstellungen → Regeln → Regel hinzufügen: Python (python.exe), "
                     "eingehend zulassen, Port %d."),
    (r"eset", "ESET öffnen → Einrichtung → Netzwerkschutz. Entweder unter „Verbundene Netzwerke“ (je nach Version „Netzwerkverbindungen“) das WLAN "
              "als „Heim- oder Büronetzwerk“ einstufen (bei „Öffentlich“ blockiert ESET eingehende Verbindungen streng), oder unter Firewall → "
              "Regeln und Zonen → Bearbeiten eine Regel anlegen: eingehend, TCP, lokaler Port %d, erlauben."),
]
AV_DEFAULT = ("Im Programm nach „Firewall“, „Netzwerkschutz“ oder „Ausnahmen“ suchen und für Python (python.exe) und den Port %d "
              "(TCP, eingehend) eine Ausnahme anlegen.")


def av_hint(names):
    joined = " ".join(names)
    for pattern, text in AV_HINTS:
        if re.search(pattern, joined, re.I):
            return text % HENRI_PORT + " (Menünamen können je nach Version abweichen.)"
    return AV_DEFAULT % HENRI_PORT


def solutions_for(f, ctx):
    """Schritte zu einer Prüfung. Nur Text und Befehle zum Kopieren, der Helfer ändert nichts."""
    key = (f["id"], f["status"])
    if key == ("server", "bad"):
        return [START_HENRI, S("Danach hier im Helfer noch einmal auf „Alles prüfen“ drücken.")]
    if key == ("ollama", "bad"):
        return [S("Ollama starten: Windows-Taste drücken, Ollama tippen, Enter.",
                  expect="Ein kleines Lama-Symbol erscheint unten rechts neben der Uhr (ggf. über den Pfeil ^)."),
                S("Falls es nicht startet: Die Henri-Steuerung (Start-Henri.bat) startet Ollama selbst, dort auf „Starten“ drücken.")]
    if key == ("ollama", "warn"):
        return [S("Modell laden (einmalig, ca. 3 GB, dauert je nach Internet einige Minuten). In der Eingabeaufforderung:",
                  "ollama pull %s" % MODEL, expect="Am Ende „success“."),
                S("Prüfen, ob das Modell da ist:", "ollama list", expect="In der Liste steht %s." % MODEL)]
    if key == ("listen", "bad"):
        return [S("In der Henri-Steuerung unten „Programm ganz beenden“ klicken, dann Start-Henri.bat neu starten und „Starten“ drücken.",
                  expect="Der Punkt wird grün. Hilft das nicht: Rechner neu starten und wieder Start-Henri.bat.")]
    if key == ("listen", "warn"):
        return [S("Ein anderes Programm belegt Port %d. Task-Manager öffnen (Strg+Umschalt+Esc), das Programm unter „Details“ suchen "
                  "(Name und Nummer stehen in der Prüfung) und mit rechter Maustaste „Task beenden“. Dann Henri neu starten." % HENRI_PORT)]
    if key == ("adapters", "warn"):
        return [S("Die richtige Adresse des Rechners anzeigen (die des WLAN- oder Kabel-Adapters, nicht von „vEthernet“, VPN, WSL):",
                  "ipconfig", expect="Beim Adapter „WLAN“ oder „Ethernet“ steht eine IPv4-Adresse wie 192.168.x.x."),
                S("In der Henri-App genau diese Adresse mit :%d eintragen, also http://192.168.x.x:%d." % (HENRI_PORT, HENRI_PORT))]
    if key == ("adapters", "bad"):
        return [S("Den Rechner mit WLAN oder Kabel verbinden (Symbol unten rechts neben der Uhr) und hier noch einmal prüfen.")]
    if key == ("fw_rule", "bad"):
        return [CMD_ADMIN,
                S("Regel anlegen (Befehl kopieren, im Fenster mit rechter Maustaste einfügen, Enter):", RULE_CMD, expect="„OK.“"),
                S("Prüfen, dass die Regel da ist:", VERIFY_RULE_CMD,
                  expect="Es steht Aktiviert: Ja, Richtung: Ein, Aktion: Zulassen, LokalerPort: 8787,8788 da (englisch: Enabled: Yes)."),
                S("Geht der Befehl nicht: Windows-Taste, „Windows Defender Firewall mit erweiterter Sicherheit“ öffnen → links "
                  "„Eingehende Regeln“ → rechts „Neue Regel…“ → Port → TCP → Bestimmte lokale Ports: %d,%d → Verbindung zulassen → "
                  "alle drei Haken lassen → Name „%s“ → Fertig stellen." % (HENRI_PORT, TEST_PORT, RULE_NAME))]
    if key == ("fw_blocks", "bad"):
        names = list(ctx.get("block_names") or [])[:10]
        steps = [PS_ADMIN]
        for n in names:
            steps.append(S("Sperrregel entfernen (Befehl einfügen, Enter):", "Remove-NetFirewallRule -Name '%s'" % q(n),
                           expect="Keine Ausgabe, das heißt erledigt. Eine rote Fehlermeldung heißt: Regel nicht gefunden oder kein Administrator."))
        steps.append(S("Falls der Befehl nicht geht, per Oberfläche: Windows-Taste, „Windows Defender Firewall mit erweiterter Sicherheit“ → „Eingehende Regeln“ → "
                       "die Regel mit dem in der Prüfung genannten Namen suchen → rechte Maustaste → „Regel löschen“."))
        return steps
    if key == ("fw_policy", "bad"):
        return [S("Eine Richtlinie (Firma, Schule, Verwaltung) ignoriert lokale Regeln. Das kann nur der Verwalter dieses Rechners ändern. "
                  "Ihn bitten: „Eingehend TCP-Port %d in der Windows-Firewall erlauben.“" % HENRI_PORT)] + TUNNEL
    if key == ("fw_policy", "warn"):
        return [S("Die in der Prüfung genannten Sperrregeln kommen aus einer Richtlinie und lassen sich nicht selbst entfernen. "
                  "Den Verwalter bitten, eingehend TCP-Port %d davon auszunehmen." % HENRI_PORT)]
    if key == ("antivirus", "warn"):
        names = ctx.get("av_names") or []
        who = ", ".join(names) or "dem Sicherheitsprogramm"
        return [S("Zuerst testen, ob %s schuld ist: Den Schutz kurz ausschalten (Rechtsklick auf das Symbol unten rechts neben der Uhr, "
                  "Schutz oder Firewall für 10 Minuten deaktivieren), dann am Handy den Handy-Test öffnen." % who,
                  expect="Meldet sich das Handy jetzt, war es dieses Programm. Dann Schutz wieder einschalten und den nächsten Schritt machen."),
                S("Ausnahme anlegen: " + av_hint(names), expect="Handy-Test noch einmal öffnen: es meldet sich auch bei eingeschaltetem Schutz.")]
    if key == ("self", "bad"):
        return [S("Der Rechner erreicht den Server nicht einmal selbst über sein Netz. Häufigste Ursache: ein Sicherheitsprogramm mit eigener "
                  "Firewall (siehe Prüfung „Sicherheitsprogramme“). Dessen Schutz 10 Minuten ausschalten und hier noch einmal prüfen. "
                  "Geht es dann, in dem Programm eine Ausnahme für Python und Port %d anlegen, Schutz wieder einschalten." % HENRI_PORT)] + TUNNEL
    if key == ("phone", "bad"):
        return [S("WLAN-Namen vergleichen: Am Handy (Einstellungen → WLAN) und am Rechner (Symbol unten rechts neben der Uhr) muss derselbe "
                  "Name stehen. Heißt eines „…Gast“ oder „Guest“, auf das normale WLAN wechseln.",
                  expect="Gleicher WLAN-Name. Danach hier noch einmal prüfen."),
                S("Hängt der Rechner per Kabel am Router, das Handy im WLAN, und es geht trotzdem nicht: Im Router (Adresse steht auf dem "
                  "Aufkleber, oft fritz.box, 192.168.0.1, 192.168.1.1 oder 192.168.2.1) die „Client-Isolation“ bzw. „AP-Isolation“ "
                  "ausschalten oder „WLAN-Geräte dürfen untereinander kommunizieren“ erlauben. Ist das nicht möglich: Tunnel (unten).")] + TUNNEL
    if key == ("phone", "warn"):
        return [S("Das Handy ins selbe WLAN wie den Rechner verbinden (gleicher Name, nicht „Gast“) und hier noch einmal prüfen.")]
    return []


ALL_GOOD = [S("Am Handy (WLAN an, mobile Daten aus) im Browser eine der Adressen unter „Handy-Test“ öffnen, mit http:// davor.",
              expect="Das Handy zeigt „Verbindung klappt“, und im Helfer erscheint das Gerät unter Handy-Test."),
            S("Meldet sich nichts: VPN und „Privates DNS“ am Handy ausschalten (Einstellungen → Netzwerk → Privates DNS → Aus), "
              "und prüfen, dass Handy und Rechner im selben WLAN sind (nicht „Gast“).")] + TUNNEL


def build_plan(diagnosis, ips):
    """Alle Schritte in einer Reihenfolge ohne Doppelte: erst die Reparaturen, dann die Prüfung, ganz am Ende der Tunnel."""
    steps, fallback, seen = [], [], set()
    for d in diagnosis:
        for st in d.get("solution", []):
            key = (st["text"], st.get("cmd"))
            if key not in seen:
                seen.add(key)
                (fallback if st.get("fallback") else steps).append(st)
    ip = ips[0] if ips else "<IP des Rechners>"
    adr = "http://%s:%d" % (ip, HENRI_PORT)
    steps += [
        S("ABSCHLUSS. Prüfen, ob es jetzt geht. Am Rechner in der Eingabeaufforderung (Henri muss laufen):",
          "curl.exe %s/health" % adr, expect="Es erscheint {\"ok\": true, …}."),
        S("Am Handy im Browser (WLAN an, mobile Daten aus) öffnen: %s/health" % adr,
          expect="Dieselbe Antwort wie am Rechner."),
        S("Klappt beides: In der Henri-App als Adresse %s eintragen und „Speichern und Verbindung testen“ drücken." % adr,
          expect="„Verbunden, Modell: %s“." % MODEL),
    ]
    if fallback:
        steps.append(S("NUR WENN ES NACH ALLEM DAVOR NOCH NICHT GEHT, geht es hier weiter (Tunnel). Wenn es schon klappt, hier aufhören."))
        steps += fallback
    steps.append(S("Klappt es nicht: Diesen Helfer noch einmal starten, „Alles prüfen“ drücken, den neuen Bericht kopieren und einfügen."))
    return steps


def diagnose(findings):
    by = {f["id"]: f for f in findings}
    st = lambda i: by.get(i, {}).get("status")
    sol = lambda i: by.get(i, {}).get("solution", [])
    out = []

    def add(text, solution):
        out.append({"text": text, "solution": solution})
    if st("server") == "bad":
        add("Der Henri-Server läuft nicht. Zuerst in der Henri-Steuerung auf Starten drücken, dann hier noch einmal prüfen.", sol("server"))
    if st("listen") == "bad":
        add("Der Server lauscht nur auf diesem Rechner. Henri beenden und neu starten.", sol("listen"))
    if st("fw_blocks") == "bad":
        add("Eine Sperrregel in der Windows-Firewall blockiert das Handy.", sol("fw_blocks"))
    if st("fw_rule") == "bad":
        add("Es fehlt die Firewall-Regel, die das Handy durchlässt.", sol("fw_rule"))
    if st("fw_policy") == "bad":
        add("Eine Richtlinie hebelt lokale Firewall-Regeln aus. Hier hilft nur der Verwalter des Rechners oder der Notfall-Tunnel.", sol("fw_policy"))
    if st("phone") == "bad":
        add("Der Rechner sieht das Handy nicht im Netz: andere Netze oder Geräte-Trennung im Router (Gastnetz). "
            "Handy ins selbe WLAN wie den Rechner bringen.", sol("phone"))
    if st("self") == "bad" and not any(st(i) == "bad" for i in ("fw_blocks", "fw_rule", "fw_policy")):
        add("Der Rechner erreicht den Server nicht einmal selbst über das Netzwerk, obwohl die Windows-Regeln stimmen. "
            "Wahrscheinlich blockiert ein anderes Sicherheitsprogramm.", sol("self"))
    if st("antivirus") == "warn":
        if st("fw_rule") == "info":
            add("Die Windows-Firewall ist aus, weil ein anderes Sicherheitsprogramm sie ersetzt. Dessen eigene Firewall ist sehr wahrscheinlich "
                "die, die das Handy blockiert (Regeln der Windows-Firewall helfen dann nicht).", sol("antivirus"))
        else:
            add("Ein zusätzliches Sicherheitsprogramm ist installiert. Es kann das Handy blockieren.", sol("antivirus"))
    if st("ollama") in ("bad", "warn"):
        add("Ollama oder das Sprachmodell ist nicht bereit. Das hat nichts mit dem Netzwerk zu tun, aber ohne Modell wird nichts korrigiert.", sol("ollama"))
    if not out:
        add("Am Rechner ist alles in Ordnung. Jetzt den Handy-Test machen. Meldet sich das Handy dort nicht, "
            "liegt es am Router (Gastnetz, Geräte-Trennung) oder am Handy (VPN, Privates DNS).", ALL_GOOD)
    return out


# ---------- Zustand ----------

STATE = {"running": False, "stage": "", "findings": [], "diagnosis": [], "ip": None, "ips": [],
         "checked_at": None, "report": None, "phone_ip": "", "dump": ""}
CTX = {}


def run_checks():
    ctx = {}
    findings = []
    for id, title, windows, fn in CHECKS:
        if windows and not IS_WINDOWS:
            findings.append(F(id, title, "skip", "nur unter Windows"))
            continue
        try:
            found = fn(ctx)
            found["solution"] = solutions_for(found, ctx)
            findings.append(found)
        except Exception:
            LOG.write("Prüfung %s ist abgestürzt:\n%s" % (id, traceback.format_exc()), "ERROR")
            findings.append(F(id, title, "warn", "Diese Prüfung ist fehlgeschlagen (Einzelheiten im Protokoll)."))
    with LOCK:
        CTX.clear()
        CTX.update(ctx)
        STATE.update(findings=findings, diagnosis=diagnose(findings), ip=ctx.get("ip"),
                     ips=ctx.get("ips") or [], checked_at=time.strftime("%H:%M:%S"))
    LOG.write("Prüfung fertig: " + ", ".join("%s=%s" % (f["id"], f["status"]) for f in findings))
    return findings


# ---------- Handy-Test ----------

TEST = {"server": None, "events": [], "error": None, "timer": None, "active": False}
TEST_PAGE = ("<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Henri-Helfer</title></head>"
             "<body style=\"font:28px/1.4 system-ui,sans-serif;background:#0e1116;color:#f3f6fb;padding:32px\">"
             "<h1 style=\"color:#2ecc71\">&#10003; Verbindung klappt</h1>"
             "<p>Das Handy erreicht den Rechner.</p></body></html>").encode()


class TestHandler(BaseHTTPRequestHandler):
    def _any(self):
        add_event(self.client_address[0], TEST_PORT, self.path, self.headers.get("User-Agent", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(TEST_PAGE)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(TEST_PAGE)

    do_GET = do_POST = do_HEAD = _any

    def log_message(self, fmt, *args):
        pass


def add_event(ip, port, path="", ua=""):
    ev = {"time": time.strftime("%H:%M:%S"), "ip": ip, "port": port, "path": str(path)[:80], "ua": str(ua)[:100]}
    with LOCK:
        TEST["events"].append(ev)
    LOG.write("Handy-Test: Verbindung von %s auf Port %s %s" % (ip, port, ev["path"]), "TEST")


def watch_henri_port():
    """Meldet Verbindungen anderer Geräte zum echten Henri-Port (der Server selbst protokolliert nichts)."""
    seen = {}
    while TEST["active"]:
        if IS_WINDOWS:
            rows = ps_json("Get-NetTCPConnection -LocalPort %d -State Established -ErrorAction SilentlyContinue | "
                           "Select-Object RemoteAddress" % HENRI_PORT, timeout=15)
            for r in rows or []:
                ip = str(r.get("RemoteAddress"))
                if ip not in ("127.0.0.1", "::1") and time.time() - seen.get(ip, 0) > 60:
                    seen[ip] = time.time()
                    add_event(ip, HENRI_PORT)
        for _ in range(6):
            if not TEST["active"]:
                return
            time.sleep(0.5)


def start_test():
    with LOCK:
        if TEST["active"]:
            return True
        TEST.update(events=[], error=None)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", TEST_PORT), TestHandler)
    except OSError as e:
        TEST["error"] = "Port %d ist belegt oder gesperrt (%s)." % (TEST_PORT, e)
        LOG.write("Handy-Test konnte nicht starten: %s" % e, "ERROR")
        return False
    TEST.update(server=httpd, active=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=watch_henri_port, daemon=True).start()
    timer = threading.Timer(15 * 60, stop_test)
    timer.daemon = True
    timer.start()
    TEST["timer"] = timer
    LOG.write("Handy-Test läuft auf Port %d." % TEST_PORT)
    return True


def stop_test():
    with LOCK:
        httpd, timer = TEST["server"], TEST["timer"]
        TEST.update(server=None, timer=None, active=False)
    if timer:
        timer.cancel()
    if httpd:
        httpd.shutdown()
        httpd.server_close()
        LOG.write("Handy-Test beendet.")


# ---------- Bericht ----------

MARK = {"ok": "OK  ", "bad": "FEHL", "warn": "ACHT", "info": "INFO", "skip": "----"}


def build_report():
    with LOCK:
        findings, diagnosis = list(STATE["findings"]), list(STATE["diagnosis"])
        events = list(TEST["events"])
        ips = list(STATE["ips"])
    L = ["Henri Windows-Helfer %s, Bericht vom %s" % (VERSION, time.strftime("%Y-%m-%d %H:%M:%S")),
         "Rechner: %s, Python %s" % (platform.platform(), platform.python_version()), ""]
    L.append("ERGEBNIS (die Ursachen)")
    L += ["- " + d["text"] for d in diagnosis] or ["- noch keine Prüfung gelaufen"]
    L += ["", "ARBEITSPLAN (von oben nach unten abarbeiten; der Helfer hat nichts geändert, das machst du selbst)"]
    for n, st in enumerate(build_plan(diagnosis, ips), 1):
        L.append("%d. %s" % (n, st["text"]))
        if st.get("cmd"):
            L.append("     Befehl:   " + st["cmd"])
        if st.get("expect"):
            L.append("     Erwartet: " + st["expect"])
    L += ["", "PRÜFUNGEN"]
    for f in findings:
        L.append("[%s] %s: %s" % (MARK.get(f["status"], "?"), f["title"], f["detail"]))
    L += ["", "HANDY-TEST (Adressen: %s)" % (", ".join("http://%s:%d" % (i, TEST_PORT) for i in ips) or "keine")]
    L += ["%s Verbindung von %s auf Port %s %s" % (e["time"], e["ip"], e["port"], e["path"]) for e in events] \
        or ["- es hat sich kein Gerät gemeldet"]
    L += ["", "NETZWERKDATEN", STATE.get("dump") or "- nicht gesammelt"]
    L += ["", "BEFEHLSPROTOKOLL (Ende)", LOG.text(120_000)]
    return redact("\n".join(L))


def save_report():
    text = build_report()
    path = os.path.join(LOG.dir, "bericht-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        LOG.write("Bericht konnte nicht gespeichert werden: %s" % e, "ERROR")
        path = None
    with LOCK:
        STATE["report"] = {"path": path, "time": time.strftime("%H:%M:%S"), "text": text}
    return STATE["report"]


# ---------- Abläufe im Hintergrund ----------

def background(fn, *args):
    """Startet fn im Hintergrund, aber nie zwei Abläufe gleichzeitig."""
    with LOCK:
        if STATE["running"]:
            return False
        STATE["running"] = True

    def work():
        try:
            fn(*args)
        except Exception:
            LOG.write("Ablauf abgestürzt:\n" + traceback.format_exc(), "ERROR")
            STATE["stage"] = "Es ist ein Fehler passiert. Der Bericht enthält die Einzelheiten."
        finally:
            with LOCK:
                STATE["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return True


def stage(text):
    STATE["stage"] = text
    LOG.write("== " + text)


def do_check():
    stage("Prüfe den Rechner …")
    run_checks()
    stage("Prüfung fertig.")


def do_auto():
    """Prüft nur, ändert nichts am Rechner. Startet den Handy-Test und schreibt den Bericht."""
    stage("Prüfe den Rechner …")
    run_checks()
    start_test()
    save_report()
    stage("Fertig. Jetzt den Handy-Test machen.")


def public_state():
    with LOCK:
        report = STATE["report"]
        return {
            "version": VERSION, "windows": IS_WINDOWS, "logfile": LOG.path, "logdir": LOG.dir,
            "running": STATE["running"], "stage": STATE["stage"], "checkedAt": STATE["checked_at"],
            "findings": STATE["findings"], "diagnosis": STATE["diagnosis"], "ip": STATE["ip"], "ips": STATE["ips"],
            "plan": build_plan(STATE["diagnosis"], STATE["ips"]) if STATE["findings"] else [],
            "phoneIp": STATE["phone_ip"], "testPort": TEST_PORT, "henriPort": HENRI_PORT,
            "test": {"active": TEST["active"], "events": list(TEST["events"])[-20:], "error": TEST["error"]},
            "report": None if not report else {"path": report["path"], "time": report["time"]},
        }


# ---------- Lokale Seite ----------

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
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % PANEL_PORT, "localhost:%d" % PANEL_PORT)

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
        if self.path == "/api/state":
            return self._send(200, public_state())
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "helfer.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Henri") != "1":
            return self._send(403, {"error": "forbidden"})
        data = self._json()
        if self.path == "/api/auto":
            return self._send(200, {"ok": background(do_auto)})
        if self.path == "/api/check":
            return self._send(200, {"ok": background(do_check)})
        if self.path == "/api/phone":
            ip = str(data.get("ip", "")).strip()
            if ip and not valid_ip(ip):
                return self._send(400, {"error": "invalid ip"})
            STATE["phone_ip"] = ip
            LOG.write("Handy-IP eingetragen: %s" % (ip or "(leer)"))
            return self._send(200, {"ok": background(do_check) if ip else True})
        if self.path == "/api/test/start":
            return self._send(200, {"ok": start_test(), "error": TEST["error"]})
        if self.path == "/api/test/stop":
            stop_test()
            return self._send(200, {"ok": True})
        if self.path == "/api/report":
            report = save_report()
            return self._send(200, {"ok": True, "path": report["path"], "text": report["text"]})
        if self.path == "/api/open-logs":
            open_folder(LOG.dir)
            return self._send(200, {"ok": True})
        if self.path == "/api/quit":
            self._send(200, {"ok": True})
            threading.Thread(target=shutdown, daemon=True).start()
            return
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def open_folder(path):
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: attribute nur unter Windows vorhanden
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        LOG.write("Ordner konnte nicht geöffnet werden: %s" % e, "WARN")


def shutdown(*_):
    LOG.write("Helfer wird beendet.")
    try:
        stop_test()
    finally:
        os._exit(0)


def main():
    LOG.write("Henri Windows-Helfer %s startet. %s, Python %s" % (VERSION, platform.platform(), platform.python_version()))
    try:
        panel = ThreadingHTTPServer(("127.0.0.1", PANEL_PORT), Panel)
    except OSError:
        print("Der Helfer läuft schon, öffne ihn im Browser.")
        webbrowser.open("http://127.0.0.1:%d" % PANEL_PORT)
        return
    atexit.register(stop_test)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    url = "http://127.0.0.1:%d" % PANEL_PORT
    print("Henri Windows-Helfer läuft: " + url)
    print("Protokolle liegen in: " + LOG.dir)
    print("Dieses Fenster offen lassen. Zum Beenden: Strg+C oder auf der Seite \"Helfer beenden\".")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    panel.serve_forever()


if __name__ == "__main__":
    main()
