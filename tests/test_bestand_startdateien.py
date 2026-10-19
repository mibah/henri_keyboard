"""Bestand: Startdateien zum Doppelklicken."""
import os
import unittest

import helpers


class TestStartdateien(unittest.TestCase):
    def test_mac_datei(self):
        path = os.path.join(helpers.ROOT, "Start-Henri.command")
        self.assertTrue(os.access(path, os.X_OK), "Start-Henri.command muss ausführbar sein")
        text = helpers.read("Start-Henri.command")
        self.assertTrue(text.startswith("#!/bin/bash"))
        self.assertIn("python3 launcher.py", text)
        self.assertIn("Python 3 fehlt", text)

    def test_mac_fenster_wird_nur_bei_normalem_ende_geschlossen(self):
        text = helpers.read("Start-Henri.command")
        self.assertIn('if [ "$STATUS" -eq 0 ]', text)
        self.assertIn("close w", text)
        self.assertIn('exit "$STATUS"', text)

    def test_windows_datei(self):
        with open(os.path.join(helpers.ROOT, "Start-Henri.bat"), "rb") as f:
            raw = f.read()
        self.assertIn(b"\r\n", raw, "Batch-Dateien brauchen Windows-Zeilenenden")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        text = raw.decode("utf-8")
        self.assertIn("launcher.py", text)
        self.assertIn("py -3", text)
        self.assertIn("Python 3 fehlt", text)
        self.assertIn("exit", text)

    def test_dateien_existieren(self):
        for name in ("proxy/server.py", "proxy/launcher.py", "proxy/panel.html", "proxy/prompt.txt",
                     "proxy/prompt_reword.txt", "proxy/prompt_passage.txt", "QUICKSTART.md", "README.md", "LICENSE"):
            with self.subTest(datei=name):
                self.assertTrue(os.path.exists(os.path.join(helpers.ROOT, name)))


if __name__ == "__main__":
    unittest.main()
