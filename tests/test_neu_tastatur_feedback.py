"""Neu: Rückmeldung beim Tippen (Ton, Vibration), Emoji-Knöpfe, Ansage vor dem Ergebnis.

Die Android-App lässt sich hier nicht ausführen. Diese Tests sichern die Quelltexte ab (Standardwerte,
Reihenfolge der Abläufe, Barrierefreiheit). Das Verhalten auf dem Handy prüft man per Hand.
"""
import os
import re
import struct
import unittest
import wave

import helpers


def kotlin(name):
    return helpers.read("keyboard", "app", "src", "main", "java", "de", "henri", "keyboard", name)


class TestEinstellungen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.look = kotlin("Look.kt")
        cls.main = kotlin("MainActivity.kt")

    def test_ton_und_ansage_sind_standardmaessig_an(self):
        self.assertRegex(self.look, r"fun keySound\(c: Context\) = prefs\(c\)\.getBoolean\(K_SOUND, true\)")
        self.assertRegex(self.look, r"fun announce\(c: Context\) = prefs\(c\)\.getBoolean\(K_ANNOUNCE, true\)")
        self.assertRegex(self.look, r"fun vibration\(c: Context\) = prefs\(c\)\.getBoolean\(K_VIBRATION, true\)")

    def test_look_laedt_die_neuen_optionen(self):
        self.assertIn("keySound = keySound(c)", self.look)
        self.assertIn("announce = announce(c)", self.look)

    def test_optionen_stehen_in_der_app(self):
        self.assertIn("Look.setKeySound", self.main)
        self.assertIn("Look.setAnnounce", self.main)
        self.assertIn("Vibration beim Tippen", self.main)
        self.assertIn("Ton beim Tippen", self.main)
        self.assertIn("Ich überarbeite deinen Text", self.main)

    def test_zuruecksetzen_stellt_die_standardwerte_wieder_her(self):
        self.assertRegex(self.look, r"fun reset\(c: Context\) = prefs\(c\)\.edit\(\)\.clear\(\)\.apply\(\)")


class TestTonUndVibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = kotlin("KeyboardService.kt")

    def test_jede_taste_gibt_rueckmeldung(self):
        for place in ("feedback(v)\n                typeText(", "feedback(v, PITCH_ACTION)\n                showPress(v as TextView)\n                onTap()",
                      "feedback(v, PITCH_ACTION)\n                    showPress(v as TextView)\n                    sendDownUpKeyEvents"):
            self.assertIn(place, self.ks)
        self.assertIn("feedback(it, PITCH_BUTTON)", self.ks, "auch die KI-Knöpfe klicken")
        self.assertNotIn("buzz(", self.ks)

    def test_ton_und_vibration_folgen_den_optionen(self):
        self.assertRegex(self.ks, r"if \(look\.keySound\) playClick\(pitch\)")
        self.assertRegex(self.ks, r"if \(look\.vibration\) vibrate\(v\)")

    def test_ton_ueber_soundpool_mit_ressource(self):
        self.assertIn("SoundPool", self.ks)
        self.assertIn("R.raw.key_click", self.ks)
        self.assertIn("sounds?.release()", self.ks, "SoundPool muss freigegeben werden")
        self.assertRegex(self.ks, r"catch \(e: Exception\) \{\s*sounds = null", "ohne Ton muss Tippen trotzdem gehen")

    def test_vibration_direkt_und_mit_rueckfall(self):
        self.assertIn("VibrationEffect.createOneShot(VIBRATE_MS", self.ks)
        self.assertIn("Build.VERSION.SDK_INT >= 26", self.ks, "minSdk 21: ältere Geräte brauchen den alten Aufruf")
        self.assertIn("HapticFeedbackConstants.KEYBOARD_TAP", self.ks)
        self.assertIn("FLAG_IGNORE_GLOBAL_SETTING", self.ks, "Rückfall darf nicht von der Systemeinstellung abhängen")
        self.assertIn("hasVibrator()", self.ks)
        self.assertIn("USAGE_ASSISTANCE_ACCESSIBILITY", self.ks, "als Bedienungshilfe melden, damit Android es nicht unterdrückt")
        self.assertIn("hasAmplitudeControl()", self.ks)
        self.assertIn("VIBRATE_MS = 40L", self.ks, "20 ms war auf manchen Handys nicht zu spüren")

    def test_berechtigung_und_tondatei(self):
        manifest = helpers.read("keyboard", "app", "src", "main", "AndroidManifest.xml")
        self.assertIn("android.permission.VIBRATE", manifest)
        path = os.path.join(helpers.ROOT, "keyboard", "app", "src", "main", "res", "raw", "key_click.wav")
        with wave.open(path) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2))
            self.assertLess(w.getnframes() / w.getframerate(), 0.2, "ein Klick, kein langer Ton")
            frames = w.readframes(w.getnframes())
        peak = max(abs(v) for (v,) in struct.iter_unpack("<h", frames))
        self.assertGreater(peak, 8000, "der Klick muss gut hörbar sein")
        self.assertLess(os.path.getsize(path), 20_000)


