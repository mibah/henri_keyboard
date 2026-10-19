"""Bestand: Steuerung (proxy/launcher.py) – Zustände, Sicherheit der Seite, Start und Beenden.

Läuft ohne Ollama: Ollama und Server werden ersetzt. Der volle Ablauf mit echtem Ollama steht in
test_bestand_integration.py.
"""
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("BROWSER", "true")
os.environ.setdefault("HENRI_CONFIG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-config.json"))

import helpers
from helpers import http

import launcher

OLD_STATUS_KEYS = {"phase", "step", "error", "pull", "ollama", "model", "modelName", "proxy", "external",
                   "url", "lastUse", "corrections"}


class TestStatus(unittest.TestCase):
    def setUp(self):
        with launcher.lock:
            launcher.state.update(phase="aus", step="", error="", pull=None)
        launcher.own["httpd"] = None

    def status(self, up=True, health=None, present=True):
        with mock.patch.object(launcher, "ollama_up", return_value=up), \
                mock.patch.object(launcher, "proxy_health", return_value=health), \
                mock.patch.object(launcher, "model_present", return_value=present):
            return launcher.status()

    def test_alle_bisherigen_felder(self):
        s = self.status(health={"corrections": 3, "last_correction_ago": 5})
        self.assertTrue(OLD_STATUS_KEYS <= set(s), OLD_STATUS_KEYS - set(s))

    def test_bereit_wenn_alles_laeuft(self):
        s = self.status(health={"corrections": 3, "last_correction_ago": 5})
        self.assertEqual(s["phase"], "bereit")
        self.assertTrue(s["ollama"] and s["model"] and s["proxy"])
        self.assertEqual((s["corrections"], s["lastUse"]), (3, 5))
        self.assertTrue(s["external"], "ein nicht selbst gestarteter Server gilt als extern")

    def test_nicht_bereit(self):
        self.assertEqual(self.status(up=False, health={})["phase"], "aus")
        self.assertEqual(self.status(health=None)["phase"], "aus")
        self.assertEqual(self.status(present=False, health={})["phase"], "aus")

    def test_ohne_server_keine_zahlen(self):
        s = self.status(health=None)
        self.assertFalse(s["proxy"])
        self.assertIsNone(s["lastUse"])
        self.assertEqual(s["corrections"], 0)

    def test_startet_bleibt_startet(self):
        launcher.update(phase="startet", step="Ollama wird gestartet …")
        s = self.status(up=False, health=None)
        self.assertEqual(s["phase"], "startet")
        self.assertEqual(s["step"], "Ollama wird gestartet …")

    def test_fehler_bleibt_stehen(self):
        launcher.update(phase="fehler", error="Ollama ist nicht installiert.")
        s = self.status(up=False, health=None)
        self.assertEqual((s["phase"], s["error"]), ("fehler", "Ollama ist nicht installiert."))

    def test_gestoppt_nach_bereit(self):
        launcher.update(phase="bereit")
        self.assertEqual(self.status(health=None)["phase"], "aus")

    def test_adresse_fuers_handy(self):
        s = self.status(health={})
        if s["url"] is not None:
            self.assertRegex(s["url"], r"^http://\d+\.\d+\.\d+\.\d+:%d$" % launcher.PROXY_PORT)


