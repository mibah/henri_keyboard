package de.henri.keyboard

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Einrichtung: Verbindung zum Server (anzeigen, trennen, verbinden), Tastatur aktivieren,
 * Proxy-Adresse eintragen, Verbindung und Tastatur testen.
 */
class MainActivity : Activity() {

    // Farben wie auf der Steuerungsseite am Rechner
    private val cBg = Color.rgb(14, 17, 22)
    private val cCard = Color.rgb(23, 28, 36)
    private val cLine = Color.rgb(42, 49, 64)
    private val cText = Color.rgb(243, 246, 251)
    private val cMuted = Color.rgb(169, 180, 198)
    private val cGreen = Color.rgb(46, 204, 113)
    private val cRed = Color.rgb(255, 93, 93)
    private val cAmber = Color.rgb(255, 185, 56)
    private val cBlue = Color.rgb(77, 163, 255)
    private val cGrey = Color.rgb(140, 148, 160)

    private val main = Handler(Looper.getMainLooper())
    private lateinit var connDot: TextView
    private lateinit var connTitle: TextView
    private lateinit var connSub: TextView
    private lateinit var connButton: Button

    private val poll = object : Runnable {
        override fun run() {
            refreshConnection()
            main.postDelayed(this, 3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(28))
        }

        // ---- Kopf ----
        col.addView(text("Henri", 34f, cText, bold = true).apply { setPadding(dp(4), dp(8), 0, 0) })
        col.addView(text("Tastatur mit KI-Korrektur", 17f, cMuted).apply { setPadding(dp(4), 0, 0, dp(18)) })

        // ---- Verbindung ----
        val connCard = card()
        connCard.addView(label("VERBINDUNG"))
        val connRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        connDot = text("●", 38f, cAmber)
        connRow.addView(connDot, LinearLayout.LayoutParams(-2, -2).apply { rightMargin = dp(14) })
        val connTexts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        connTitle = text("Prüfe …", 22f, cText, bold = true)
        connSub = text("", 15f, cMuted)
        connTexts.addView(connTitle)
        connTexts.addView(connSub)
        connRow.addView(connTexts, LinearLayout.LayoutParams(0, -2, 1f))
        connCard.addView(connRow)
        connButton = button("Trennen", Color.rgb(38, 48, 63), cText) {
            Api.setEnabled(this, !Api.enabled(this))
            renderChecking()
            refreshConnection()
        }
        connCard.addView(connButton)
        col.addView(connCard)

        // ---- Einrichtung ----
        val setup = card()
        setup.addView(label("1  TASTATUR EINSCHALTEN"))
        setup.addView(body("Einschalten, dann hierher zurückkehren."))
        setup.addView(button("Tastatur aktivieren", cBlue, Color.rgb(6, 18, 33)) {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        })
        setup.addView(label("2  TASTATUR AUSWÄHLEN").apply { setPadding(0, dp(22), 0, dp(4)) })
        setup.addView(body("Oder im Textfeld auf das Tastatursymbol tippen."))
        setup.addView(button("Tastatur auswählen", cBlue, Color.rgb(6, 18, 33)) {
            (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker()
        })
        col.addView(setup)

        // ---- Server ----
        val server = card()
        server.addView(label("3  SERVER"))
        server.addView(body("Adresse des Rechners im selben WLAN, auf dem Henri läuft."))
        val url = field(Api.baseUrl(this), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        server.addView(url)
        server.addView(body("Token (leer lassen, wenn der Server keinen verlangt)").apply { setPadding(0, dp(14), 0, dp(4)) })
        val token = field(
            Api.token(this),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        )
        server.addView(token)
        val speak = CheckBox(this).apply {
            text = "Verbesserten Text automatisch vorlesen"
            isChecked = Api.autoSpeak(this@MainActivity)
            setTextColor(cText)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            buttonTintList = ColorStateList.valueOf(cGreen)
            setPadding(dp(8), dp(14), 0, dp(6))
        }
        server.addView(speak)
        val result = body("").apply { setPadding(0, dp(10), 0, 0) }
        server.addView(button("Speichern und Verbindung testen", cGreen, Color.rgb(7, 19, 12)) {
            Api.save(this@MainActivity, url.text.toString(), token.text.toString(), speak.isChecked)
            result.setTextColor(cMuted)
            result.text = "Teste …"
            thread {
                val model = Api.check(this@MainActivity)
                runOnUiThread {
                    if (model != null) {
                        result.setTextColor(cGreen)
                        result.text = "Verbunden, Modell: $model"
                    } else {
                        result.setTextColor(cRed)
                        result.text = "Keine Verbindung. Gleiches WLAN? Server gestartet? Adresse richtig?"
                    }
                    refreshConnection()
                }
            }
        })
        server.addView(result)
        col.addView(server)

        // ---- Für Einrichter: Aussehen und Bedienung (aufklappbar) ----
        col.addView(buildLookCard())

        // ---- Ausprobieren ----
        val tryout = card()
        tryout.addView(label("4  AUSPROBIEREN"))
        tryout.addView(
            field("", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE).apply {
                hint = "Tippe hier mit der Henri Tastatur …"
                minLines = 3
                gravity = Gravity.TOP
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            }
        )
        col.addView(tryout)

        col.addView(text("Version ${versionName()}", 13f, cGrey).apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(6), 0, 0)
        }, LinearLayout.LayoutParams(-1, -2))

        // Android 15 zeichnet Apps hinter Status- und Navigationsleiste: Inhalt darunter schieben.
        setContentView(ScrollView(this).apply {
            setBackgroundColor(cBg)
            addView(col)
            clipToPadding = false
            @Suppress("DEPRECATION")
            setOnApplyWindowInsetsListener { v, insets ->
                v.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
                insets
            }
        })
    }

