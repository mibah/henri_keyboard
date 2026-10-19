"""Bestand: Verhalten des Servers (proxy/server.py) vor dem Anbieter-Feature.

Dieselben Tests müssen gegen den alten und den neuen Stand grün sein. Das Sprachmodell ist ein
Schein-Anbieter (helpers.FakeLLM), es braucht weder Ollama noch Internet.
"""
import os
import threading
import unittest

import helpers
from helpers import FakeLLM, http

import server


def prompt_file(name):
    with open(os.path.join(helpers.PROXY, name), encoding="utf-8") as f:
        return f.read().strip()


class ServerTestCase(unittest.TestCase):
    """Startet den echten Server in diesem Prozess gegen einen Schein-Anbieter."""

    model = "gemma3:4b"
    reword_model = "qwen2.5:7b"

    def setUp(self):
        self.llm = FakeLLM()
        self._saved = {k: getattr(server, k) for k in ("BASE_URL", "API_KEY", "MODEL", "REWORD_MODEL", "APP_TOKEN")}
        server.BASE_URL = self.llm.url
        server.API_KEY = ""
        server.MODEL = self.model
        server.REWORD_MODEL = self.reword_model
        server.APP_TOKEN = ""
        server._hits.clear()
        server.STATS["last"] = None
        server.STATS["count"] = 0
        self.httpd = server.make_server(0)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.llm.close()
        for k, v in self._saved.items():
            setattr(server, k, v)

    def correct(self, text, headers=None):
        return http("POST", self.base + "/correct", {"text": text}, headers)


class TestHealthUndRouten(ServerTestCase):
    def test_health_felder(self):
        code, d = http("GET", self.base + "/health")
        self.assertEqual(code, 200)
        self.assertIs(d["ok"], True)
        self.assertTrue(d["model"].startswith(self.model))
        self.assertEqual(d["corrections"], 0)
        self.assertIsNone(d["last_correction_ago"])

    def test_unbekannte_pfade(self):
        self.assertEqual(http("GET", self.base + "/nix")[0], 404)
        self.assertEqual(http("POST", self.base + "/nix", {"text": "a"})[0], 404)

    def test_zaehler_nach_korrektur(self):
        self.llm.reply = lambda b: "Hallo."
        self.assertEqual(self.correct("hallo")[0], 200)
        _, d = http("GET", self.base + "/health")
        self.assertEqual(d["corrections"], 1)
        self.assertLessEqual(d["last_correction_ago"], 5)


class TestKorrektur(ServerTestCase):
    def test_anfrage_an_das_modell(self):
        self.llm.reply = lambda b: "Kannst du mir morgen die Sachen mitbringen?"
        code, d = self.correct("kanst du mir morgn die sachn mit bringn")
        self.assertEqual((code, d), (200, {"text": "Kannst du mir morgen die Sachen mitbringen?"}))
        req = self.llm.requests[-1]
        body = req["body"]
        self.assertTrue(req["path"].endswith("/chat/completions"))
        self.assertEqual(body["model"], self.model)
        self.assertEqual(body["temperature"], 0)
        msgs = body["messages"]
        self.assertEqual(len(msgs), 2 + 2 * len(server.SHOTS))
        self.assertEqual(msgs[0], {"role": "system", "content": prompt_file("prompt.txt")})
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertEqual(msgs[-1]["content"], "<nachricht>kanst du mir morgn die sachn mit bringn</nachricht>")

    def test_beispiele_im_verlauf(self):
        self.correct("x y")
        msgs = self.llm.requests[-1]["body"]["messages"]
        for i, (src, dst) in enumerate(server.SHOTS):
            self.assertEqual(msgs[1 + 2 * i], {"role": "user", "content": "<nachricht>" + src + "</nachricht>"})
            self.assertEqual(msgs[2 + 2 * i], {"role": "assistant", "content": dst})

    def test_schluessel_nur_wenn_gesetzt(self):
        self.correct("a b")
        self.assertNotIn("Authorization", self.llm.requests[-1]["headers"])
        server.API_KEY = "geheim"
        self.correct("a b")
        self.assertEqual(self.llm.requests[-1]["headers"]["Authorization"], "Bearer geheim")

    def test_denken_abschalten_nur_bei_qwen3(self):
        server.MODEL = "qwen3:4b"
        self.correct("a b")
        self.assertTrue(self.llm.requests[-1]["body"]["messages"][-1]["content"].endswith(" /no_think"))
        server.MODEL = "gemma3:4b"
        self.correct("a b")
        self.assertNotIn("/no_think", self.llm.requests[-1]["body"]["messages"][-1]["content"])

    def test_tags_und_denkblock_werden_entfernt(self):
        self.llm.reply = lambda b: "<think>überlege</think>\n<nachricht>Hallo Welt</nachricht>\n"
        self.assertEqual(self.correct("hallo welt")[1], {"text": "Hallo Welt"})

    def test_schutz_vor_zu_langer_antwort(self):
        self.llm.reply = lambda b: "Ärgerlich, wenn Fehler sich zeigen. " * 5
        self.assertEqual(self.correct("ok")[1], {"text": "ok"})

    def test_leere_antwort_gibt_original(self):
        self.llm.reply = lambda b: "   "
        self.assertEqual(self.correct("hallo du")[1], {"text": "hallo du"})

    def test_eingabe_pruefung(self):
        self.assertEqual(self.correct("")[0], 400)
        self.assertEqual(self.correct("   ")[0], 400)
        self.assertEqual(http("POST", self.base + "/correct", {"nix": 1})[0], 400)
        self.assertEqual(http("POST", self.base + "/correct", b"kein json")[0], 400)
        self.assertEqual(http("POST", self.base + "/correct", {"text": 5})[0], 400)
        self.assertEqual(self.correct("a" * (server.MAX_CHARS + 1))[0], 413)
        self.assertEqual(self.correct("a" * server.MAX_CHARS)[0], 200)

    def test_modellfehler_wird_502(self):
        self.llm.reply = lambda b: (500, "kaputt")
        self.assertEqual(self.correct("hallo du"), (502, {"error": "llm unavailable"}))

    def test_umlaute_und_emoji_bleiben(self):
        self.llm.reply = lambda b: "Das war ein schöner Tag 😊 Danke dir."
        self.assertEqual(self.correct("das war ein schöner tag 😊 danke dir")[1]["text"], "Das war ein schöner Tag 😊 Danke dir.")


