package de.henri.keyboard

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.text.method.ScrollingMovementMethod
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Große, kontrastreiche QWERTZ-Tastatur mit KI-Korrektur:
 * Verbessern -> Vorschlag erscheint groß und wird vorgelesen -> Übernehmen ersetzt den Feldtext.
 * Gesendet wird nie automatisch.
 */
class KeyboardService : InputMethodService() {

    private val main = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    private lateinit var suggestionView: TextView
    private lateinit var scrollHint: TextView
    private lateinit var aiBar: LinearLayout
    private lateinit var applyButton: TextView
    private lateinit var keysContainer: LinearLayout

    private var shift = false
    private var symbols = false
    private var suggestion: String? = null
    private var sourceText: String? = null
    private var requestId = 0
    private val letterKeys = mutableListOf<Pair<TextView, String>>()

    private val bg = Color.rgb(18, 18, 18)
    private val keyBg = Color.rgb(58, 58, 62)
    private val specialBg = Color.rgb(32, 82, 140)

    override fun onCreate() {
        super.onCreate()
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.GERMAN
                tts?.setSpeechRate(0.95f)
                ttsReady = true
            }
        }
    }

    override fun onDestroy() {
        tts?.shutdown()
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onCreateInputView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
            setPadding(dp(4), dp(4), dp(4), dp(6))
        }

        suggestionView = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 24f)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(30, 30, 36))
            setPadding(dp(12), dp(8), dp(12), dp(8))
            maxLines = 6
            // Lange Vorschläge: im Feld wischen. Kein Scrollbalken: der per Code eingeschaltete
            // Balken hat die Tastatur beim Zeichnen zum Absturz gebracht.
            movementMethod = ScrollingMovementMethod.getInstance()
            visibility = View.GONE
        }
        root.addView(suggestionView, LinearLayout.LayoutParams(-1, -2))

        scrollHint = TextView(this).apply {
            text = "↕ Mehr Text: im Feld nach oben oder unten wischen"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setTextColor(Color.rgb(255, 193, 7))
            setBackgroundColor(Color.rgb(30, 30, 36))
            setPadding(dp(12), 0, dp(12), dp(6))
            visibility = View.GONE
        }
        root.addView(scrollHint, LinearLayout.LayoutParams(-1, -2))

        aiBar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        aiBar.addView(bigButton("Verbessern", Color.rgb(30, 120, 60)) { improve() }, weighted(1.2f))
        aiBar.addView(bigButton("Vorlesen", specialBg) { speakCurrent() }, weighted(1f))
        applyButton = bigButton("Übernehmen", Color.rgb(160, 90, 0)) { applySuggestion() }
        aiBar.addView(applyButton, weighted(1.2f))
        root.addView(aiBar, LinearLayout.LayoutParams(-1, dp(56)))

        keysContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(keysContainer, LinearLayout.LayoutParams(-1, -2))
        buildKeys()
        refreshApplyButton()
        return root
    }

    override fun onStartInputView(info: EditorInfo, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        // In Passwortfeldern keine KI: Text würde sonst an den Server gehen.
        aiBar.visibility = if (isPasswordField(info)) View.GONE else View.VISIBLE
        clearSuggestion()
        updateShiftFromCaps()
    }

    override fun onFinishInputView(finishingInput: Boolean) {
        tts?.stop()
        clearSuggestion()
        super.onFinishInputView(finishingInput)
    }

    private fun isPasswordField(info: EditorInfo): Boolean {
        val cls = info.inputType and InputType.TYPE_MASK_CLASS
        val v = info.inputType and InputType.TYPE_MASK_VARIATION
        return when (cls) {
            InputType.TYPE_CLASS_TEXT ->
                v == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
                    v == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD ||
                    v == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD
            InputType.TYPE_CLASS_NUMBER -> v == InputType.TYPE_NUMBER_VARIATION_PASSWORD
            else -> false
        }
    }

    // ---------- KI-Funktionen ----------

    private fun fieldText(): String? {
        val ic = currentInputConnection ?: return null
        val before = ic.getTextBeforeCursor(MAX_CHARS, 0)?.toString().orEmpty()
        val after = ic.getTextAfterCursor(MAX_CHARS, 0)?.toString().orEmpty()
        return before + after
    }

    private fun improve() {
        val text = fieldText()
        if (text.isNullOrBlank()) {
            showStatus("Erst etwas schreiben, dann „Verbessern“.")
            return
        }
        val id = ++requestId
        showStatus("Einen Moment …")
        executor.execute {
            val result = try {
                Api.correct(this, text)
            } catch (e: Exception) {
                null
            }
            main.post {
                if (id != requestId) return@post // inzwischen neuere Anfrage oder Feld gewechselt
                when {
                    result == null -> showStatus("Keine Verbindung zum Server.")
                    result == text -> showStatus("Schon in Ordnung: $text")
                        .also { speak("Schon in Ordnung.") }
                    else -> {
                        sourceText = text
                        suggestion = result
                        suggestionView.text = result
                        suggestionView.scrollTo(0, 0)
                        suggestionView.visibility = View.VISIBLE
                        suggestionView.post {
                            scrollHint.visibility =
                                if (suggestionView.canScrollVertically(1)) View.VISIBLE else View.GONE
                        }
                        refreshApplyButton()
                        if (Api.autoSpeak(this)) speak(result)
                    }
                }
            }
        }
    }

    private fun applySuggestion() {
        val s = suggestion ?: return
        val ic = currentInputConnection ?: return
        val before = ic.getTextBeforeCursor(MAX_CHARS, 0)?.toString().orEmpty()
        val after = ic.getTextAfterCursor(MAX_CHARS, 0)?.toString().orEmpty()
        if (before + after != sourceText) {
            showStatus("Der Text hat sich geändert. Bitte nochmal „Verbessern“.")
            return
        }
        ic.beginBatchEdit()
        ic.deleteSurroundingText(before.length, after.length)
        ic.commitText(s, 1)
        ic.endBatchEdit()
        tts?.stop()
        clearSuggestion()
        updateShiftFromCaps()
    }

    private fun speakCurrent() {
        val text = suggestion ?: fieldText()
        if (text.isNullOrBlank()) speak("Es ist noch nichts geschrieben.") else speak(text)
    }

    private fun speak(text: String) {
        if (ttsReady) tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "henri")
    }

    private fun showStatus(msg: String) {
        suggestion = null
        sourceText = null
        suggestionView.text = msg
        suggestionView.visibility = View.VISIBLE
        scrollHint.visibility = View.GONE
        refreshApplyButton()
    }

    private fun clearSuggestion() {
        requestId++
        suggestion = null
        sourceText = null
        if (::suggestionView.isInitialized) {
            suggestionView.text = ""
            suggestionView.visibility = View.GONE
            scrollHint.visibility = View.GONE
            refreshApplyButton()
        }
    }

    private fun refreshApplyButton() {
        applyButton.alpha = if (suggestion == null) 0.35f else 1f
    }

    // ---------- Tasten ----------

    private val rowsLetters = listOf(
        listOf("q", "w", "e", "r", "t", "z", "u", "i", "o", "p", "ü"),
        listOf("a", "s", "d", "f", "g", "h", "j", "k", "l", "ö", "ä"),
        listOf("y", "x", "c", "v", "b", "n", "m", "ß")
    )
    private val rowsSymbols = listOf(
        listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"),
        listOf("@", "#", "€", "%", "&", "*", "-", "+", "(", ")"),
        listOf("!", "\"", "'", ":", ";", "/", "?", "=")
    )

    private fun buildKeys() {
        keysContainer.removeAllViews()
        letterKeys.clear()
        val rows = if (symbols) rowsSymbols else rowsLetters
        keysContainer.addView(keyRow(rows[0]))
        keysContainer.addView(keyRow(rows[1]))

        val row3 = row()
        if (!symbols) row3.addView(actionKey("⇧", 1.4f, if (shift) Color.rgb(200, 150, 0) else keyBg) {
            shift = !shift
            applyShiftLabels()
            buildKeys()
        })
        rows[2].forEach { row3.addView(charKey(it, 1f)) }
        row3.addView(repeatKey("⌫", 1.4f))
        keysContainer.addView(row3)

        val row4 = row()
        row4.addView(actionKey(if (symbols) "ABC" else "123", 1.4f, keyBg) {
            symbols = !symbols
            buildKeys()
        })
        row4.addView(charKey(",", 1f))
        row4.addView(actionKey("Leerzeichen", 4.5f, keyBg) { typeText(" ") })
        row4.addView(charKey(".", 1f))
        row4.addView(actionKey("↵", 1.4f, specialBg) { pressEnter() })
        keysContainer.addView(row4)
        applyShiftLabels()
    }

    private fun keyRow(keys: List<String>): LinearLayout {
        val r = row()
        keys.forEach { r.addView(charKey(it, 1f)) }
        return r
    }

    private fun row() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        layoutParams = LinearLayout.LayoutParams(-1, dp(KEY_HEIGHT_DP))
    }

    private fun charKey(label: String, weight: Float): TextView {
        val k = keyView(label, weight, keyBg)
        val isLetter = label.length == 1 && label[0].isLetter()
        if (isLetter) letterKeys.add(k to label)
        k.setOnTouchListener { v, e ->
            if (e.action == MotionEvent.ACTION_DOWN) {
                v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                typeText(if (isLetter && shift) label.uppercase() else label)
                showPress(v as TextView)
            } else if (e.action == MotionEvent.ACTION_UP || e.action == MotionEvent.ACTION_CANCEL) {
                hidePress(v as TextView)
            }
            true
        }
        return k
    }

    private fun actionKey(label: String, weight: Float, color: Int, onTap: () -> Unit): TextView {
        val k = keyView(label, weight, color)
        k.setOnTouchListener { v, e ->
            if (e.action == MotionEvent.ACTION_DOWN) {
                v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                showPress(v as TextView)
                onTap()
            } else if (e.action == MotionEvent.ACTION_UP || e.action == MotionEvent.ACTION_CANCEL) {
                hidePress(v as TextView)
            }
            true
        }
        if (label == "Leerzeichen") k.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
        return k
    }

    /** Löschen: gedrückt halten wiederholt. */
    private fun repeatKey(label: String, weight: Float): TextView {
        val k = keyView(label, weight, Color.rgb(120, 40, 40))
        val repeater = object : Runnable {
            override fun run() {
                sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL)
                main.postDelayed(this, 60)
            }
        }
        k.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                    showPress(v as TextView)
                    sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL)
                    main.postDelayed(repeater, 400)
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    hidePress(v as TextView)
                    main.removeCallbacks(repeater)
                    updateShiftFromCaps()
                }
            }
            true
        }
        return k
    }

    private fun keyView(label: String, weight: Float, color: Int) = TextView(this).apply {
        text = label
        tag = color
        gravity = Gravity.CENTER
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 26f)
        setTypeface(typeface, Typeface.BOLD)
        background = GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(8).toFloat()
        }
        val lp = LinearLayout.LayoutParams(0, -1, weight)
        lp.setMargins(dp(2), dp(3), dp(2), dp(3))
        layoutParams = lp
    }

    private fun bigButton(label: String, color: Int, onTap: () -> Unit) = TextView(this).apply {
        text = label
        gravity = Gravity.CENTER
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)
        setTypeface(typeface, Typeface.BOLD)
        background = GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(8).toFloat()
        }
        setOnClickListener {
            it.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            onTap()
        }
    }

    private fun weighted(w: Float) = LinearLayout.LayoutParams(0, -1, w).apply {
        setMargins(dp(2), dp(2), dp(2), dp(2))
    }

    // ---------- Rückmeldung beim Drücken ----------

    private val pressColor = Color.rgb(255, 193, 7)

    /** Gedrückte Taste leuchtet gelb. */
    private fun showPress(v: TextView) {
        (v.background as? GradientDrawable)?.setColor(pressColor)
        v.setTextColor(Color.BLACK)
    }

    private fun hidePress(v: TextView) {
        (v.background as? GradientDrawable)?.setColor(v.tag as? Int ?: keyBg)
        v.setTextColor(Color.WHITE)
    }

    private fun applyShiftLabels() {
        letterKeys.forEach { (view, base) -> view.text = if (shift) base.uppercase() else base }
    }

    // ---------- Eingabe ----------

    private fun typeText(s: String) {
        currentInputConnection?.commitText(s, 1)
        // Neuer Text macht einen alten Vorschlag ungültig.
        if (suggestion != null) clearSuggestion()
        updateShiftFromCaps()
    }

    private fun pressEnter() {
        val info = currentInputEditorInfo
        val action = info?.imeOptions?.and(EditorInfo.IME_MASK_ACTION) ?: EditorInfo.IME_ACTION_NONE
        val noEnterAction = info?.imeOptions?.and(EditorInfo.IME_FLAG_NO_ENTER_ACTION) != 0
        if (!noEnterAction && (action == EditorInfo.IME_ACTION_SEND || action == EditorInfo.IME_ACTION_GO ||
                action == EditorInfo.IME_ACTION_SEARCH)
        ) {
            currentInputConnection?.performEditorAction(action)
        } else {
            sendDownUpKeyEvents(KeyEvent.KEYCODE_ENTER)
        }
        clearSuggestion()
        updateShiftFromCaps()
    }

    /** Automatische Großschreibung am Satzanfang, wie es das Feld verlangt. */
    private fun updateShiftFromCaps() {
        val info = currentInputEditorInfo ?: return
        val caps = currentInputConnection?.getCursorCapsMode(info.inputType) ?: 0
        val want = caps != 0
        if (want != shift && !symbols) {
            shift = want
            if (::keysContainer.isInitialized) buildKeys()
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val MAX_CHARS = 4000
        private const val KEY_HEIGHT_DP = 58
    }
}