    override fun onResume() {
        super.onResume()
        main.post(poll)
    }

    override fun onPause() {
        main.removeCallbacks(poll)
        super.onPause()
    }

    // ---- Verbindung anzeigen ----

    private fun renderChecking() {
        connDot.setTextColor(cAmber)
        connTitle.text = "Prüfe …"
        connSub.text = ""
        connButton.isEnabled = false
    }

    private fun refreshConnection() {
        if (!Api.enabled(this)) {
            connDot.setTextColor(cGrey)
            connTitle.text = "Getrennt"
            connSub.text = "Die Tastatur nutzt den Server nicht. Er kann weiterlaufen."
            setConnButton("Verbinden", cGreen, Color.rgb(7, 19, 12))
            return
        }
        thread {
            val model = Api.check(this)
            runOnUiThread {
                if (!Api.enabled(this)) return@runOnUiThread // inzwischen getrennt
                if (model != null) {
                    connDot.setTextColor(cGreen)
                    connTitle.text = "Verbunden"
                    connSub.text = "Modell: $model"
                } else {
                    connDot.setTextColor(cRed)
                    connTitle.text = "Server nicht erreichbar"
                    connSub.text = "Läuft der Server? Gleiches WLAN? Adresse richtig?"
                }
                setConnButton("Trennen", Color.rgb(38, 48, 63), cText)
            }
        }
    }

    private fun setConnButton(label: String, fill: Int, textColor: Int) {
        connButton.isEnabled = true
        connButton.text = label
        connButton.setTextColor(textColor)
        connButton.background = ripple(fill, 14)
    }

    // ---- Aussehen und Bedienung (für Einrichter, aufklappbar) ----