class TestEmojiKnoepfe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = kotlin("KeyboardService.kt")

    def test_emojis_statt_text(self):
        self.assertIn('ICON_IMPROVE = "✏️"', self.ks)
        self.assertIn('ICON_SPEAK = "🔊"', self.ks)
        self.assertIn('ICON_APPLY = "✅"', self.ks)
        self.assertIn("bigButton(ICON_IMPROVE, \"Verbessern\"", self.ks)
        self.assertIn("bigButton(ICON_SPEAK, \"Vorlesen\"", self.ks)
        self.assertIn("bigButton(ICON_APPLY, \"Übernehmen\"", self.ks)

    def test_kein_umbruch_und_namen_fuer_vorlesehilfen(self):
        body = self.ks[self.ks.index("private fun bigButton("):self.ks.index("private fun weighted(")]
        self.assertIn("maxLines = 1", body)
        self.assertIn("contentDescription = description", body, "TalkBack braucht den Namen, sonst sagt es nur „Bleistift“")

    def test_beim_vorlesen_wird_der_knopf_zu_stopp(self):
        self.assertIn('speakButton.text = if (on) ICON_STOP else ICON_SPEAK', self.ks)
        self.assertIn('speakButton.contentDescription = if (on) "Stopp" else "Vorlesen"', self.ks)
        self.assertIn('ICON_STOP = "⏹️"', self.ks)


class TestAnsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = kotlin("KeyboardService.kt")
        cls.improve = cls.ks[cls.ks.index("private fun improve()"):cls.ks.index("private fun showCorrection(")]

    def test_text_der_ansage_ist_der_angezeigte_text(self):
        self.assertIn('ANNOUNCE_TEXT = "Ich überarbeite deinen Text"', self.ks)
        # Anzeige und Ansage kommen aus derselben Stelle und können nicht auseinanderlaufen.
        self.assertIn('showBusy("$ANNOUNCE_TEXT …")', self.ks)
        self.assertIn("speak(ANNOUNCE_TEXT", self.ks)
        self.assertNotIn("KI übersetzt", self.ks)

    def test_ansage_kommt_vor_der_anfrage_und_das_ergebnis_wartet(self):
        self.assertLess(self.improve.index("startAnnouncement()"), self.improve.index("Api.correct("))
        self.assertIn("whenAnnouncementDone {", self.improve)
        self.assertIn("if (id == requestId) showCorrection(text, result)", self.improve,
                      "auch nach dem Warten darf ein veraltetes Ergebnis nicht erscheinen")

    def test_ergebnis_wird_erst_nach_dem_ende_der_ansage_gezeigt(self):
        self.assertIn("if (announcing) afterAnnouncement = block else block()", self.ks)
        self.assertRegex(self.ks, r"if \(announcing && id == announceUtterance\) finishAnnouncement\(\)")

    def test_ansage_haengt_nie_fest(self):
        self.assertIn("main.postDelayed(announceTimeout, ANNOUNCE_MAX_MS)", self.ks)
        self.assertIn("ANNOUNCE_MAX_MS = 4000L", self.ks)
        # Ohne laufende Sprachausgabe oder bei abgeschalteter Option wird gar nicht gewartet.
        self.assertIn("if (!look.announce || !ttsReady) return", self.ks)
        self.assertRegex(self.ks, r"if \(!ttsReady\) return // die Sprachausgabe ließ sich nicht starten")

    def test_alte_ansage_wird_bei_neuer_anfrage_verworfen(self):
        self.assertIn("finishAnnouncement(runPending = false)", self.ks)

    def test_anzeigen_des_ergebnisses_unveraendert(self):
        body = self.ks[self.ks.index("private fun showCorrection("):self.ks.index("// ---------- Ansage beim Verbessern")]
        for part in ('"Keine Verbindung zum Server."', '"Schon in Ordnung: $text"', 'speak("Schon in Ordnung.")',
                     "if (Api.autoSpeak(this)) speak(result)", "sourceText = text", "suggestion = result"):
            self.assertIn(part, body)

    def test_server_und_senden_unveraendert(self):
        self.assertEqual(self.ks.count("Api.correct("), 1)
        self.assertEqual(self.ks.count("performEditorAction("), 1)


class TestVersion(unittest.TestCase):
    def test_version(self):
        g = helpers.read("keyboard", "app", "build.gradle.kts")
        self.assertIn('versionName = "0.4.1"', g)
        self.assertIn("versionCode = 5", g)


if __name__ == "__main__":
    unittest.main()
