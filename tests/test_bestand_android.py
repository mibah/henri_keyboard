"""Bestand: feste Werte und Schutzregeln der Android-App (statische Prüfung des Quelltextes).

Ohne Gerät und ohne Gradle prüfbar. Hält fest, was sich nicht still ändern darf: das Standard-Aussehen,
die Hinweistexte, die Schnittstellen zum Server und die Absturzursache mit dem Scrollbalken.
"""
import re
import unittest

import helpers


def kotlin(name):
    return helpers.read("keyboard", "app", "src", "main", "java", "de", "henri", "keyboard", name)


class TestStandardAussehen(unittest.TestCase):
    """Das Farbschema „Standard“ ist das ursprüngliche Aussehen."""

    @classmethod
    def setUpClass(cls):
        text = kotlin("Look.kt")
        start = text.index("STANDARD, \"Standard (dunkel)\"")
        cls.standard = text[start:text.index("Theme(", start + 10)]
        cls.look = text

    def test_farben(self):
        expected = [
            "bg = Color.rgb(18, 18, 18)", "keyBg = Color.rgb(58, 58, 62)", "keyText = Color.WHITE",
            "specialBg = Color.rgb(32, 82, 140)", "deleteBg = Color.rgb(120, 40, 40)",
            "shiftOn = Color.rgb(200, 150, 0)", "panelBg = Color.rgb(30, 30, 36)",
            "hlMulti = Color.rgb(46, 204, 113)", "btnImprove = Color.rgb(30, 120, 60)",
            "btnSpeak = Color.rgb(32, 82, 140)", "btnApply = Color.rgb(160, 90, 0)", "btnStop = Color.rgb(176, 42, 42)",
            "pressText = Color.BLACK", "hlText = Color.BLACK",
        ]
        for part in expected:
            with self.subTest(farbe=part):
                self.assertIn(part, self.standard)
        # gelb (Markierung, Druckfarbe, Hinweis) ist 255,193,7
        self.assertIn("private val yellow = Color.rgb(255, 193, 7)", self.look)
        for field in ("hintText", "press", "hlSingle"):
            self.assertRegex(self.standard, field + r" = yellow")

    def test_groessen_und_standardstufen(self):
        self.assertIn("KEY_TEXT_SP = listOf(26f,", self.look)
        self.assertIn("KEY_HEIGHT_DP = listOf(58,", self.look)
        self.assertIn("SUGGESTION_SP = listOf(24f,", self.look)
        self.assertIn("SPEECH_RATE = listOf(0.75f, 0.95f, 1.2f)", self.look)
        self.assertIn("DEFAULT_SPEECH = 1", self.look)
        # ohne gespeicherte Einstellung gilt jeweils die erste Stufe bzw. die mittlere beim Vorlesen
        for key in ("K_KEY_TEXT", "K_KEY_HEIGHT", "K_SUGGESTION"):
            self.assertRegex(self.look, r"level\(c, %s, 0," % key)
        self.assertIn("Look.themes", kotlin("MainActivity.kt"))
        self.assertTrue(re.search(r"fun vibration\(c: Context\) = prefs\(c\)\.getBoolean\(K_VIBRATION, true\)", self.look))

    def test_standard_ist_das_erste_und_vorgewaehlte_schema(self):
        self.assertRegex(self.look, r"val themes: List<Theme> = listOf\(\s*Theme\(\s*STANDARD,")
        self.assertIn('getString(K_THEME, STANDARD)', self.look)


