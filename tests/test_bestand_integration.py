"""Bestand: kompletter Ablauf mit echtem Ollama (wie im Alltag): starten, korrigieren, Vorschläge, beenden.

Läuft nur mit HENRI_INTEGRATION=1 und wenn Ollama samt gemma3:4b vorhanden ist, sonst wird übersprungen.
    HENRI_INTEGRATION=1 python3 -m unittest test_bestand_integration -v
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

import helpers
from helpers import http

MODEL = "gemma3:4b"


def ollama_has_model():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            names = {m["name"] for m in json.load(r)["models"]}
        return MODEL in names
    except Exception:
        return False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.environ.get("HENRI_INTEGRATION") == "1", "HENRI_INTEGRATION=1 setzen")
@unittest.skipUnless(ollama_has_model(), "Ollama mit %s nicht vorhanden" % MODEL)
class TestKompletterAblauf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proxy_port, cls.panel_port = free_port(), free_port()
        env = dict(os.environ, PORT=str(cls.proxy_port), PANEL_PORT=str(cls.panel_port), BROWSER="true",
                   HENRI_MODEL=MODEL, HENRI_CONFIG=os.path.join(helpers.ROOT, "no-such-config.json"))
        env.pop("HENRI_REWORD_MODEL", None)
        cls.proc = subprocess.Popen([sys.executable, "launcher.py"], cwd=helpers.PROXY, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.panel = "http://127.0.0.1:%d" % cls.panel_port
        cls.proxy = "http://127.0.0.1:%d" % cls.proxy_port
        cls.hdr = {"X-Henri": "1"}
        for _ in range(40):
            try:
                if http("GET", cls.panel + "/api/status", timeout=1)[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        try:
            http("POST", cls.panel + "/api/quit", {}, cls.hdr, timeout=3)
        except Exception:
            pass
        try:
            cls.proc.wait(10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def wait_phase(self, wanted, seconds=90):
        end = time.time() + seconds
        while time.time() < end:
            _, st = http("GET", self.panel + "/api/status")
            if st["phase"] in wanted:
                return st
            time.sleep(0.5)
        return st

    def test_ablauf(self):
        _, st = http("GET", self.panel + "/api/status")
        self.assertEqual(st["phase"], "aus")

        http("POST", self.panel + "/api/start", {}, self.hdr)
        st = self.wait_phase(("bereit", "fehler"))
        self.assertEqual((st["phase"], st["error"]), ("bereit", ""))
        self.assertTrue(st["ollama"] and st["model"] and st["proxy"])

        code, d = http("POST", self.proxy + "/correct", {"text": "kanst du mir morgn die sachn mit bringn"}, timeout=90)
        self.assertEqual(code, 200)
        self.assertIn("Sachen", d["text"])
        self.assertIn("mitbringen", d["text"])

        code, d = http("POST", self.proxy + "/reword", {
            "original": "wiel ich nich gut seh dauert das schreibn lange", "before": "", "word": "Wie",
            "after": " ich nicht gut sehe, dauert das Schreiben lange.", "rejected": []}, timeout=90)
        self.assertEqual(code, 200)
        self.assertTrue(d["words"] and all(isinstance(w, str) for w in d["words"]))
        self.assertNotIn("Wie", d["words"])

        code, d = http("POST", self.proxy + "/rephrase", {
            "original": "ich bin um 17 uhr bein bahnhof ok", "before": "Ich bin um 17 Uhr ", "passage": "bei dem",
            "after": " Bahnhof. Ok.", "rejected": []}, timeout=90)
        self.assertEqual(code, 200)
        self.assertTrue(d["options"])

        _, st = http("GET", self.panel + "/api/status")
        self.assertGreaterEqual(st["corrections"], 1)
        self.assertIsNotNone(st["lastUse"])

        http("POST", self.panel + "/api/stop", {}, self.hdr)
        _, st = http("GET", self.panel + "/api/status")
        self.assertEqual(st["phase"], "aus")
        with self.assertRaises(Exception):
            http("GET", self.proxy + "/health", timeout=2)


if __name__ == "__main__":
    unittest.main()
