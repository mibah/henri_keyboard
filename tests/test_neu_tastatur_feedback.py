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
        self.assertIn("feedback(it, if (execute) PITCH_EXECUTE else PITCH_SELECT)", self.ks, "auch die KI-Knöpfe klicken")
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
        self.assertIn("VibrationEffect.createOneShot(look.vibrationMs", self.ks)
        self.assertIn("Build.VERSION.SDK_INT >= 26", self.ks, "minSdk 21: ältere Geräte brauchen den alten Aufruf")
        self.assertIn("HapticFeedbackConstants.KEYBOARD_TAP", self.ks)
        self.assertIn("FLAG_IGNORE_GLOBAL_SETTING", self.ks, "Rückfall darf nicht von der Systemeinstellung abhängen")
        self.assertIn("hasVibrator()", self.ks)
        self.assertIn("USAGE_ASSISTANCE_ACCESSIBILITY", self.ks, "als Bedienungshilfe melden, damit Android es nicht unterdrückt")
        self.assertIn("hasAmplitudeControl()", self.ks)
        self.assertIn("look.vibrationMs", self.ks)
        self.assertNotIn("VIBRATE_MS", self.ks, "die Dauer kommt aus den Einstellungen")

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


class TestVibrationsstaerke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.look = kotlin("Look.kt")
        cls.main = kotlin("MainActivity.kt")

    def test_stufen_und_standard(self):
        m = re.search(r"VIBRATION_MS = listOf\((\d+)L, (\d+)L, (\d+)L\)", self.look)
        self.assertIsNotNone(m)
        light, normal, strong = (int(x) for x in m.groups())
        self.assertLess(light, normal)
        self.assertLess(normal, strong)
        self.assertIn("DEFAULT_VIBE = 1", self.look)
        self.assertGreaterEqual(normal, 80, "ein einzelner kurzer Impuls ist langsam getippt kaum zu spüren")

    def test_ohne_gespeicherte_einstellung_gilt_der_standard(self):
        self.assertRegex(self.look, r"VIBRATION_MS\[level\(c, K_VIBE, DEFAULT_VIBE, VIBRATION_MS\.lastIndex\)\]")

    def test_einstellung_in_der_app(self):
        self.assertIn("STÄRKE DER VIBRATION", self.main)
        self.assertRegex(self.main, r"Look\.level\(this, Look\.K_VIBE, Look\.DEFAULT_VIBE, Look\.VIBRATION_MS\.lastIndex\)")
        for label in ("Leicht", "Kräftig", "Sehr kräftig"):
            self.assertIn('"%s"' % label, self.main)


