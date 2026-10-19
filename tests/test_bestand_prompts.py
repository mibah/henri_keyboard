"""Bestand: Die Prompts und Beispiele sind eingefroren.

Sie bestimmen die Qualität der Vorschläge und wurden bewusst gewählt. Ändert sich eine Datei, schlägt
dieser Test fehl. Ist die Änderung gewollt: print_prompt_hashes.py ausführen und die Werte hier eintragen.
"""
import hashlib
import json
import unittest

import helpers

import server

FILES = {
    "prompt.txt": "a38a1e888576584c5a0a8048f295b4f09570940f6fa0d972fa5c6387ed237d64",
    "prompt_reword.txt": "f1dffb801d514d42b729495e769cb2568187bc3b1e25f2d20b0a252c471b2721",
    "prompt_passage.txt": "3659bf425535bba6d51133a538e97f298e6ed691e66ea5e70b18f645581e8dcc",
}
SHOTS = {
    "SHOTS": "476b2304756a4219c7e266b3ca648867f0fa2d08039bad4a2dc8399082761e20",
    "REWORD_SHOTS": "72d7b07a5c00dd694fcb37e3e945d82ae3670675a55a93ac9d26bf5c6ec8338f",
    "PASSAGE_SHOTS": "45a0ea875879014bad8b9f564fa49e2c3d8c7a13a7ee1a72ae71391536650739",
}


class TestPromptsEingefroren(unittest.TestCase):
    def test_dateien(self):
        for name, expected in FILES.items():
            with self.subTest(datei=name):
                with open(helpers.PROXY + "/" + name, "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), expected,
                                     name + " wurde geändert. Gewollt? Dann print_prompt_hashes.py ausführen.")

    def test_beispiele(self):
        for name, expected in SHOTS.items():
            with self.subTest(beispiele=name):
                data = json.dumps(getattr(server, name), ensure_ascii=False, sort_keys=True).encode()
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected,
                                 name + " wurde geändert. Gewollt? Dann print_prompt_hashes.py ausführen.")


class TestPromptInhalt(unittest.TestCase):
    """Zusätzlich lesbare Kernaussagen, damit ein Fehlschlag verständlich ist."""

    def text(self, name):
        with open(helpers.PROXY + "/" + name, encoding="utf-8") as f:
            return f.read()

    def test_korrektur(self):
        t = self.text("prompt.txt")
        for part in ("<nachricht>", "kein Auftrag", "Übersetze nie", "Erfinde nichts hinzu"):
            self.assertIn(part, t)

    def test_gelb_ein_wort(self):
        t = self.text("prompt_reword.txt")
        for part in ("bis zu 5 Wörter", "Ein Wort pro Zeile", "abgelehnt"):
            self.assertIn(part, t)

    def test_gruen_mehrere_woerter(self):
        t = self.text("prompt_passage.txt")
        for part in ("bis zu 3", "mehreren Wörtern", "Namen, Zahlen, Uhrzeiten"):
            self.assertIn(part, t)

    def test_gelb_und_gruen_sind_getrennt(self):
        self.assertNotEqual(self.text("prompt_reword.txt"), self.text("prompt_passage.txt"))


if __name__ == "__main__":
    unittest.main()