    private fun buildLookCard(): LinearLayout {
        val card = card()
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            isClickable = true
        }
        val titles = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titles.addView(label("FÜR EINRICHTER"))
        titles.addView(text("Aussehen und Bedienung", 20f, cText, bold = true))
        titles.addView(text("Schriftgröße, Farbschema, Vorlesen", 15f, cMuted))
        val arrow = text("▾", 26f, cMuted)
        header.addView(titles, LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(arrow)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
        }
        header.setOnClickListener {
            val open = content.visibility != View.VISIBLE
            content.visibility = if (open) View.VISIBLE else View.GONE
            arrow.text = if (open) "▴" else "▾"
            if (open) renderLook(content)
        }
        card.addView(header)
        card.addView(content)
        return card
    }

    /** Baut den Inhalt neu auf; nach jeder Auswahl, damit die gewählte Stufe markiert ist. */
    private fun renderLook(box: LinearLayout) {
        box.removeAllViews()
        box.addView(section("SCHRIFT DER TASTEN"))
        box.addView(chips(listOf("Normal", "Groß", "Sehr groß"), Look.level(this, Look.K_KEY_TEXT, 0, Look.KEY_TEXT_SP.lastIndex)) {
            Look.setLevel(this, Look.K_KEY_TEXT, it)
            renderLook(box)
        })
        box.addView(section("HÖHE DER TASTEN"))
        box.addView(chips(listOf("Normal", "Hoch", "Sehr hoch"), Look.level(this, Look.K_KEY_HEIGHT, 0, Look.KEY_HEIGHT_DP.lastIndex)) {
            Look.setLevel(this, Look.K_KEY_HEIGHT, it)
            renderLook(box)
        })
        box.addView(section("SCHRIFT DES VORSCHLAGS"))
        box.addView(chips(listOf("Normal", "Groß", "Sehr groß", "Extra"), Look.level(this, Look.K_SUGGESTION, 0, Look.SUGGESTION_SP.lastIndex)) {
            Look.setLevel(this, Look.K_SUGGESTION, it)
            renderLook(box)
        })

        box.addView(section("FARBSCHEMA"))
        val current = Look.themeId(this)
        Look.themes.forEach { theme ->
            box.addView(themeRow(theme, theme.id == current) {
                Look.setTheme(this, theme.id)
                renderLook(box)
            })
        }

        box.addView(section("VORLESEN"))
        box.addView(chips(listOf("Langsam", "Normal", "Schneller"), Look.level(this, Look.K_SPEECH, Look.DEFAULT_SPEECH, Look.SPEECH_RATE.lastIndex)) {
            Look.setLevel(this, Look.K_SPEECH, it)
            renderLook(box)
        })
        box.addView(CheckBox(this).apply {
            text = "Vibration beim Tippen"
            isChecked = Look.vibration(this@MainActivity)
            setTextColor(cText)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            buttonTintList = ColorStateList.valueOf(cGreen)
            setPadding(dp(8), dp(14), 0, dp(4))
            setOnCheckedChangeListener { _, on -> Look.setVibration(this@MainActivity, on) }
        })

        box.addView(body("Die Änderungen gelten, sobald die Tastatur das nächste Mal geöffnet wird. Zum Ausprobieren unten in das Testfeld tippen.").apply {
            setPadding(0, dp(16), 0, 0)
        })
        box.addView(button("Auf Standard zurücksetzen", Color.rgb(38, 48, 63), cText) {
            Look.reset(this)
            renderLook(box)
        })
    }

    private fun section(s: String) = text(s, 13f, cMuted, bold = true).apply {
        letterSpacing = 0.08f
        setPadding(dp(2), dp(20), 0, dp(8))
    }

    /** Eine Reihe gleich breiter Auswahlfelder; das gewählte ist grün. */
    private fun chips(labels: List<String>, selected: Int, onSelect: (Int) -> Unit): LinearLayout {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        labels.forEachIndexed { i, label ->
            val on = i == selected
            row.addView(TextView(this).apply {
                text = label
                gravity = Gravity.CENTER
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
                setTypeface(typeface, Typeface.BOLD)
                setTextColor(if (on) Color.rgb(7, 19, 12) else cText)
                background = rounded(if (on) cGreen else cBg, 12, if (on) cGreen else cLine)
                setPadding(dp(4), dp(14), dp(4), dp(14))
                setOnClickListener { onSelect(i) }
            }, LinearLayout.LayoutParams(0, -2, 1f).apply { if (i > 0) leftMargin = dp(8) })
        }
        return row
    }

    /** Eine Zeile pro Farbschema: kleines Farbmuster, Name, Beschreibung, Haken beim gewählten. */
    private fun themeRow(theme: Theme, selected: Boolean, onClick: () -> Unit): LinearLayout {
        val p = theme.palette
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = rounded(cBg, 14, if (selected) cGreen else cLine).apply { if (selected) setStroke(dp(2), cGreen) }
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) }
            setOnClickListener { onClick() }
        }
        val swatch = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = rounded(p.bg, 10, cLine)
            setPadding(dp(6), dp(6), dp(6), dp(6))
        }
        fun sample(t: String, fill: Int, textColor: Int, stroke: Int) = TextView(this).apply {
            text = t
            gravity = Gravity.CENTER
            setTextColor(textColor)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            setTypeface(typeface, Typeface.BOLD)
            background = rounded(fill, 6, if (stroke != 0) stroke else null)
        }
        swatch.addView(sample("A", p.keyBg, p.keyText, p.keyStroke), LinearLayout.LayoutParams(dp(34), dp(34)))
        swatch.addView(sample("a", p.hlSingle, p.hlText, 0), LinearLayout.LayoutParams(dp(34), dp(34)).apply { leftMargin = dp(6) })
        row.addView(swatch, LinearLayout.LayoutParams(-2, -2).apply { rightMargin = dp(14) })
        val texts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        texts.addView(text(theme.name, 17f, cText, bold = true))
        texts.addView(text(theme.description, 14f, cMuted))
        row.addView(texts, LinearLayout.LayoutParams(0, -2, 1f))
        if (selected) row.addView(text("✓", 24f, cGreen, bold = true))
        return row
    }

    // ---- Bausteine fürs Aussehen ----

    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(cCard, 20, cLine)
        setPadding(dp(20), dp(18), dp(20), dp(20))
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(14) }
    }

    private fun text(s: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = s
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun label(s: String) = text(s, 13f, cGreen, bold = true).apply {
        letterSpacing = 0.08f
        setPadding(0, 0, 0, dp(4))
    }

    private fun body(s: String) = text(s, 16f, cMuted).apply { setPadding(0, 0, 0, dp(10)) }

    private fun field(initial: String, type: Int) = EditText(this).apply {
        setText(initial)
        inputType = type
        setTextColor(cText)
        setHintTextColor(cGrey)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
        background = rounded(cBg, 12, cLine)
        setPadding(dp(14), dp(14), dp(14), dp(14))
    }

    private fun button(label: String, fill: Int, textColor: Int, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setTextColor(textColor)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
        setTypeface(typeface, Typeface.BOLD)
        stateListAnimator = null // keine Standard-Erhebung, sieht flacher und moderner aus
        minHeight = dp(56)
        background = ripple(fill, 14)
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) }
        setOnClickListener { onClick() }
    }

    private fun rounded(fill: Int, radiusDp: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(fill)
        cornerRadius = dp(radiusDp).toFloat()
        if (stroke != null) setStroke(dp(1), stroke)
    }

    private fun ripple(fill: Int, radiusDp: Int) =
        RippleDrawable(ColorStateList.valueOf(Color.argb(60, 255, 255, 255)), rounded(fill, radiusDp), null)

    @Suppress("DEPRECATION")
    private fun versionName(): String =
        try { packageManager.getPackageInfo(packageName, 0).versionName ?: "?" } catch (e: Exception) { "?" }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}