class TestZugriffUndBegrenzung(ServerTestCase):
    def test_token(self):
        server.APP_TOKEN = "geheim"
        self.assertEqual(self.correct("hallo du")[0], 401)
        self.assertEqual(self.correct("hallo du", {"Authorization": "Bearer falsch"})[0], 401)
        self.assertEqual(self.correct("hallo du", {"Authorization": "Bearer geheim"})[0], 200)
        # /health bleibt ohne Token erreichbar (die App prüft damit die Verbindung)
        self.assertEqual(http("GET", self.base + "/health")[0], 200)

    def test_begrenzung_pro_minute(self):
        codes = [self.correct("hallo du")[0] for _ in range(server.RATE_LIMIT + 1)]
        self.assertEqual(codes[:server.RATE_LIMIT], [200] * server.RATE_LIMIT)
        self.assertEqual(codes[-1], 429)

    def test_keine_inhalte_im_log(self):
        # Der Server schreibt keine Zugriffe (und damit keine Texte) auf die Konsole.
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            self.correct("geheimer satz hier")
        self.assertNotIn("geheimer", buf.getvalue())


class TestWortvorschlag(ServerTestCase):
    """Gelb: ein Wort (/reword)."""

    def reword(self, **kw):
        data = dict(original="wiel ich nich gut seh dauert das schreibn lange", before="", word="Wie",
                    after=" ich nicht gut sehe, dauert das Schreiben lange.", rejected=[])
        data.update(kw)
        return http("POST", self.base + "/reword", data)

    def test_ergebnis_und_filter(self):
        self.llm.reply = lambda b: "1. Weil\n- Da\nWenn\nweil\nWie\n\"Obwohl\"\nweil ich dann doch nochmal\nSehr schön!\n\nUnd\n(Falls)"
        code, d = self.reword()
        self.assertEqual(code, 200)
        # doppelte, das markierte Wort selbst und zu lange Vorschläge fallen weg, höchstens 5
        self.assertEqual(d["words"], ["Weil", "Da", "Wenn", "Obwohl", "Sehr schön"])

    def test_abgelehnte_werden_nicht_wieder_vorgeschlagen(self):
        self.llm.reply = lambda b: "Weil\nDa\nWenn"
        self.assertEqual(self.reword(rejected=["weil"])[1]["words"], ["Da", "Wenn"])

    def test_grossschreibung_am_satzanfang(self):
        self.llm.reply = lambda b: "weil\ndass"
        self.assertEqual(self.reword()[1]["words"], ["Weil", "Dass"])
        self.assertEqual(self.reword(before="Ich sage, ")[1]["words"], ["weil", "dass"])

    def test_anfrage_an_das_modell(self):
        self.llm.reply = lambda b: "Weil"
        self.reword()
        body = self.llm.requests[-1]["body"]
        self.assertEqual(body["model"], self.reword_model)
        self.assertEqual(body["temperature"], 0)
        msgs = body["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": prompt_file("prompt_reword.txt")})
        self.assertEqual(len(msgs), 2 + 2 * len(server.REWORD_SHOTS))
        last = msgs[-1]["content"]
        self.assertIn("<original>wiel ich nich gut seh dauert das schreibn lange</original>", last)
        self.assertIn("<korrigiert><<Wie>> ich nicht gut sehe, dauert das Schreiben lange.</korrigiert>", last)
        self.assertIn("Getippt wurde an dieser Stelle: wiel", last)
        self.assertIn("Abgelehnte Wörter: keine", last)

    def test_abgelehnte_stehen_in_der_anfrage(self):
        self.reword(rejected=["Weil", "Da"])
        self.assertIn("Abgelehnte Wörter: Weil, Da", self.llm.requests[-1]["body"]["messages"][-1]["content"])

    def test_leere_antwort_gibt_leere_liste(self):
        self.llm.reply = lambda b: ""
        self.assertEqual(self.reword()[1], {"words": []})

    def test_eingabe_pruefung(self):
        self.assertEqual(http("POST", self.base + "/reword", {"word": "a"})[0], 400)
        self.assertEqual(self.reword(word="  ")[0], 400)
        self.assertEqual(self.reword(rejected=[1])[0], 400)
        self.assertEqual(self.reword(original="a" * (2 * server.MAX_CHARS + 1))[0], 413)
        self.assertEqual(self.reword(rejected=["x"] * 21)[0], 413)

    def test_zuordnung_zum_getippten_wort(self):
        cases = [
            ("wiel ich nich gut seh dauert das schreibn lange", "", "Wie", "wiel"),
            ("kannst du bitte brot milch und eir mitbrignen", "Kannst du bitte Brot, Milch und ", "Eis", "eir"),
            ("wir ham gans lange gwartet auf dich", "Wir haben ", "Gans", "gans"),
            ("ich bin um 17 uhr bein bahnhof ok", "Ich bin um 17 Uhr ", "bei", "bein"),
            ("ich kan morgn nich komm erst um fümf", "Ich kann morgen nicht kommen, erst um ", "fünf", "fümf"),
            ("ok", "", "Ok", "ok"),
        ]
        for original, before, word, expected in cases:
            with self.subTest(word=word):
                self.assertEqual(server.typed_word(original, before, word), expected)

    def test_zuordnung_unklar(self):
        self.assertEqual(server.typed_word("", "", "Hallo"), "")