class TestZweimalTippen(unittest.TestCase):
    """Die drei KI-Knöpfe: erst antippen markiert (dicker Rand), nochmal antippen führt aus."""

    @classmethod
    def setUpClass(cls):
        cls.ks = kotlin("KeyboardService.kt")
        cls.look = kotlin("Look.kt")
        cls.main = kotlin("MainActivity.kt")
        cls.button = cls.ks[cls.ks.index("private fun bigButton("):cls.ks.index("// ---------- Erst markieren, dann ausführen")]

    def test_standardmaessig_an_und_in_der_app_abschaltbar(self):
        self.assertRegex(self.look, r"fun confirmTap\(c: Context\) = prefs\(c\)\.getBoolean\(K_CONFIRM, true\)")
        self.assertIn("confirmTap = confirmTap(c)", self.look)
        self.assertIn("Look.setConfirmTap", self.main)
        self.assertIn("Erst markieren, dann nochmal tippen", self.main)

    def test_erstes_tippen_markiert_zweites_fuehrt_aus(self):
        self.assertIn("val execute = !look.confirmTap || !needsConfirm() || armedButton === this", self.button)
        self.assertRegex(self.button, r"if \(execute\) \{\s*disarm\(\)\s*onTap\(\)\s*\} else \{\s*arm\(this\)")

    def test_alle_drei_knoepfe_laufen_darueber(self):
        for call in ('bigButton(ICON_IMPROVE, "Verbessern"', 'bigButton(ICON_SPEAK, "Vorlesen"', 'bigButton(ICON_APPLY, "Übernehmen"'):
            self.assertIn(call, self.ks)
        self.assertEqual(self.ks.count("bigButton("), 4, "drei Aufrufe plus die Definition")

    def test_stopp_beim_vorlesen_ohne_zweites_tippen(self):
        self.assertIn("needsConfirm = { !speaking }", self.ks)

    def test_markierung_wird_aufgehoben(self):
        # beim Tippen einer Taste, bei Sondertasten, Löschen, nach Ausführen, bei Feldwechsel und nach Zeitablauf
        for place in ("disarm()\n                feedback(v)\n                typeText(",
                      "disarm()\n                feedback(v, PITCH_ACTION)\n                showPress(v as TextView)\n                onTap()",
                      "disarm()\n                    feedback(v, PITCH_ACTION)\n                    showPress(v as TextView)\n                    sendDownUpKeyEvents",
                      "private fun clearSuggestion() {\n        disarm()"):
            self.assertIn(place, self.ks)
        self.assertIn("main.postDelayed(disarmTimeout, ARM_MS)", self.ks)
        self.assertIn("ARM_MS = 6000L", self.ks)
        self.assertIn("main.removeCallbacks(disarmTimeout)", self.ks)

    def test_dicker_rand_dunkle_fuellung_und_rueckbau(self):
        arm = self.ks[self.ks.index("private fun arm("):self.ks.index("private fun disarm(")]
        self.assertIn("setStroke(dp(6), look.select)", arm)
        self.assertIn("setColor(look.selectFill)", arm)
        disarm = self.ks[self.ks.index("private fun disarm("):self.ks.index("private fun weighted(")]
        self.assertIn("shape.setColor(button.tag as? Int ?: look.btnSpeak)", disarm, "die Knopffarbe muss zurückkommen")
        self.assertIn("if (look.keyStroke != 0) shape.setStroke(dp(2), look.keyStroke) else shape.setStroke(0, 0)", disarm,
                      "nach dem Aufheben muss der Knopf wieder aussehen wie vorher")

    def test_knopffarbe_steht_im_tag_auch_beim_vorlesen(self):
        self.assertIn("tag = color", self.button)
        self.assertIn("speakButton.tag = fill", self.ks)
        self.assertIn("if (armedButton !== speakButton)", self.ks)

    def test_zwei_unterschiedliche_toene(self):
        self.assertIn("PITCH_SELECT = 0.9f", self.ks)
        self.assertIn("PITCH_EXECUTE = 1.25f", self.ks)

    def test_namen_fuer_vorlesehilfen_bleiben(self):
        self.assertIn("contentDescription = description", self.button)


def _luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def _contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _themes():
    """Liest die Farbschemata aus Look.kt: Name -> {Feld: (r, g, b)}."""
    src = kotlin("Look.kt")
    named = {k: v for k, v in ((m.group(1), tuple(int(x) for x in m.groups()[1:])) for m in
                               re.finditer(r"private val (\w+) = Color\.rgb\((\d+), (\d+), (\d+)\)", src))}
    named.update({"Color.WHITE": (255, 255, 255), "Color.BLACK": (0, 0, 0)})

    def color(expr):
        expr = expr.strip()
        m = re.fullmatch(r"Color\.rgb\((\d+), (\d+), (\d+)\)", expr)
        if m:
            return tuple(int(x) for x in m.groups())
        return named[expr]
    out = {}
    for block in src.split("Theme(")[1:]:
        if "Palette(" not in block:  # die Klassendefinition "class Theme(val id ..." überspringen
            continue
        theme_id = re.match(r'\s*("?)(\w+)\1', block).group(2)
        palette = block[block.index("Palette("):]
        fields = {}
        for m in re.finditer(r"(\w+) = (Color\.rgb\(\d+, \d+, \d+\)|Color\.WHITE|Color\.BLACK|\w+)(?=,|\n|\))", palette):
            try:
                fields[m.group(1)] = color(m.group(2))
            except KeyError:
                pass
        out[theme_id] = fields
    return out


