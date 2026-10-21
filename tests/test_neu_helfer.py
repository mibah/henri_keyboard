"""Neu: Windows-Helfer (windows-helfer/helfer.py), eigenständig neben App, Server und Steuerung.

Läuft auf jedem System: Die Windows-Abfragen (PowerShell) werden durch nachgestellte Antworten ersetzt.
Echte Windows-Läufe ersetzt das nicht, es sichert Logik, Auswertung, Schutz und Protokoll ab.
"""
import json
import os
import re
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import helpers
from helpers import http

HELFER_DIR = os.path.join(helpers.ROOT, "windows-helfer")
if HELFER_DIR not in sys.path:
    sys.path.insert(0, HELFER_DIR)
import helfer  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def fake_run(table, rc=0):
    """Ersetzt helfer.run: antwortet je nach Textteil im PowerShell-Skript mit einer festen Ausgabe."""
    calls = []

    def run(cmd, timeout=40, keep=2000):
        script = cmd[-1] if cmd and cmd[0] == "powershell.exe" else ""
        calls.append(script)
        for key, out in table.items():
            if key in script:
                return {"rc": rc, "out": out if isinstance(out, str) else json.dumps(out), "err": "", "secs": 0.0}
        return {"rc": 0, "out": "", "err": "", "secs": 0.0}
    run.calls = calls
    return run


class HelferCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patches = [
            mock.patch.object(helfer, "LOG", helfer.Log(self._tmp.name)),
            mock.patch.object(helfer, "IS_WINDOWS", True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        helfer.STATE.update(running=False, stage="", findings=[], diagnosis=[], ip=None, ips=[], checked_at=None,
                            report=None, phone_ip="", dump="")
        helfer.TEST.update(server=None, events=[], error=None, timer=None, active=False)
        helfer.CTX.clear()
        self.addCleanup(helfer.stop_test)

    def checks(self, table, ctx=None, **patches):
        """Führt alle Prüfungen mit nachgestellten Windows-Antworten aus."""
        with mock.patch.object(helfer, "run", fake_run(table)):
            return {f["id"]: f for f in helfer.run_checks()}


GOOD_RULE = {"Name": "x", "Enabled": "True", "Direction": "Inbound", "Action": "Allow", "Profile": "Any",
             "Protocol": "TCP", "LocalPort": "8787 8788"}


class TestPruefungen(HelferCase):
    def fn(self, check_id):
        return next(f for i, t, w, f in helfer.CHECKS if i == check_id)

    def one(self, check_id, table, ctx=None):
        with mock.patch.object(helfer, "run", fake_run(table)):
            return self.fn(check_id)(ctx if ctx is not None else {})

    def test_server_laeuft(self):
        with mock.patch.object(helfer, "http_get", return_value=(200, '{"ok": true, "model": "gemma3:4b"}')):
            ctx = {}
            f = self.one("server", {}, ctx)
        self.assertEqual(f["status"], "ok")
        self.assertTrue(ctx["server_up"] and not ctx["hosted"])

    def test_server_cloud_erkannt(self):
        with mock.patch.object(helfer, "http_get", return_value=(200, '{"model": "llama (Cloud)"}')):
            ctx = {}
            self.one("server", {}, ctx)
        self.assertTrue(ctx["hosted"])

    def test_server_aus(self):
        with mock.patch.object(helfer, "http_get", return_value=(None, "refused")):
            f = self.one("server", {}, {})
        self.assertEqual(f["status"], "bad")
        self.assertIn("Starten", f["detail"])

    def test_ollama_zustaende(self):
        tags = json.dumps({"models": [{"name": "gemma3:4b"}]})
        with mock.patch.object(helfer, "http_get", return_value=(200, tags)):
            self.assertEqual(self.one("ollama", {})["status"], "ok")
        with mock.patch.object(helfer, "http_get", return_value=(200, json.dumps({"models": []}))):
            f = self.one("ollama", {})
            self.assertEqual(f["status"], "warn")
            self.assertIn("ollama pull", f["detail"])
        with mock.patch.object(helfer, "http_get", return_value=(None, "x")):
            self.assertEqual(self.one("ollama", {})["status"], "bad")
        self.assertEqual(self.one("ollama", {}, {"hosted": True})["status"], "info")

    def test_lauschen(self):
        key = "Get-NetTCPConnection -State Listen"
        ok = self.one("listen", {key: [{"LocalAddress": "0.0.0.0", "OwningProcess": 5, "Name": "python"}]}, {"server_up": True})
        self.assertEqual(ok["status"], "ok")
        lokal = self.one("listen", {key: [{"LocalAddress": "127.0.0.1", "OwningProcess": 5, "Name": "python"}]}, {"server_up": True})
        self.assertEqual(lokal["status"], "bad")
        fremd = self.one("listen", {key: [{"LocalAddress": "0.0.0.0", "OwningProcess": 5, "Name": "nginx"}]}, {"server_up": True})
        self.assertEqual(fremd["status"], "warn")
        self.assertEqual(self.one("listen", {}, {"server_up": False})["status"], "skip")

    def test_netzwerkadressen(self):
        rows = [{"IPAddress": "192.168.1.20", "InterfaceAlias": "WLAN"},
                {"IPAddress": "172.20.0.1", "InterfaceAlias": "vEthernet (WSL)"}]
        with mock.patch.object(helfer, "local_ip", return_value="192.168.1.20"):
            ctx = {}
            f = self.one("adapters", {"Get-NetIPAddress": rows}, ctx)
        self.assertEqual(f["status"], "ok")
        self.assertEqual(ctx["ips"], ["192.168.1.20"])
        with mock.patch.object(helfer, "local_ip", return_value="172.20.0.1"):
            f = self.one("adapters", {"Get-NetIPAddress": rows}, {})
        self.assertEqual(f["status"], "warn")
        self.assertIn("virtuellen", f["detail"])
        with mock.patch.object(helfer, "local_ip", return_value=None):
            self.assertEqual(self.one("adapters", {}, {})["status"], "bad")

    def test_mehrere_echte_netze_werden_gemeldet(self):
        rows = [{"IPAddress": "192.168.1.20", "InterfaceAlias": "Ethernet"},
                {"IPAddress": "192.168.1.30", "InterfaceAlias": "WLAN"}]
        with mock.patch.object(helfer, "local_ip", return_value="192.168.1.20"):
            ctx = {}
            f = self.one("adapters", {"Get-NetIPAddress": rows}, ctx)
        self.assertEqual(f["status"], "warn")
        self.assertEqual(ctx["ips"], ["192.168.1.20", "192.168.1.30"])

    def test_selbsttest(self):
        ctx = {"server_up": True, "ips": ["192.168.1.20"]}
        with mock.patch.object(helfer, "http_get", return_value=(200, "")):
            self.assertEqual(self.one("self", {}, dict(ctx))["status"], "ok")
        with mock.patch.object(helfer, "http_get", return_value=(None, "timeout")):
            self.assertEqual(self.one("self", {}, dict(ctx))["status"], "bad")
        self.assertEqual(self.one("self", {}, {"server_up": False})["status"], "skip")

    def test_firewall_regel(self):
        q = "Get-NetFirewallRule -DisplayName"
        self.assertEqual(self.one("fw_rule", {q: [GOOD_RULE]}, {"fw_enabled": True})["status"], "ok")
        fehlt = self.one("fw_rule", {}, {"fw_enabled": True})
        self.assertEqual(fehlt["status"], "bad")
        self.assertIn("fehlt", fehlt["detail"])
        aus = self.one("fw_rule", {q: [dict(GOOD_RULE, Enabled="False")]}, {"fw_enabled": True})
        self.assertEqual(aus["status"], "bad")
        self.assertIn("falsch", aus["detail"])
        for kaputt in (dict(GOOD_RULE, Direction="Outbound"), dict(GOOD_RULE, Action="Block"),
                       dict(GOOD_RULE, Protocol="UDP"), dict(GOOD_RULE, LocalPort="80"), dict(GOOD_RULE, Profile="Private")):
            with self.subTest(regel=kaputt):
                self.assertEqual(self.one("fw_rule", {q: [kaputt]}, {"fw_enabled": True})["status"], "bad")
        self.assertEqual(self.one("fw_rule", {}, {"fw_enabled": False})["status"], "info")
        alle = dict(GOOD_RULE, Profile="Domain, Private, Public")
        self.assertEqual(self.one("fw_rule", {q: [alle]}, {"fw_enabled": True})["status"], "ok")

    def test_sperrregeln(self):
        q = "-Action Block"
        python = {"Name": "{AAA}", "Display": "python.exe", "Profile": "Public", "Protocol": "TCP", "LocalPort": "Any",
                  "Program": "C:\\Python312\\python.exe"}
        harmlos = {"Name": "{BBB}", "Display": "Spiel", "Profile": "Any", "Protocol": "TCP", "LocalPort": "27015",
                   "Program": "C:\\Spiel\\spiel.exe"}
        bereich = {"Name": "{CCC}", "Display": "Bereich", "Profile": "Any", "Protocol": "TCP", "LocalPort": "8000-9000",
                   "Program": "Any"}
        ctx = {}
        f = self.one("fw_blocks", {q: [python, harmlos, bereich]}, ctx)
        self.assertEqual(f["status"], "bad")
        self.assertEqual(ctx["block_names"], ["{AAA}", "{CCC}"])
        self.assertIn("Abbrechen", f["detail"])
        ctx = {}
        self.assertEqual(self.one("fw_blocks", {q: [harmlos]}, ctx)["status"], "ok")
        self.assertEqual(ctx["block_names"], [])
        self.assertEqual(self.one("fw_blocks", {}, {})["status"], "ok")

    def test_sicherheitsprogramme(self):
        av = "AntiVirusProduct"
        self.assertEqual(self.one("antivirus", {av: [{"displayName": "Windows Defender"}]})["status"], "ok")
        f = self.one("antivirus", {av: [{"displayName": "Norton 360"}, {"displayName": "Windows Defender"}]})
        self.assertEqual(f["status"], "warn")
        self.assertIn("Norton 360", f["detail"])

    def test_einzelner_eintrag_statt_liste(self):
        # PowerShell liefert bei genau einem Treffer ein Objekt statt einer Liste.
        out = json.dumps({"displayName": "Windows Defender"})
        self.assertEqual(self.one("antivirus", {"AntiVirusProduct": out})["status"], "ok")

    def test_richtlinien(self):
        prof = "Get-NetFirewallProfile -PolicyStore ActiveStore"
        gpo = "PolicyStoreSourceType"
        ok = self.one("fw_policy", {prof: [{"Name": "Public", "Local": "True", "Inbound": "Block"}]})
        self.assertEqual(ok["status"], "ok")
        ignoriert = self.one("fw_policy", {prof: [{"Name": "Private", "Local": "False", "Inbound": "Block"}]})
        self.assertEqual(ignoriert["status"], "bad")
        self.assertIn("ignoriert", ignoriert["detail"])
        verwaltet = self.one("fw_policy", {prof: [{"Name": "Public", "Local": "NotConfigured", "Inbound": "Block"}],
                                           gpo: [{"Display": "Block App X"}]})
        self.assertEqual(verwaltet["status"], "warn")
        self.assertIn("Block App X", verwaltet["detail"])

    def test_internet(self):
        with mock.patch.object(helfer, "http_get", return_value=(200, "")):
            self.assertEqual(self.one("internet", {})["status"], "ok")
        with mock.patch.object(helfer, "http_get", return_value=(None, "x")):
            self.assertEqual(self.one("internet", {})["status"], "warn")

    def test_netzwerkdaten_werden_gesammelt_und_namen_geschuetzt(self):
        fake = fake_run({"Get-NetAdapter": "Ethernet Up 1 Gbps", "Sicherheitsprozesse": "x",
                         "ProcessName -match": "avast\nnorton"})
        calls = []

        def run(cmd, timeout=40, keep=2000):
            calls.append(list(cmd))
            if cmd[0] == "ipconfig":
                return {"rc": 0, "out": "Physische Adresse: AA-BB-CC-DD-EE-FF\nIPv4: 192.168.1.20", "err": "", "secs": 0}
            return fake(cmd, timeout)
        with mock.patch.object(helfer, "run", run):
            f = self.fn("dump")({})
        self.assertEqual(f["status"], "info")
        self.assertIn("avast norton", f["detail"])
        self.assertTrue(any(c[0] == "ipconfig" for c in calls))
        self.assertTrue(any(c[0] == "arp" for c in calls))
        self.assertIn("192.168.1.20", helfer.STATE["dump"])
        self.assertNotIn("AA-BB-CC-DD-EE-FF", helfer.STATE["dump"])
        self.assertIn("<mac>", helfer.STATE["dump"])
        self.assertIn("NETZWERKDATEN", helfer.build_report())

    def test_handy_im_netz(self):
        def run_with(ping_rc, arp_out):
            def run(cmd, timeout=40, keep=2000):
                if cmd[0] == "ping":
                    return {"rc": ping_rc, "out": "", "err": "", "secs": 0}
                return {"rc": 0, "out": arp_out, "err": "", "secs": 0}
            return run
        ctx = {"ips": ["192.168.1.20"]}
        helfer.STATE["phone_ip"] = "192.168.1.42"
        with mock.patch.object(helfer, "run", run_with(0, "")):
            self.assertEqual(self.fn("phone")(dict(ctx))["status"], "ok")
        with mock.patch.object(helfer, "run", run_with(1, "192.168.1.42   aa-bb-cc-dd-ee-01   dynamisch")):
            f = self.fn("phone")(dict(ctx))
            self.assertEqual(f["status"], "ok")
            self.assertIn("antwortet aber nicht auf Ping", f["detail"])
        with mock.patch.object(helfer, "run", run_with(1, "192.168.1.42   ff-ff-ff-ff-ff-ff   statisch")):
            self.assertEqual(self.fn("phone")(dict(ctx))["status"], "bad")
        with mock.patch.object(helfer, "run", run_with(1, "")):
            f = self.fn("phone")(dict(ctx))
            self.assertEqual(f["status"], "bad")
            self.assertIn("Router", f["detail"])
        helfer.STATE["phone_ip"] = "192.168.9.39"
        with mock.patch.object(helfer, "run", run_with(0, "")):
            f = self.fn("phone")(dict(ctx))
            self.assertEqual(f["status"], "warn")
            self.assertIn("anderen Netz", f["detail"])

    def test_handy_ip_eingabe(self):
        self.assertEqual(self.one("phone", {}, {})["status"], "skip")
        helfer.STATE["phone_ip"] = "kein-ip; rm -rf /"
        self.assertEqual(self.one("phone", {}, {})["status"], "warn")
        for good in ("192.168.1.42", "10.0.0.1", "255.255.255.255"):
            self.assertTrue(helfer.valid_ip(good), good)
        for bad in ("", "1.2.3", "256.1.1.1", "1.2.3.4.5", "a.b.c.d", "1.2.3.4; dir", " 1.2.3.4 x"):
            self.assertFalse(helfer.valid_ip(bad), bad)

    def test_nicht_windows_wird_uebersprungen(self):
        with mock.patch.object(helfer, "IS_WINDOWS", False), \
                mock.patch.object(helfer, "http_get", return_value=(None, "x")), \
                mock.patch.object(helfer, "run", side_effect=AssertionError("kein Befehl ausserhalb Windows")):
            result = {f["id"]: f for f in helfer.run_checks()}
        for i in ("listen", "profile", "fw_state", "fw_rule", "fw_blocks", "antivirus", "fw_policy", "dump"):
            self.assertEqual(result[i]["status"], "skip", i)

    def test_abgestuerzte_pruefung_bringt_nicht_alles_zum_absturz(self):
        boom = mock.Mock(side_effect=RuntimeError("kaputt"))
        patched = [(i, t, w, boom if i == "profile" else f) for i, t, w, f in helfer.CHECKS]
        with mock.patch.object(helfer, "CHECKS", patched), mock.patch.object(helfer, "run", fake_run({})), \
                mock.patch.object(helfer, "http_get", return_value=(None, "x")):
            result = {f["id"]: f for f in helfer.run_checks()}
        self.assertEqual(result["profile"]["status"], "warn")
        self.assertIn("system", result)
        self.assertIn("RuntimeError", helfer.LOG.text())

    def test_powershell_fehler_werden_zu_warnung_nicht_absturz(self):
        with mock.patch.object(helfer, "run", return_value={"rc": 1, "out": "", "err": "boese", "secs": 0}), \
                mock.patch.object(helfer, "http_get", return_value=(None, "x")):
            result = {f["id"]: f for f in helfer.run_checks()}
        self.assertEqual(result["fw_state"]["status"], "warn")
        self.assertIn("fw_rule", result)


class TestAuswertung(HelferCase):
    def f(self, id, status, solution=None):
        return {"id": id, "title": id, "status": status, "detail": "", "solution": solution or []}

    def test_alles_gut(self):
        d = helfer.diagnose([self.f("server", "ok"), self.f("fw_rule", "ok"), self.f("self", "ok")])
        self.assertEqual(len(d), 1)
        self.assertIn("Handy-Test", d[0]["text"])
        self.assertTrue(d[0]["solution"], "auch wenn am Rechner alles stimmt, gibt es nächste Schritte")

    def test_sperrregel_und_regel_mit_loesungen(self):
        blocks, rule = [helfer.S("a", "x")], [helfer.S("b", "y")]
        d = helfer.diagnose([self.f("fw_blocks", "bad", blocks), self.f("fw_rule", "bad", rule)])
        self.assertEqual([x["solution"] for x in d], [blocks, rule])
        self.assertIn("Sperrregel", d[0]["text"])
        self.assertIn("Regel", d[1]["text"])

    def test_server_aus_zuerst(self):
        d = helfer.diagnose([self.f("server", "bad", [helfer.S("Starten")])])
        self.assertIn("läuft nicht", d[0]["text"])
        self.assertEqual(d[0]["solution"][0]["text"], "Starten")

    def test_selbst_nicht_erreichbar_ohne_bekannte_ursache(self):
        d = helfer.diagnose([self.f("self", "bad"), self.f("fw_rule", "ok")])
        self.assertIn("Sicherheitsprogramm", d[0]["text"])

    def test_handy_nicht_sichtbar_und_richtlinie(self):
        d = helfer.diagnose([self.f("phone", "bad")])
        self.assertTrue(any("Router" in x["text"] or "Netz" in x["text"] for x in d))
        d = helfer.diagnose([self.f("fw_policy", "bad"), self.f("self", "bad")])
        self.assertTrue(any("Richtlinie" in x["text"] for x in d))

    def test_fremde_firewall_ersetzt_die_windows_firewall(self):
        d = helfer.diagnose([self.f("fw_rule", "info"), self.f("antivirus", "warn", [helfer.S("x")])])
        self.assertIn("ersetzt", d[0]["text"])
        d = helfer.diagnose([self.f("fw_rule", "ok"), self.f("antivirus", "warn")])
        self.assertNotIn("ersetzt", d[0]["text"])

    def test_eset_hinweis(self):
        hint = helfer.av_hint(["ESET Internet Security"])
        self.assertIn("Heim- oder Büronetzwerk", hint)
        self.assertIn("8787", hint)

    def test_modell_fehlt_wird_genannt(self):
        d = helfer.diagnose([self.f("ollama", "warn")])
        self.assertTrue(any("Modell" in x["text"] for x in d))


class TestLoesungen(HelferCase):
    def f(self, id, status):
        return {"id": id, "title": id, "status": status, "detail": "", "solution": []}

    def texts(self, id, status, ctx=None):
        steps = helfer.solutions_for(self.f(id, status), ctx or {})
        return steps, " ".join((x["text"] + " " + (x["cmd"] or "")) for x in steps)

    def test_fehlende_regel_befehl_zum_kopieren(self):
        steps, text = self.texts("fw_rule", "bad")
        cmds = [x["cmd"] for x in steps if x["cmd"]]
        self.assertEqual(cmds, ['netsh advfirewall firewall add rule name="Henri Proxy" dir=in action=allow protocol=TCP '
                                'localport=8787,8788 profile=any',
                                'netsh advfirewall firewall show rule name="Henri Proxy"'])
        self.assertIn("Administrator", text)
        self.assertIn("OK.", " ".join(x["expect"] or "" for x in steps))

    def test_sperrregeln_befehle_pro_regel_und_maskiert(self):
        steps, text = self.texts("fw_blocks", "bad", {"block_names": ["{AAA}", "{B'B}"]})
        cmds = [x["cmd"] for x in steps if x["cmd"]]
        self.assertEqual(cmds, ["Remove-NetFirewallRule -Name '{AAA}'", "Remove-NetFirewallRule -Name '{B''B}'"])

    def test_richtlinie_verweist_an_verwalter_und_tunnel(self):
        steps, text = self.texts("fw_policy", "bad")
        self.assertIn("Verwalter", text)
        self.assertIn("cloudflared", text)

    def test_tunnel_befehl_ohne_leerzeichen_vor_dem_und_zeichen(self):
        # "set X=a && ..." würde ein Leerzeichen in den Wert schreiben (set APP_TOKEN=... ).
        cmds = [x["cmd"] for x in helfer.TUNNEL if x["cmd"]]
        server = next(c for c in cmds if "APP_TOKEN" in c)
        self.assertNotIn(" &&", server)
        self.assertIn("python server.py", server)
        self.assertTrue(any(c.startswith("cloudflared.exe tunnel --url http://localhost:8787") for c in cmds))
        self.assertTrue(any(c.startswith("curl.exe -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/")
                            for c in cmds), "das Programm lässt sich mit einem Befehl laden")
        text = " ".join(x["text"] for x in helfer.TUNNEL)
        self.assertIn("Token", text)
        self.assertIn("beenden", text, "Port 8787 muss vorher frei sein")

    def test_jede_loesung_ist_text_oder_befehl_zum_kopieren(self):
        for id, status in [("server", "bad"), ("ollama", "bad"), ("ollama", "warn"), ("listen", "bad"), ("listen", "warn"),
                           ("adapters", "warn"), ("adapters", "bad"), ("fw_rule", "bad"), ("fw_blocks", "bad"),
                           ("fw_policy", "bad"), ("fw_policy", "warn"), ("antivirus", "warn"), ("self", "bad"),
                           ("phone", "bad"), ("phone", "warn")]:
            steps, _ = self.texts(id, status, {"block_names": ["{A}"]})
            with self.subTest(pruefung=id, status=status):
                self.assertTrue(steps)
                for st in steps:
                    self.assertTrue(st["text"])
                    self.assertIn("cmd", st)

    def test_keine_loesung_bei_ok_info_skip(self):
        for status in ("ok", "info", "skip"):
            self.assertEqual(helfer.solutions_for(self.f("fw_rule", status), {}), [])

    def test_loesungen_stehen_in_pruefung_und_bericht(self):
        table = {"Get-NetFirewallProfile -PolicyStore ActiveStore": [{"Name": "Public", "Local": "True", "Inbound": "Block"}],
                 "Get-NetFirewallProfile -ErrorAction": [{"Name": "Public", "Enabled": "True"}]}
        with mock.patch.object(helfer, "run", fake_run(table)), mock.patch.object(helfer, "http_get", return_value=(None, "x")):
            result = {f["id"]: f for f in helfer.run_checks()}
        rule = result["fw_rule"]
        self.assertEqual(rule["status"], "bad")
        self.assertTrue(any(st["cmd"] and "netsh advfirewall firewall add rule" in st["cmd"] for st in rule["solution"]))
        text = helfer.build_report()
        self.assertIn("ARBEITSPLAN", text)
        self.assertIn("Befehl:   netsh advfirewall firewall add rule", text)
        self.assertIn("Erwartet: ", text)
        self.assertNotIn("BEHOBEN", text)

    def test_jeder_befehl_hat_ein_erwartetes_ergebnis(self):
        """Damit beim Abarbeiten immer klar ist, woran man erkennt, dass ein Schritt geklappt hat."""
        steps = list(helfer.TUNNEL) + list(helfer.ALL_GOOD)
        for id, status in [("server", "bad"), ("ollama", "bad"), ("ollama", "warn"), ("listen", "bad"), ("listen", "warn"),
                           ("adapters", "warn"), ("adapters", "bad"), ("fw_rule", "bad"), ("fw_blocks", "bad"),
                           ("fw_policy", "bad"), ("fw_policy", "warn"), ("antivirus", "warn"), ("self", "bad"),
                           ("phone", "bad"), ("phone", "warn")]:
            steps += helfer.solutions_for(self.f(id, status), {"block_names": ["{A}"], "av_names": ["Norton 360"]})
        steps += helfer.build_plan([], ["192.168.1.20"])
        self.assertGreater(len(steps), 30)
        for st in steps:
            if st["cmd"]:
                with self.subTest(befehl=st["cmd"][:60]):
                    self.assertTrue(st["expect"], "Befehl ohne „Erwartet“")

    def test_plan_ohne_doppelte_tunnel_zuletzt_mit_abschluss(self):
        d1 = {"text": "a", "solution": [helfer.S("Schritt A", "cmd a", "ok a"), helfer.TUNNEL[0]]}
        d2 = {"text": "b", "solution": [helfer.S("Schritt A", "cmd a", "ok a"), helfer.TUNNEL[0], helfer.S("Schritt B")]}
        plan = helfer.build_plan([d1, d2], ["192.168.1.20"])
        texts = [st["text"] for st in plan]
        self.assertEqual(texts.count("Schritt A"), 1)
        self.assertEqual(texts.count(helfer.TUNNEL[0]["text"]), 1)
        self.assertLess(texts.index("Schritt B"), next(i for i, t in enumerate(texts) if t.startswith("ABSCHLUSS")),
                        "erst die Reparaturen, dann der Abschluss")
        abschluss = next(i for i, t in enumerate(texts) if t.startswith("ABSCHLUSS"))
        tunnel = texts.index(helfer.TUNNEL[0]["text"])
        self.assertGreater(tunnel, abschluss, "der Tunnel ist der letzte Ausweg und steht hinter der Prüfung")
        self.assertTrue(any(t.startswith("NUR WENN ES NACH ALLEM DAVOR") for t in texts[abschluss:tunnel]))
        cmds = [st["cmd"] for st in plan if st["cmd"]]
        self.assertIn("curl.exe http://192.168.1.20:8787/health", cmds)
        self.assertIn("http://192.168.1.20:8787", texts[abschluss + 2])
        self.assertIn("einfügen", texts[-1], "letzter Schritt: neuen Bericht einfügen")

    def test_ohne_tunnelbedarf_kein_tunnel_im_plan(self):
        plan = helfer.build_plan([{"text": "x", "solution": [helfer.S("Nur das")]}], ["192.168.1.20"])
        self.assertFalse(any("TUNNEL" in st["text"] for st in plan))
        self.assertIn("<IP des Rechners>", helfer.build_plan([], [])[0]["cmd"])

    def test_alle_tunnelschritte_sind_markiert(self):
        self.assertTrue(all(st["fallback"] for st in helfer.TUNNEL))
        steps = helfer.solutions_for(self.f("fw_policy", "bad"), {})
        self.assertTrue(any(st["fallback"] for st in steps))
        self.assertFalse(any(st["fallback"] for st in helfer.solutions_for(self.f("fw_rule", "bad"), {})))

    def test_sicherheitsprogramm_hinweis_je_produkt(self):
        self.assertIn("Norton", helfer.av_hint(["Norton 360"]))
        self.assertIn("8787", helfer.av_hint(["McAfee Total Protection"]))
        self.assertIn("Firewall", helfer.av_hint(["Unbekanntes Programm"]))
        steps = helfer.solutions_for(self.f("antivirus", "warn"), {"av_names": ["Kaspersky Internet Security"]})
        self.assertTrue(any("Kaspersky" in st["text"] for st in steps))
        self.assertTrue(any("10 Minuten" in st["text"] for st in steps), "erst testen, ob das Programm schuld ist")


class TestNurLesend(HelferCase):
    """Der Helfer darf am Rechner nichts ändern: keine Regeln, keine Einstellungen, keine Administrator-Rechte."""

    CHANGING = re.compile(r"New-NetFirewallRule|Remove-NetFirewallRule|Set-NetFirewall|Enable-NetFirewall|Disable-NetFirewall|"
                          r"netsh\s+advfirewall\s+(firewall\s+(add|delete|set)|set)|Start-Process|RunAs|Set-ItemProperty|"
                          r"New-ItemProperty|Remove-Item|reg\s+(add|delete)|sc\s+(config|stop)|Stop-Process|Set-NetConnectionProfile|Restart-")

    def test_kein_befehl_aendert_etwas_im_ganzen_ablauf(self):
        seen = []

        def spy(cmd, timeout=40, keep=2000):
            seen.append(" ".join(str(c) for c in cmd))
            script = cmd[-1] if cmd and cmd[0] == "powershell.exe" else ""
            if "Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True" in script and "ActiveStore" not in script:
                return {"rc": 0, "out": json.dumps([{"Name": "{A}", "Display": "python.exe", "Profile": "Public", "Protocol": "TCP",
                                                     "LocalPort": "Any", "Program": "C:\\py\\python.exe"}]), "err": "", "secs": 0}
            return {"rc": 0, "out": "", "err": "", "secs": 0}
        helfer.STATE["phone_ip"] = "192.168.1.42"
        with mock.patch.object(helfer, "run", spy), mock.patch.object(helfer, "http_get", return_value=(None, "x")), \
                mock.patch.object(helfer, "start_test"):
            helfer.do_auto()
        self.assertGreater(len(seen), 10, "es wurden Abfragen ausgeführt")
        for cmd in seen:
            self.assertIsNone(self.CHANGING.search(cmd), cmd)
        self.assertTrue(helfer.STATE["findings"])

    def test_quelltext_hat_keine_reparatur_und_keine_rechteerhoehung(self):
        src = helpers.read("windows-helfer", "helfer.py")
        for name in ("elevated_ps", "apply_fixes", "do_fix", "fixable", "rule_script"):
            self.assertFalse(hasattr(helfer, name), name)
        for text in ("-Verb RunAs", "Start-Process", "New-NetFirewallRule", "Set-NetFirewall", "tempfile.mkdtemp", "shutil"):
            self.assertNotIn(text, src)

    def test_befehle_zum_kopieren_werden_nie_ausgefuehrt(self):
        # Alles in S(...) ist nur Text. Es darf keinen Weg geben, einen Lösungsbefehl auszuführen.
        src = helpers.read("windows-helfer", "helfer.py")
        for m in re.finditer(r"(run|ps|ps_json)\(\s*\[?\s*(st|step|x)\[", src):
            self.fail("Lösungsbefehl wird ausgeführt: " + m.group(0))

    def test_alte_endpunkte_zum_beheben_gibt_es_nicht_mehr(self):
        for name in ("do_fix_all",):
            self.assertFalse(hasattr(helfer, name))


class TestHandyTest(HelferCase):
    def test_verbindung_wird_gemeldet(self):
        port = free_port()
        with mock.patch.object(helfer, "TEST_PORT", port), mock.patch.object(helfer, "IS_WINDOWS", False):
            self.assertTrue(helfer.start_test())
            with urllib.request.urlopen("http://127.0.0.1:%d/hallo" % port, timeout=5) as r:
                page = r.read().decode()
            self.assertIn("Verbindung klappt", page)
            self.assertEqual(len(helfer.TEST["events"]), 1)
            ev = helfer.TEST["events"][0]
            self.assertEqual((ev["ip"], ev["port"], ev["path"]), ("127.0.0.1", port, "/hallo"))
            helfer.stop_test()
            self.assertFalse(helfer.TEST["active"])
            with self.assertRaises(OSError):
                urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2)

    def test_belegter_port_gibt_meldung_statt_absturz(self):
        blocker = socket.socket()
        blocker.bind(("0.0.0.0", 0))
        blocker.listen(1)
        try:
            with mock.patch.object(helfer, "TEST_PORT", blocker.getsockname()[1]):
                self.assertFalse(helfer.start_test())
            self.assertIn("belegt", helfer.TEST["error"])
        finally:
            blocker.close()

    def test_mehrfach_starten_ist_harmlos(self):
        port = free_port()
        with mock.patch.object(helfer, "TEST_PORT", port), mock.patch.object(helfer, "IS_WINDOWS", False):
            self.assertTrue(helfer.start_test())
            self.assertTrue(helfer.start_test())
            helfer.stop_test()
            helfer.stop_test()


class TestBericht(HelferCase):
    def test_bericht_enthaelt_alles_und_schuetzt_namen(self):
        with mock.patch.object(helfer, "_private_words", return_value=[("MaxMuster", "<benutzer>"), ("MEINPC", "<rechner>")]):
            helfer.STATE.update(findings=[{"id": "x", "title": "Pfad", "status": "bad",
                                           "detail": "C:\\Users\\MaxMuster\\python.exe auf MEINPC", "solution": []}],
                                diagnosis=[{"text": "Etwas ist kaputt.", "solution": [helfer.S("Mach X", "befehl --y")]}],
                                ips=["192.168.1.20"])
            helfer.add_event("192.168.1.42", 8788, "/")
            helfer.LOG.write("Befehl lief als MaxMuster")
            text = helfer.build_report()
        for part in ("ERGEBNIS", "PRÜFUNGEN", "ARBEITSPLAN", "Befehl:   befehl --y", "HANDY-TEST", "BEFEHLSPROTOKOLL", "Etwas ist kaputt.",
                     "192.168.1.42", "http://192.168.1.20:8788"):
            self.assertIn(part, text)
        self.assertNotIn("MaxMuster", text)
        self.assertNotIn("MEINPC", text)
        self.assertIn("<benutzer>", text)

    def test_namen_werden_nur_als_ganze_woerter_ersetzt(self):
        with mock.patch.object(helfer, "_private_words", return_value=[("mac", "<rechner>")]):
            self.assertEqual(helfer.redact("macOS auf mac, machen Mac-Pro"), "macOS auf <rechner>, machen <rechner>-Pro")
            self.assertEqual(helfer.redact("C:\\Users\\mac\\x.exe"), "C:\\Users\\<rechner>\\x.exe")

    def test_mac_adressen_werden_unkenntlich(self):
        self.assertEqual(helfer.redact("a AA-BB-CC-DD-EE-FF b 1:2:3:4:5:6 c"), "a <mac> b <mac> c")

    def test_bericht_wird_gespeichert(self):
        report = helfer.save_report()
        self.assertTrue(os.path.exists(report["path"]))
        self.assertEqual(os.path.dirname(report["path"]), self._tmp.name)
        with open(report["path"], encoding="utf-8") as f:
            self.assertEqual(f.read(), report["text"])

    def test_protokoll_schreibt_datei_und_kuerzt_den_speicher(self):
        helfer.LOG.write("hallo")
        with open(helfer.LOG.path, encoding="utf-8") as f:
            self.assertIn("hallo", f.read())
        helfer.LOG.MAX = 500
        for i in range(100):
            helfer.LOG.write("x" * 50)
        self.assertLessEqual(len("\n".join(helfer.LOG.lines)), 800)

    def test_befehl_ohne_programm_wirft_nicht(self):
        with mock.patch.object(helfer, "IS_WINDOWS", False):
            r = helfer.run(["gibt-es-nicht-xyz"])
        self.assertIsNone(r["rc"])
        self.assertIn("FileNotFoundError", r["err"])
        self.assertIn("gibt-es-nicht-xyz", helfer.LOG.text())

    def test_befehl_zeitueberschreitung(self):
        with mock.patch.object(helfer, "IS_WINDOWS", False):
            r = helfer.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
        self.assertIsNone(r["rc"])
        self.assertIn("Zeitüberschreitung", r["err"])

    def test_http_get_ignoriert_system_proxy(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1"}):
            port = free_port()
            httpd = ThreadingHTTPServer(("127.0.0.1", port), helfer.TestHandler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                self.assertEqual(helfer.http_get("http://127.0.0.1:%d/" % port)[0], 200)
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestSeite(HelferCase):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), helfer.Panel)
        self.port = self.httpd.server_address[1]
        self._port = mock.patch.object(helfer, "PANEL_PORT", self.port)
        self._port.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.port
        self.hdr = {"X-Henri": "1"}

    def tearDown(self):
        self._port.stop()
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_startseite_und_zustand(self):
        code, html = http("GET", self.base + "/")
        self.assertEqual(code, 200)
        self.assertIn("Alles prüfen", html)
        self.assertIn("ändert nichts", html)
        self.assertNotIn("einrichten", html.lower())
        code, d = http("GET", self.base + "/api/state")
        self.assertEqual(code, 200)
        for key in ("version", "windows", "running", "findings", "diagnosis", "plan", "ips", "test", "logfile", "report"):
            self.assertIn(key, d)

    def test_schutz_der_seite(self):
        self.assertEqual(http("GET", self.base + "/api/state", headers={"Host": "boese.example"})[0], 403)
        for path in ("/api/auto", "/api/check", "/api/phone", "/api/test/start", "/api/report", "/api/quit", "/api/open-logs"):
            with self.subTest(pfad=path):
                self.assertEqual(http("POST", self.base + path, {})[0], 403)
                self.assertEqual(http("POST", self.base + path, {}, {"Host": "boese.example", **self.hdr})[0], 403)

    def test_unbekanntes_und_keine_reparatur_endpunkte(self):
        self.assertEqual(http("GET", self.base + "/api/nix")[0], 404)
        self.assertEqual(http("POST", self.base + "/api/nix", {}, self.hdr)[0], 404)
        for path in ("/api/fix", "/api/fixall", "/api/repair"):
            self.assertEqual(http("POST", self.base + path, {"id": "firewall_rule"}, self.hdr)[0], 404, path)

    def test_nur_ein_ablauf_gleichzeitig(self):
        gate, started = threading.Event(), threading.Event()
        with mock.patch.object(helfer, "do_check", side_effect=lambda: (started.set(), gate.wait(3))):
            self.assertEqual(http("POST", self.base + "/api/check", {}, self.hdr), (200, {"ok": True}))
            self.assertTrue(started.wait(2))
            self.assertEqual(http("POST", self.base + "/api/auto", {}, self.hdr), (200, {"ok": False}))
            self.assertTrue(http("GET", self.base + "/api/state")[1]["running"])
            gate.set()
        for _ in range(40):
            if not helfer.STATE["running"]:
                break
            threading.Event().wait(0.05)
        self.assertFalse(helfer.STATE["running"])

    def test_abgestuerzter_ablauf_gibt_den_zustand_frei(self):
        done = threading.Event()

        def boom():
            done.set()
            raise RuntimeError("kaputt")
        with mock.patch.object(helfer, "do_check", side_effect=boom):
            http("POST", self.base + "/api/check", {}, self.hdr)
            self.assertTrue(done.wait(2))
            for _ in range(40):
                if not helfer.STATE["running"]:
                    break
                threading.Event().wait(0.05)
        self.assertFalse(helfer.STATE["running"])
        self.assertIn("Fehler", helfer.STATE["stage"])

    def test_handy_ip_endpunkt(self):
        self.assertEqual(http("POST", self.base + "/api/phone", {"ip": "nope; dir"}, self.hdr)[0], 400)
        self.assertEqual(helfer.STATE["phone_ip"], "")
        with mock.patch.object(helfer, "do_check"):
            self.assertEqual(http("POST", self.base + "/api/phone", {"ip": "192.168.1.42"}, self.hdr)[0], 200)
        self.assertEqual(helfer.STATE["phone_ip"], "192.168.1.42")
        self.assertEqual(http("GET", self.base + "/api/state")[1]["phoneIp"], "192.168.1.42")
        helfer.STATE["phone_ip"] = ""

    def test_bericht_und_beenden(self):
        code, d = http("POST", self.base + "/api/report", {}, self.hdr)
        self.assertEqual(code, 200)
        self.assertIn("BEFEHLSPROTOKOLL", d["text"])
        done = threading.Event()
        with mock.patch.object(helfer, "shutdown", side_effect=lambda *a: done.set()):
            self.assertEqual(http("POST", self.base + "/api/quit", {}, self.hdr), (200, {"ok": True}))
            self.assertTrue(done.wait(2))

    def test_zustand_enthaelt_nicht_den_ganzen_bericht(self):
        helfer.save_report()
        d = http("GET", self.base + "/api/state")[1]
        self.assertNotIn("text", d["report"])

    def test_seite_enthaelt_die_bedienung(self):
        html = helpers.read("windows-helfer", "helfer.html")
        for part in ('id="autoBtn"', 'id="plan"', "Arbeitsplan", "Erwartet", "Kopieren", 'id="testStart"', 'id="repBtn"', 'id="phoneIp"', "/api/phone", "/api/auto", "/api/report", "X-Henri",
                     "ändert nichts", "Bericht kopieren"):
            self.assertIn(part, html)
        self.assertNotIn("innerHTML", html, "Daten dürfen nie als HTML eingefügt werden")
        for text in ("/api/fix", "fixBtn", "Administrator-Rückfrage", "So lösen"):
            self.assertNotIn(text, html)


class TestEigenstaendig(unittest.TestCase):
    def test_batchdatei(self):
        with open(os.path.join(HELFER_DIR, "Henri-Helfer.bat"), "rb") as f:
            raw = f.read()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        raw.decode("ascii")
        self.assertIn(b"helfer.py", raw)

    def test_liest_keine_schluessel_und_aendert_nichts_an_henri(self):
        src = helpers.read("windows-helfer", "helfer.py")
        self.assertNotIn("henri-config", src)
        self.assertNotIn("Set-NetFirewallProfile", src)
        self.assertNotIn("netsh advfirewall set", src)
        self.assertNotIn("import server", src)
        self.assertNotIn("import launcher", src)

    def test_nur_standardbibliothek(self):
        src = helpers.read("windows-helfer", "helfer.py")
        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        if stdlib is None:
            self.skipTest("Python < 3.10")
        for mod in re.findall(r"^(?:import|from)\s+([a-zA-Z_]+)", src, re.M):
            self.assertIn(mod, stdlib, mod)

    def test_protokollordner_nicht_im_git(self):
        self.assertIn("windows-helfer/protokoll/", helpers.read(".gitignore"))


if __name__ == "__main__":
    unittest.main()
