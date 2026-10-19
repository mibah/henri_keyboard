"""Neu: Anbieter für das Sprachmodell (proxy/providers.py und seine Einbindung).

Nur für den Stand mit Anbieter-Feature. Alle Anbieter werden durch einen Schein-Anbieter ersetzt, es
werden keine Schlüssel oder echte Dienste gebraucht.
"""
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("BROWSER", "true")
os.environ.setdefault("HENRI_CONFIG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-config.json"))

import helpers
from helpers import FakeLLM, http

import launcher
import providers
import server


class ConfigTestCase(unittest.TestCase):
    """Jeder Test arbeitet mit einer eigenen, leeren Konfigurationsdatei."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._path = mock.patch.object(providers, "CONFIG_PATH", os.path.join(self.tmp.name, "henri-config.json"))
        self._path.start()
        self.addCleanup(self._path.stop)
        self.addCleanup(launcher.apply_config)  # danach wieder der Standard
        launcher.apply_config()


class TestStandard(ConfigTestCase):
    def test_ohne_datei_ist_es_lokal_wie_bisher(self):
        r = providers.resolve()
        self.assertEqual((r.id, r.hosted, r.key), ("ollama", False, ""))
        self.assertEqual(r.model, os.environ.get("HENRI_MODEL", "gemma3:4b"))
        self.assertEqual(r.base_url, os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"))
        self.assertEqual(launcher.MODELS[0], r.model)

    def test_server_bekommt_im_standard_nichts_zusaetzliches(self):
        launcher.apply_config()
        self.assertEqual((server.EXTRA_BODY, server.EXTRA_HEADERS, server.HEALTH_SUFFIX), ({}, {}, ""))
        self.assertEqual(server.API_KEY, os.environ.get("LLM_API_KEY", ""))

    def test_kaputte_datei_faellt_auf_lokal_zurueck(self):
        with open(providers.CONFIG_PATH, "w") as f:
            f.write("{kaputt")
        self.assertEqual(providers.resolve().id, "ollama")

    def test_unbekannter_anbieter_faellt_auf_lokal_zurueck(self):
        self.assertEqual(providers.resolve({"provider": "gibtsnicht", "settings": {}}).id, "ollama")

    def test_alle_anbieter_haben_pflichtangaben(self):
        ids = [p["id"] for p in providers.PRESETS]
        self.assertEqual(ids[0], "ollama")
        self.assertEqual(len(ids), len(set(ids)))
        for p in providers.PRESETS:
            with self.subTest(anbieter=p["id"]):
                for field in ("name", "note", "base_url", "model", "extra_body", "extra_headers"):
                    self.assertIn(field, p)
                if p["hosted"] and p["id"] != providers.CUSTOM:
                    self.assertTrue(p["base_url"].startswith("https://"))
                    self.assertTrue(p["model"])
                    self.assertTrue(p["key_url"].startswith("https://"))


class TestSpeichern(ConfigTestCase):
    def test_speichern_laden(self):
        cfg = providers.load()
        providers.update_settings(cfg, "groq", key="test-schluessel-123456", model="llama-x")
        providers.save(cfg)
        r = providers.resolve()
        self.assertEqual((r.id, r.hosted, r.model, r.reword_model), ("groq", True, "llama-x", "llama-x"))
        self.assertEqual(r.key, "test-schluessel-123456")
        self.assertEqual(r.base_url, "https://api.groq.com/openai/v1")

    def test_datei_nur_fuer_den_benutzer(self):
        providers.save(providers.update_settings(providers.load(), "groq", key="k" * 12))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(providers.CONFIG_PATH).st_mode), 0o600)

    def test_leerer_schluessel_behaelt_den_alten(self):
        cfg = providers.update_settings(providers.load(), "mistral", key="alt-schluessel-123")
        providers.update_settings(cfg, "mistral", key="", model="neu")
        self.assertEqual(providers.resolve(cfg).key, "alt-schluessel-123")
        providers.update_settings(cfg, "mistral", clear_key=True)
        self.assertEqual(providers.resolve(cfg).key, "")

    def test_jeder_anbieter_behaelt_seine_einstellungen(self):
        cfg = providers.update_settings(providers.load(), "groq", key="groq-key-0001")
        providers.update_settings(cfg, "mistral", key="mistral-key-0002")
        providers.update_settings(cfg, "groq", model="x")
        self.assertEqual(providers.resolve(cfg).key, "groq-key-0001")
        cfg["provider"] = "mistral"
        self.assertEqual(providers.resolve(cfg).key, "mistral-key-0002")

    def test_adresse_nur_beim_eigenen_anbieter(self):
        cfg = providers.update_settings(providers.load(), "groq", base_url="https://boese.example/v1")
        self.assertEqual(providers.resolve(cfg).base_url, "https://api.groq.com/openai/v1")
        cfg = providers.update_settings(cfg, "custom", base_url="https://mein.example/v1/", model="m")
        self.assertEqual(providers.resolve(cfg).base_url, "https://mein.example/v1")

    def test_oberflaeche_bekommt_nie_den_schluessel(self):
        cfg = providers.update_settings(providers.load(), "groq", key="test-geheim-abcd1234")
        view = json.dumps(providers.public_view(cfg))
        self.assertNotIn("test-geheim-abcd1234", view)
        groq = next(p for p in providers.public_view(cfg)["providers"] if p["id"] == "groq")
        self.assertTrue(groq["hasKey"])
        self.assertEqual(groq["keyHint"], "…1234")
        self.assertEqual(providers.public_view(cfg)["active"], "groq")


class TestVerbindungstest(unittest.TestCase):
    def setUp(self):
        self.llm = FakeLLM()
        self.addCleanup(self.llm.close)

    def test_erfolg(self):
        ok, msg = providers.test(self.llm.url, "k", "m")
        self.assertTrue(ok)
        self.assertIn("Verbindung ok", msg)
        req = self.llm.requests[-1]
        self.assertEqual(req["headers"]["Authorization"], "Bearer k")
        self.assertEqual(req["body"]["model"], "m")

    def test_ohne_schluessel_kein_header(self):
        providers.test(self.llm.url, "", "m")
        self.assertNotIn("Authorization", self.llm.requests[-1]["headers"])

    def test_zusatzfelder_und_header(self):
        providers.test(self.llm.url, "k", "m", {"reasoning_effort": "none"}, {"X-Title": "Henri"})
        req = self.llm.requests[-1]
        self.assertEqual(req["body"]["reasoning_effort"], "none")
        self.assertEqual(req["headers"]["X-Title"], "Henri")

    def test_fehlermeldungen_auf_deutsch(self):
        cases = {401: "Schlüssel", 403: "verweigert", 404: "nicht gefunden", 429: "zu viele Anfragen", 503: "Problem"}
        for code, word in cases.items():
            with self.subTest(code=code):
                self.llm.reply = lambda b, c=code: (c, "details")
                ok, msg = providers.test(self.llm.url, "k", "m")
                self.assertFalse(ok)
                self.assertIn(word, msg)
        self.llm.reply = lambda b: (400, "bad model")
        self.assertIn("lehnt die Anfrage ab", providers.test(self.llm.url, "k", "m")[1])

    def test_schluessel_wird_nie_angezeigt(self):
        self.llm.reply = lambda b: (401, "Incorrect API key provided: sk-supergeheim-1234")
        ok, msg = providers.test(self.llm.url, "sk-supergeheim-1234", "m")
        self.assertFalse(ok)
        self.assertNotIn("supergeheim", msg)

    def test_nicht_erreichbar(self):
        ok, msg = providers.test("http://127.0.0.1:1/v1", "k", "m", timeout=2)
        self.assertFalse(ok)
        self.assertIn("nicht erreichbar", msg)

    def test_fehlende_angaben(self):
        self.assertFalse(providers.test("", "k", "m")[0])
        self.assertFalse(providers.test(self.llm.url, "k", "")[0])

    def test_unerwartetes_format(self):
        self.llm.reply = lambda b: (200, "x")
        with mock.patch("json.load", return_value={"nix": 1}):
            ok, msg = providers.test(self.llm.url, "k", "m")
        self.assertFalse(ok)

    def test_fehlerkennungen(self):
        self.assertIn("Schlüssel", providers.explain_code("HTTP 401"))
        self.assertIn("Tageslimit", providers.explain_code("HTTP 429"))
        self.assertIn("HTTP 503", providers.explain_code("HTTP 503"))
        self.assertIn("Keine Verbindung", providers.explain_code("URLError"))
        self.assertEqual(providers.explain_code(None), "")


class TestEinbindung(ConfigTestCase):
    """Anbieter wählen, Server und Steuerung nutzen ihn."""

    def setUp(self):
        super().setUp()
        self.llm = FakeLLM(lambda b: "Kannst du mir morgen die Sachen mitbringen?")
        self.addCleanup(self.llm.close)
        self._saved = {k: getattr(server, k) for k in ("BASE_URL", "API_KEY", "MODEL", "REWORD_MODEL", "APP_TOKEN")}
        self.addCleanup(lambda: [setattr(server, k, v) for k, v in self._saved.items()])
        server._hits.clear()
        with launcher.lock:
            launcher.state.update(phase="aus", step="", error="", pull=None)

    def choose_fake(self, key="gutes-passwort", model="fake-model", reword=""):
        cfg = providers.update_settings(providers.load(), "custom", key=key, model=model, reword_model=reword,
                                        base_url=self.llm.url)
        providers.save(cfg)
        launcher.apply_config()

    def test_apply_config_gibt_alles_an_den_server(self):
        self.choose_fake(reword="fake-reword")
        self.assertTrue(launcher.ACTIVE.hosted)
        self.assertEqual(launcher.MODELS, ["fake-model", "fake-reword"])
        self.assertEqual((server.BASE_URL, server.API_KEY, server.MODEL, server.REWORD_MODEL),
                         (self.llm.url, "gutes-passwort", "fake-model", "fake-reword"))
        self.assertEqual(server.HEALTH_SUFFIX, " (Cloud)")

    def test_zurueck_zu_lokal_raeumt_auf(self):
        self.choose_fake()
        providers.save({"provider": "ollama", "settings": {}})
        launcher.apply_config()
        self.assertEqual((server.HEALTH_SUFFIX, server.EXTRA_BODY, server.EXTRA_HEADERS), ("", {}, {}))
        self.assertNotEqual(server.API_KEY, "gutes-passwort")

    def test_status_bereit_ohne_ollama(self):
        self.choose_fake()
        with mock.patch.object(launcher, "ollama_up", return_value=False), \
                mock.patch.object(launcher, "proxy_health", return_value={"corrections": 0, "last_correction_ago": None}):
            s = launcher.status()
        self.assertEqual(s["phase"], "bereit")
        self.assertTrue(s["hosted"] and s["model"])
        self.assertEqual(s["providerName"], "Eigener (OpenAI-kompatibel)")

    def test_start_prueft_nur_den_anbieter(self):
        self.choose_fake()
        with mock.patch.object(launcher, "ollama_up", side_effect=AssertionError("Ollama darf nicht gebraucht werden")), \
                mock.patch.object(launcher, "pull_model", side_effect=AssertionError("kein Download")), \
                mock.patch.object(launcher, "proxy_health", side_effect=[None, {}, {}]), \
                mock.patch.object(launcher.server, "make_server") as make:
            make.return_value = mock.Mock(serve_forever=lambda: None)
            launcher.start_all()
        self.assertEqual(launcher.state["phase"], "bereit")
        self.assertTrue(any("Antworte nur mit dem Wort OK" in json.dumps(r["body"]) for r in self.llm.requests))

    def test_start_mit_falschem_schluessel_zeigt_klare_meldung(self):
        self.llm.reply = lambda b: (401, "Invalid API Key")
        self.choose_fake(key="falsch")
        with mock.patch.object(launcher, "proxy_health", return_value=None):
            launcher.start_all()
        self.assertEqual(launcher.state["phase"], "fehler")
        self.assertIn("nimmt den Schlüssel nicht an", launcher.state["error"])

    def test_korrektur_geht_ueber_den_anbieter(self):
        self.choose_fake()
        httpd = server.make_server(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        code, d = http("POST", base + "/correct", {"text": "kanst du mir morgn die sachn mit bringn"})
        self.assertEqual((code, d["text"]), (200, "Kannst du mir morgen die Sachen mitbringen?"))
        req = self.llm.requests[-1]
        self.assertEqual(req["headers"]["Authorization"], "Bearer gutes-passwort")
        self.assertEqual(req["body"]["model"], "fake-model")
        self.assertEqual(http("GET", base + "/health")[1]["model"], "fake-model (Cloud)")

    def test_anbieterfehler_im_betrieb_wird_gemerkt(self):
        self.choose_fake()
        httpd = server.make_server(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        self.llm.reply = lambda b: (429, "rate limit")
        self.assertEqual(http("POST", base + "/correct", {"text": "hallo du"})[0], 502)
        _, health = http("GET", base + "/health")
        self.assertEqual(health["last_error"]["what"], "HTTP 429")
        self.assertNotIn("hallo", json.dumps(health), "es werden keine Inhalte gemerkt")
        self.assertIn("Tageslimit", launcher.last_error(health)["text"])
        self.assertIsNone(launcher.last_error({"last_error": {"what": "HTTP 429", "ago": 5000}}))
        self.assertIsNone(launcher.last_error(None))


class TestOberflaeche(ConfigTestCase):
    def setUp(self):
        super().setUp()
        self.llm = FakeLLM()
        self.addCleanup(self.llm.close)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Panel)
        self._port = mock.patch.object(launcher, "PANEL_PORT", self.httpd.server_address[1])
        self._port.start()
        self.addCleanup(self._port.stop)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.hdr = {"X-Henri": "1"}
        with launcher.lock:
            launcher.state.update(phase="aus", step="", error="", pull=None)
        launcher.own.update(httpd=None, ollama=None)
        # unabhängig davon, ob auf diesem Rechner gerade ein echter Server läuft
        self._health = mock.patch.object(launcher, "proxy_health", return_value=None)
        self._health.start()
        self.addCleanup(self._health.stop)

    def test_liste(self):
        code, d = http("GET", self.base + "/api/providers")
        self.assertEqual(code, 200)
        self.assertEqual(d["active"], "ollama")
        self.assertEqual([p["id"] for p in d["providers"]][:2], ["ollama", "groq"])

    def test_test_und_speichern_brauchen_den_header(self):
        for path in ("/api/provider/test", "/api/provider/save"):
            self.assertEqual(http("POST", self.base + path, {})[0], 403)

    def test_testen_speichert_nichts(self):
        body = {"provider": "custom", "key": "k", "model": "m", "base_url": self.llm.url}
        code, d = http("POST", self.base + "/api/provider/test", body, self.hdr)
        self.assertEqual((code, d["ok"]), (200, True))
        self.assertFalse(os.path.exists(providers.CONFIG_PATH))

    def test_testen_nutzt_gespeicherten_schluessel(self):
        providers.save(providers.update_settings(providers.load(), "custom", key="gespeichert-123", base_url=self.llm.url))
        http("POST", self.base + "/api/provider/test", {"provider": "custom", "key": "", "model": "m"}, self.hdr)
        self.assertEqual(self.llm.requests[-1]["headers"]["Authorization"], "Bearer gespeichert-123")

    def test_testen_meldet_fehler_auf_deutsch(self):
        self.llm.reply = lambda b: (401, "x")
        _, d = http("POST", self.base + "/api/provider/test",
                    {"provider": "custom", "key": "k", "model": "m", "base_url": self.llm.url}, self.hdr)
        self.assertFalse(d["ok"])
        self.assertIn("Schlüssel", d["message"])

    def test_speichern(self):
        body = {"provider": "custom", "key": "neuer-schluessel", "model": "m", "reword_model": "r", "base_url": self.llm.url}
        code, d = http("POST", self.base + "/api/provider/save", body, self.hdr)
        self.assertEqual((code, d["ok"]), (200, True))
        self.assertIn("Mit Starten", d["message"])
        self.assertEqual(providers.load()["provider"], "custom")
        self.assertEqual(launcher.ACTIVE.key, "neuer-schluessel")
        self.assertEqual((launcher.MODEL, launcher.REWORD_MODEL), ("m", "r"))

    def test_speichern_startet_laufenden_server_neu(self):
        launcher.own["httpd"] = mock.Mock()
        with mock.patch.object(launcher, "stop_all") as stop, mock.patch.object(launcher, "start_all") as start:
            _, d = http("POST", self.base + "/api/provider/save",
                        {"provider": "custom", "key": "k", "model": "m", "base_url": self.llm.url}, self.hdr)
            threading.Event().wait(0.3)
        stop.assert_called_once()
        start.assert_called_once()
        self.assertIn("neu", d["message"])
        launcher.own["httpd"] = None

    def test_speichern_waehrend_des_starts_wird_abgelehnt(self):
        launcher.update(phase="startet")
        _, d = http("POST", self.base + "/api/provider/save", {"provider": "groq", "key": "k"}, self.hdr)
        self.assertFalse(d["ok"])
        self.assertFalse(os.path.exists(providers.CONFIG_PATH))

    def test_status_zeigt_den_anbieter(self):
        _, st = http("GET", self.base + "/api/status")
        self.assertIs(st["hosted"], False)
        self.assertEqual(st["providerName"], "Lokal (Ollama)")
        self.assertIn("lastError", st)

    def test_seite_enthaelt_den_anbieterbereich(self):
        html = helpers.read("proxy", "panel.html")
        for part in ('id="provSelect"', 'id="provKey"', 'id="provTest"', 'id="provSave"', "/api/providers",
                     "/api/provider/test", "/api/provider/save", "Cloud-Anbieter"):
            with self.subTest(teil=part):
                self.assertIn(part, html)

    def test_konfigurationsdatei_ist_nicht_im_git(self):
        self.assertIn("proxy/henri-config.json", helpers.read(".gitignore"))


if __name__ == "__main__":
    unittest.main()
