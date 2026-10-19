package de.henri.keyboard

import android.content.Context
import android.graphics.Color
import kotlin.math.pow

/** Alle Farben eines Farbschemas (Theme). Rand 0 = kein Rand um die Tasten. */
data class Palette(
    val bg: Int,
    val keyBg: Int,
    val keyText: Int,
    val keyStroke: Int,
    val specialBg: Int,
    val deleteBg: Int,
    val shiftOn: Int,
    val panelBg: Int,
    val panelText: Int,
    val hintText: Int,
    val press: Int,
    val pressText: Int,
    val hlSingle: Int,
    val hlMulti: Int,
    val hlText: Int,
    val btnImprove: Int,
    val btnSpeak: Int,
    val btnApply: Int,
    val btnStop: Int,
)

/** Ein auswählbares Farbschema mit Name und Beschreibung für die Einstellungen. */
class Theme(val id: String, val name: String, val description: String, val palette: Palette)

/**
 * Aussehen und Bedienung der Tastatur. Wird in der Henri-App eingestellt und beim Öffnen der
 * Tastatur geladen. Die Standardwerte sind genau das ursprüngliche Aussehen.
 */
data class Look(
    val themeId: String,
    val palette: Palette,
    val keyTextSp: Float,
    val keyHeightDp: Int,
    val suggestionSp: Float,
    val speechRate: Float,
    val vibration: Boolean,
) {
    val bg get() = palette.bg
    val keyBg get() = palette.keyBg
    val keyText get() = palette.keyText
    val keyStroke get() = palette.keyStroke
    val specialBg get() = palette.specialBg
    val deleteBg get() = palette.deleteBg
    val shiftOn get() = palette.shiftOn
    val panelBg get() = palette.panelBg
    val panelText get() = palette.panelText
    val hintText get() = palette.hintText
    val press get() = palette.press
    val pressText get() = palette.pressText
    val hlSingle get() = palette.hlSingle
    val hlMulti get() = palette.hlMulti
    val hlText get() = palette.hlText
    val btnImprove get() = palette.btnImprove
    val btnSpeak get() = palette.btnSpeak
    val btnApply get() = palette.btnApply
    val btnStop get() = palette.btnStop

    /** Schriftfarbe auf einer Taste mit dem Hintergrund [fill]. */
    fun textOnKey(fill: Int) = if (fill == keyBg) keyText else onColor(fill)

    companion object {
        const val STANDARD = "standard"
        const val K_THEME = "theme"
        const val K_KEY_TEXT = "keyText"
        const val K_KEY_HEIGHT = "keyHeight"
        const val K_SUGGESTION = "suggestion"
        const val K_SPEECH = "speech"
        const val K_VIBRATION = "vibration"

        // Stufen; die jeweils erste bzw. mittlere ist der Standard (= bisheriges Aussehen).
        val KEY_TEXT_SP = listOf(26f, 30f, 34f)
        val KEY_HEIGHT_DP = listOf(58, 68, 80)
        val SUGGESTION_SP = listOf(24f, 30f, 36f, 42f)
        val SPEECH_RATE = listOf(0.75f, 0.95f, 1.2f)
        const val DEFAULT_SPEECH = 1

        private val yellow = Color.rgb(255, 193, 7)
        private val signalYellow = Color.rgb(255, 230, 0)
        private val cyan = Color.rgb(0, 229, 255)

        val themes: List<Theme> = listOf(
            Theme(
                STANDARD, "Standard (dunkel)", "Das bisherige Aussehen.",
                Palette(
                    bg = Color.rgb(18, 18, 18), keyBg = Color.rgb(58, 58, 62), keyText = Color.WHITE, keyStroke = 0,
                    specialBg = Color.rgb(32, 82, 140), deleteBg = Color.rgb(120, 40, 40), shiftOn = Color.rgb(200, 150, 0),
                    panelBg = Color.rgb(30, 30, 36), panelText = Color.WHITE, hintText = yellow,
                    press = yellow, pressText = Color.BLACK,
                    hlSingle = yellow, hlMulti = Color.rgb(46, 204, 113), hlText = Color.BLACK,
                    btnImprove = Color.rgb(30, 120, 60), btnSpeak = Color.rgb(32, 82, 140),
                    btnApply = Color.rgb(160, 90, 0), btnStop = Color.rgb(176, 42, 42),
                )
            ),
            Theme(
                "hell", "Hell", "Heller Hintergrund, dunkle Schrift. Gut bei Tageslicht.",
                Palette(
                    bg = Color.rgb(226, 230, 238), keyBg = Color.WHITE, keyText = Color.rgb(17, 21, 28),
                    keyStroke = Color.rgb(150, 160, 178),
                    specialBg = Color.rgb(176, 196, 226), deleteBg = Color.rgb(232, 184, 184), shiftOn = Color.rgb(255, 213, 79),
                    panelBg = Color.WHITE, panelText = Color.rgb(17, 21, 28), hintText = Color.rgb(125, 70, 0),
                    press = yellow, pressText = Color.BLACK,
                    hlSingle = Color.rgb(255, 213, 79), hlMulti = Color.rgb(120, 214, 150), hlText = Color.BLACK,
                    btnImprove = Color.rgb(20, 110, 55), btnSpeak = Color.rgb(25, 85, 165),
                    btnApply = Color.rgb(180, 95, 0), btnStop = Color.rgb(175, 35, 35),
                )
            ),
            Theme(
                "kontrast_weiss", "Kontrast: Weiß auf Schwarz", "Reines Schwarz, weiße Schrift, helle Tastenränder.",
                Palette(
                    bg = Color.BLACK, keyBg = Color.rgb(12, 12, 12), keyText = Color.WHITE, keyStroke = Color.WHITE,
                    specialBg = Color.WHITE, deleteBg = Color.WHITE, shiftOn = signalYellow,
                    panelBg = Color.BLACK, panelText = Color.WHITE, hintText = signalYellow,
                    press = signalYellow, pressText = Color.BLACK,
                    hlSingle = signalYellow, hlMulti = cyan, hlText = Color.BLACK,
                    btnImprove = Color.rgb(0, 230, 118), btnSpeak = cyan,
                    btnApply = yellow, btnStop = Color.rgb(255, 99, 99),
                )
            ),
            Theme(
                "kontrast_gelb", "Kontrast: Gelb auf Schwarz",
                "Sehr starker Kontrast. Gelb auf Schwarz sehen viele Menschen mit Sehschwäche besonders gut.",
                Palette(
                    bg = Color.BLACK, keyBg = Color.rgb(12, 12, 12), keyText = signalYellow, keyStroke = signalYellow,
                    specialBg = signalYellow, deleteBg = signalYellow, shiftOn = Color.WHITE,
                    panelBg = Color.BLACK, panelText = signalYellow, hintText = Color.WHITE,
                    press = Color.WHITE, pressText = Color.BLACK,
                    hlSingle = Color.WHITE, hlMulti = cyan, hlText = Color.BLACK,
                    btnImprove = signalYellow, btnSpeak = cyan,
                    btnApply = Color.WHITE, btnStop = Color.rgb(255, 99, 99),
                )
            ),
            Theme(
                "blau_gelb", "Blau und Gelb", "Farben, die man auch bei Rot-Grün-Schwäche gut unterscheidet.",
                Palette(
                    bg = Color.rgb(8, 16, 38), keyBg = Color.rgb(28, 44, 92), keyText = Color.WHITE, keyStroke = 0,
                    specialBg = Color.rgb(70, 100, 180), deleteBg = Color.rgb(70, 100, 180), shiftOn = Color.rgb(255, 214, 0),
                    panelBg = Color.rgb(18, 30, 66), panelText = Color.WHITE, hintText = Color.rgb(255, 214, 0),
                    press = Color.rgb(255, 214, 0), pressText = Color.BLACK,
                    hlSingle = Color.rgb(255, 214, 0), hlMulti = Color.rgb(79, 195, 247), hlText = Color.BLACK,
                    btnImprove = Color.rgb(25, 118, 210), btnSpeak = Color.rgb(0, 150, 170),
                    btnApply = Color.rgb(255, 214, 0), btnStop = Color.rgb(250, 250, 250),
                )
            ),
        )

        fun prefs(c: Context) = c.getSharedPreferences("henri_look", Context.MODE_PRIVATE)

        fun themeId(c: Context): String = prefs(c).getString(K_THEME, STANDARD).orEmpty()
            .let { id -> if (themes.any { it.id == id }) id else STANDARD }

        fun level(c: Context, key: String, default: Int, max: Int): Int =
            prefs(c).getInt(key, default).coerceIn(0, max)

        fun setLevel(c: Context, key: String, value: Int) = prefs(c).edit().putInt(key, value).apply()

        fun setTheme(c: Context, id: String) = prefs(c).edit().putString(K_THEME, id).apply()

        fun vibration(c: Context) = prefs(c).getBoolean(K_VIBRATION, true)

        fun setVibration(c: Context, on: Boolean) = prefs(c).edit().putBoolean(K_VIBRATION, on).apply()

        fun reset(c: Context) = prefs(c).edit().clear().apply()

        fun load(c: Context): Look {
            val id = themeId(c)
            return Look(
                themeId = id,
                palette = themes.first { it.id == id }.palette,
                keyTextSp = KEY_TEXT_SP[level(c, K_KEY_TEXT, 0, KEY_TEXT_SP.lastIndex)],
                keyHeightDp = KEY_HEIGHT_DP[level(c, K_KEY_HEIGHT, 0, KEY_HEIGHT_DP.lastIndex)],
                suggestionSp = SUGGESTION_SP[level(c, K_SUGGESTION, 0, SUGGESTION_SP.lastIndex)],
                speechRate = SPEECH_RATE[level(c, K_SPEECH, DEFAULT_SPEECH, SPEECH_RATE.lastIndex)],
                vibration = vibration(c),
            )
        }

        /** Schwarz oder Weiß, je nachdem, was auf der Fläche [fill] besser lesbar ist. */
        fun onColor(fill: Int): Int {
            fun lin(v: Int): Double {
                val s = v / 255.0
                return if (s <= 0.03928) s / 12.92 else ((s + 0.055) / 1.055).pow(2.4)
            }
            val l = 0.2126 * lin(Color.red(fill)) + 0.7152 * lin(Color.green(fill)) + 0.0722 * lin(Color.blue(fill))
            return if (l > 0.45) Color.BLACK else Color.WHITE
        }
    }
}