class TestHilfen(unittest.TestCase):
    def test_modell_vorhanden(self):
        tags = {"models": [{"name": "gemma3:4b"}, {"name": "llama3:latest"}]}
        with mock.patch.object(launcher, "get_json", return_value=tags):
            self.assertTrue(launcher.model_present("gemma3:4b"))
            self.assertTrue(launcher.model_present("llama3"))
            self.assertFalse(launcher.model_present("qwen2.5:7b"))
        with mock.patch.object(launcher, "get_json", side_effect=OSError):
            self.assertFalse(launcher.model_present("gemma3:4b"))

    def test_ollama_nicht_da(self):
        with mock.patch.object(launcher, "get_json", side_effect=OSError):
            self.assertFalse(launcher.ollama_up())
            self.assertIsNone(launcher.proxy_health())

    def test_ollama_finden(self):
        with mock.patch("shutil.which", return_value="/x/ollama"):
            self.assertEqual(launcher.find_ollama(), "/x/ollama")
        with mock.patch("shutil.which", return_value=None), mock.patch("os.path.exists", return_value=False):
            self.assertIsNone(launcher.find_ollama())

    def test_warten(self):
        self.assertTrue(launcher.wait_for(lambda: True, 1))
        self.assertFalse(launcher.wait_for(lambda: False, 0.2))

    def test_lokale_ip(self):
        ip = launcher.local_ip()
        self.assertTrue(ip is None or ip.count(".") == 3)


class TestStartAblauf(unittest.TestCase):
    """start_all mit ersetztem Ollama: Fehlermeldungen, Modelle laden, Server starten."""

    def setUp(self):
        with launcher.lock:
            launcher.state.update(phase="aus", step="", error="", pull=None)
        launcher.own.update(httpd=None, ollama=None)
        self.addCleanup(self.stop)

    def stop(self):
        if launcher.own["httpd"] is not None:
            launcher.own["httpd"].shutdown()
            launcher.own["httpd"].server_close()
            launcher.own["httpd"] = None

    def run_start(self, real_health=False, **patches):
        """Ruft start_all mit ersetztem Ollama auf. Mit real_health antwortet der echte Server auf /health."""
        defaults = dict(ollama_up=True, model_present=True)
        if not real_health:
            defaults["proxy_health"] = None
        defaults.update(patches)
        ctx = []
        for k, v in defaults.items():
            ctx.append(mock.patch.object(launcher, k, side_effect=v) if isinstance(v, list) else mock.patch.object(launcher, k, return_value=v))
        for c in ctx:
            c.start()
            self.addCleanup(c.stop)
        launcher.start_all()
        return dict(launcher.state)

    def test_ollama_fehlt(self):
        with mock.patch.object(launcher, "find_ollama", return_value=None):
            st = self.run_start(ollama_up=False)
        self.assertEqual(st["phase"], "fehler")
        self.assertIn("Ollama ist nicht installiert", st["error"])

    def test_modell_wird_geladen_wenn_es_fehlt(self):
        pulled = []
        with mock.patch.object(launcher, "pull_model", side_effect=pulled.append), \
                mock.patch.object(launcher.server, "make_server") as make:
            make.return_value = mock.Mock(serve_forever=lambda: None)
            # erst „kein Server“, nach dem Start „gesund“
            st = self.run_start(model_present=False, proxy_health=[None, {}, {}, {}])
        self.assertEqual(pulled, list(launcher.MODELS))
        self.assertEqual(st["phase"], "bereit")

    def test_ladefehler_wird_erklaert(self):
        with mock.patch.object(launcher, "pull_model", side_effect=OSError):
            st = self.run_start(model_present=False)
        self.assertEqual(st["phase"], "fehler")
        self.assertIn("Sprachmodell konnte nicht geladen werden", st["error"])

    def test_port_belegt(self):
        with mock.patch.object(launcher.server, "make_server", side_effect=OSError):
            st = self.run_start()
        self.assertEqual(st["phase"], "fehler")
        self.assertIn("belegt", st["error"])

    def test_laeuft_schon_ein_server(self):
        st = self.run_start(proxy_health={})
        self.assertEqual(st["phase"], "bereit")
        self.assertIsNone(launcher.own["httpd"], "ein fremder Server wird nicht übernommen oder doppelt gestartet")

    def test_echter_serverstart_und_stopp(self):
        probe = launcher.server.make_server(0)
        port = probe.server_address[1]
        probe.server_close()
        with mock.patch.object(launcher, "PROXY_PORT", port):
            st = self.run_start(real_health=True)
            self.assertEqual((st["phase"], st["error"]), ("bereit", ""))
            self.assertIsNotNone(launcher.own["httpd"])
            code, health = http("GET", "http://127.0.0.1:%d/health" % port)
            self.assertEqual((code, health["ok"]), (200, True))
            launcher.stop_all()
            self.assertEqual(launcher.state["phase"], "aus")
            self.assertIsNone(launcher.own["httpd"])
            self.assertIsNone(launcher.proxy_health(), "nach dem Beenden antwortet der Server nicht mehr")