class TestTastatur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = kotlin("KeyboardService.kt")

    def test_beschriftungen(self):
        for label in ('"Verbessern"', '"Vorlesen"', '"Übernehmen"', '"Stopp"', '"Leerzeichen"'):
            self.assertIn(label, self.ks)

    def test_hinweistexte_unveraendert(self):
        self.assertIn('HINT_SELECT = "Falsches Wort? Antippen zum Markieren."', self.ks)
        self.assertIn('HINT_RENEW = "Gelbes Wort nochmal antippen: anderes Wort."', self.ks)
        self.assertIn('HINT_PASSAGE = "Grüne Stelle nochmal antippen: andere Formulierung."', self.ks)
        self.assertIn('HINT_DRAG = "Ziehen, dann loslassen …"', self.ks)

    def test_auswahl_grenze(self):
        self.assertIn("MAX_SELECT_WORDS = 15", self.ks)

    def test_kein_scrollbalken_per_code(self):
        """Ein per Code eingeschalteter Scrollbalken hat die Tastatur zum Absturz gebracht."""
        for name in ("KeyboardService.kt", "MainActivity.kt"):
            with self.subTest(datei=name):
                text = kotlin(name)
                self.assertNotRegex(text, r"isVerticalScrollBarEnabled\s*=\s*true")
                self.assertNotRegex(text, r"isScrollbarFadingEnabled")

    def test_passwortfelder_ohne_ki(self):
        self.assertIn("isPasswordField", self.ks)
        self.assertIn("TYPE_TEXT_VARIATION_PASSWORD", self.ks)
        self.assertRegex(self.ks, r"aiBar\.visibility = if \(isPasswordField\(info\)\) View\.GONE")

    def test_senden_nie_automatisch(self):
        """Enter wird nur durch den Tastendruck ausgelöst, nie von der Tastatur selbst."""
        self.assertEqual(self.ks.count("performEditorAction("), 1)
        self.assertEqual(self.ks.count("KEYCODE_ENTER"), 1)
        pos = self.ks.index("performEditorAction(")
        self.assertIn("private fun pressEnter()", self.ks[:pos])
        self.assertNotIn("private fun", self.ks[self.ks.index("private fun pressEnter()") + 10:pos])

    def test_sprachausgabe_verbindet_sich_neu(self):
        self.assertIn("private fun initTts", self.ks)
        self.assertRegex(self.ks, r"if \(result != TextToSpeech\.SUCCESS\)")

    def test_getrennt_sperrt_nur_verbessern(self):
        self.assertIn("Api.enabled(this)", self.ks)

    def test_server_aufrufe(self):
        for call in ("Api.correct(", "Api.reword(", "Api.rephrase("):
            self.assertIn(call, self.ks)


class TestSchnittstelle(unittest.TestCase):
    def test_pfade_und_zeitgrenzen(self):
        api = kotlin("Api.kt")
        for path in ('"/correct"', '"/reword"', '"/rephrase"', '"/health"'):
            self.assertIn(path, api)
        self.assertIn("connectMs: Int = 8000, readMs: Int = 60000", api)
        self.assertIn('"Bearer $token"', api)
        self.assertIn("MODE_PRIVATE", api)

    def test_json_felder(self):
        api = kotlin("Api.kt")
        for field in ('"text"', '"original"', '"before"', '"after"', '"rejected"', '"word"', '"passage"', '"words"', '"options"'):
            self.assertIn(field, api)


class TestManifestUndBuild(unittest.TestCase):
    def test_manifest(self):
        m = helpers.read("keyboard", "app", "src", "main", "AndroidManifest.xml")
        self.assertIn("android.permission.INTERNET", m)
        self.assertIn("android.permission.BIND_INPUT_METHOD", m)
        self.assertIn("android.view.InputMethod", m)
        self.assertIn("android.intent.action.TTS_SERVICE", m)
        self.assertIn('android:name=".KeyboardService"', m)
        self.assertIn('android:name=".MainActivity"', m)

    def test_build(self):
        g = helpers.read("keyboard", "app", "build.gradle.kts")
        self.assertIn('applicationId = "de.henri.keyboard"', g)
        self.assertIn("minSdk = 21", g)
        self.assertIn("targetSdk = 35", g)

    def test_keine_privaten_angaben_im_quelltext(self):
        api = kotlin("Api.kt")
        self.assertNotIn("192.168.99.", api)
        self.assertIn('DEFAULT_URL = "http://192.168.1.10:8787"', api)


if __name__ == "__main__":
    unittest.main()