class TestFormulierung(ServerTestCase):
    """Grün: mehrere Wörter (/rephrase)."""

    def rephrase(self, **kw):
        data = dict(original="ich bin um 17 uhr bein bahnhof ok", before="Ich bin um 17 Uhr ", passage="bei dem",
                    after=" Bahnhof. Ok.", rejected=[])
        data.update(kw)
        return http("POST", self.base + "/rephrase", data)

    def test_ergebnis_und_filter(self):
        self.llm.reply = lambda b: "beim\nan dem\nvor dem\nbeim\nbei dem\nhinter dem"
        code, d = self.rephrase()
        self.assertEqual(code, 200)
        self.assertEqual(d["options"], ["beim", "an dem", "vor dem"])

    def test_anfrage_an_das_modell(self):
        self.llm.reply = lambda b: "beim"
        self.rephrase(rejected=["beim"])
        body = self.llm.requests[-1]["body"]
        self.assertEqual(body["model"], self.reword_model)
        msgs = body["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": prompt_file("prompt_passage.txt")})
        self.assertEqual(len(msgs), 2 + 2 * len(server.PASSAGE_SHOTS))
        last = msgs[-1]["content"]
        self.assertIn("<korrigiert>Ich bin um 17 Uhr <<bei dem>> Bahnhof. Ok.</korrigiert>", last)
        self.assertIn("Getippt wurde an dieser Stelle: bein", last)
        self.assertIn("Abgelehnte Vorschläge: beim", last)

    def test_eingabe_pruefung(self):
        self.assertEqual(http("POST", self.base + "/rephrase", {"passage": "a"})[0], 400)
        self.assertEqual(self.rephrase(passage="")[0], 400)
        self.assertEqual(self.rephrase(before="a" * (2 * server.MAX_CHARS + 1))[0], 413)

    def test_zuordnung_mehrerer_woerter(self):
        cases = [
            ("ich bin um 17 uhr bein bahnhof ok", "Ich bin um 17 Uhr ", "bei dem", "bein"),
            ("ich hab gestern ne tolle sendung gesehn", "Ich habe gestern ", "eine tolle Sendung", "ne tolle sendung"),
            ("ich hab dir gestern ne nachricht geschikt aber du hast nich geantwortet",
             "Ich habe dir gestern eine Nachricht geschickt, ", "aber du hast nicht", "aber du hast nich"),
        ]
        for original, before, passage, expected in cases:
            with self.subTest(passage=passage):
                self.assertEqual(server.typed_span(original, before, passage), expected)


class TestQuelltexte(unittest.TestCase):
    def test_einstellungen_aus_der_umgebung(self):
        text = helpers.read("proxy", "server.py")
        for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "APP_TOKEN", "PORT", "LLM_REWORD_MODEL"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