class PanelTestCase(unittest.TestCase):
    """Die lokale Steuerungsseite als echter HTTP-Server (ohne dass etwas gestartet wird)."""

    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Panel)
        self.port = self.httpd.server_address[1]
        self._port = mock.patch.object(launcher, "PANEL_PORT", self.port)
        self._port.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.port
        self.hdr = {"X-Henri": "1"}

    def tearDown(self):
        self._port.stop()
        self.httpd.shutdown()
        self.httpd.server_close()


class TestSeite(PanelTestCase):
    def test_startseite(self):
        code, html = http("GET", self.base + "/")
        self.assertEqual(code, 200)
        self.assertIn("Henri Tastatur", html)
        self.assertIn("Programm ganz beenden", html)

    def test_status_ist_json(self):
        code, d = http("GET", self.base + "/api/status")
        self.assertEqual(code, 200)
        self.assertTrue(OLD_STATUS_KEYS <= set(d))

    def test_unbekannt(self):
        self.assertEqual(http("GET", self.base + "/api/nix")[0], 404)

    def test_fremder_host_wird_abgewiesen(self):
        self.assertEqual(http("GET", self.base + "/api/status", headers={"Host": "boese.example"})[0], 403)
        self.assertEqual(http("POST", self.base + "/api/start", {}, {"Host": "boese.example", **self.hdr})[0], 403)

    def test_aktionen_brauchen_den_eigenen_header(self):
        # Die Aktionen sind ersetzt: fehlt der Schutz, soll der Test fehlschlagen, nicht das Programm beenden.
        with mock.patch.object(launcher, "start_all"), mock.patch.object(launcher, "stop_all"), \
                mock.patch.object(launcher, "shutdown"):
            for path in ("/api/start", "/api/stop", "/api/quit"):
                with self.subTest(pfad=path):
                    self.assertEqual(http("POST", self.base + path, {})[0], 403)

    def test_start_einmal_aufgerufen(self):
        calls = []
        started = threading.Event()
        with mock.patch.object(launcher, "start_all", side_effect=lambda: (calls.append(1), started.set())):
            self.assertEqual(http("POST", self.base + "/api/start", {}, self.hdr), (200, {"ok": True}))
            self.assertTrue(started.wait(2))
            # läuft gerade ein Start, wird keine zweiter ausgelöst
            with launcher.lock:
                launcher.state["phase"] = "startet"
            http("POST", self.base + "/api/start", {}, self.hdr)
            threading.Event().wait(0.3)
        with launcher.lock:
            launcher.state["phase"] = "aus"
        self.assertEqual(len(calls), 1)

    def test_stopp(self):
        with mock.patch.object(launcher, "stop_all") as stop:
            self.assertEqual(http("POST", self.base + "/api/stop", {}, self.hdr), (200, {"ok": True}))
        stop.assert_called_once()

    def test_beenden(self):
        done = threading.Event()
        with mock.patch.object(launcher, "shutdown", side_effect=lambda *a: done.set()):
            self.assertEqual(http("POST", self.base + "/api/quit", {}, self.hdr), (200, {"ok": True}))
            self.assertTrue(done.wait(2), "„Programm ganz beenden“ muss alles beenden")

    def test_seite_enthaelt_die_bedienung(self):
        html = helpers.read("proxy", "panel.html")
        for part in ('id="mainBtn"', 'id="quitBtn"', "/api/start", "/api/stop", "/api/quit", "X-Henri", "Kopieren"):
            with self.subTest(teil=part):
                self.assertIn(part, html)


if __name__ == "__main__":
    unittest.main()