class TestRandfarben(unittest.TestCase):
    """Markierter Knopf: leuchtender Rand, der sich bei jedem Farbschema deutlich abhebt (Menschen mit Sehbehinderung)."""

    @classmethod
    def setUpClass(cls):
        cls.themes = _themes()

    def test_alle_fuenf_schemata_gefunden(self):
        self.assertEqual(set(self.themes), {"STANDARD", "hell", "kontrast_weiss", "kontrast_gelb", "blau_gelb"})
        for name, fields in self.themes.items():
            with self.subTest(schema=name):
                for field in ("bg", "select", "selectFill", "btnImprove", "btnSpeak", "btnApply"):
                    self.assertIn(field, fields)

    def test_rand_hebt_sich_von_hintergrund_und_fuellung_ab(self):
        for name, f in self.themes.items():
            with self.subTest(schema=name):
                self.assertGreaterEqual(_contrast(f["select"], f["bg"]), 4.5, "Rand gegen Hintergrund (WCAG verlangt 3:1)")
                self.assertGreaterEqual(_contrast(f["select"], f["selectFill"]), 4.5, "Rand gegen Füllung")

    def test_fuellung_unterscheidet_sich_von_den_normalen_knoepfen(self):
        # Ein markierter Knopf muss anders aussehen als die zwei anderen, nicht nur einen Rand haben.
        for name, f in self.themes.items():
            with self.subTest(schema=name):
                for btn in ("btnImprove", "btnSpeak", "btnApply"):
                    self.assertNotEqual(f["selectFill"], f[btn])

    def test_randfarbe_ist_leuchtend(self):
        import colorsys
        for name, f in self.themes.items():
            with self.subTest(schema=name):
                h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in f["select"]))
                self.assertGreaterEqual(s, 0.75, "kräftige, gesättigte Farbe statt Weiß oder Grau")

    def test_randfarbe_nicht_weiss_schwarz_und_nicht_gelb_bei_gelb(self):
        for name, f in self.themes.items():
            with self.subTest(schema=name):
                self.assertNotIn(f["select"], [(255, 255, 255), (0, 0, 0)])
        import colorsys

        def hue(c):
            return colorsys.rgb_to_hsv(*(x / 255 for x in c))[0] * 360
        # Bei Gelb auf Schwarz darf der Rand keine gelbe oder weiße Farbe sein: Abstand der Farbtöne zu Gelb mindestens 60 Grad.
        diff = abs(hue(self.themes["kontrast_gelb"]["select"]) - hue((255, 230, 0)))
        self.assertGreaterEqual(min(diff, 360 - diff), 60)

    def test_randfarben_passen_zu_den_schemata(self):
        t = self.themes
        self.assertEqual(t["STANDARD"]["select"], (57, 255, 20), "Standard: helles Grün")
        self.assertEqual(t["blau_gelb"]["select"], (57, 255, 20))
        self.assertEqual(t["kontrast_weiss"]["select"], (255, 45, 200), "Pink")
        self.assertEqual(t["kontrast_gelb"]["select"], (255, 45, 200))
        self.assertEqual(t["hell"]["selectFill"], (255, 255, 255), "im hellen Schema weiße Füllung, dunkler Rand")

    def test_service_nutzt_die_schemafarben_statt_fester_farben(self):
        ks = kotlin("KeyboardService.kt")
        self.assertIn("look.select", ks)
        self.assertNotIn("armColor", ks)


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
        self.assertIn('versionName = "0.5.1"', g)
        self.assertIn("versionCode = 7", g)


if __name__ == "__main__":
    unittest.main()
