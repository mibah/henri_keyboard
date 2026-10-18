package de.henri.keyboard

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.text.InputType
import android.text.SpannableString
import android.text.style.BackgroundColorSpan
import android.text.style.ForegroundColorSpan
import android.text.method.ScrollingMovementMethod
import android.util.TypedValue
import android.view.GestureDetector
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.animation.LinearInterpolator
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
    private var speaking = false
    private var utteranceCounter = 0
    private var currentUtterance = ""

    private lateinit var suggestionView: TextView
    private lateinit var scrollHint: TextView
    private lateinit var hintRow: LinearLayout
    private lateinit var spinner: Spinner
    private lateinit var speakButton: TextView
    private lateinit var aiBar: LinearLayout
    private lateinit var applyButton: TextView
    private lateinit var keysContainer: LinearLayout

    private var shift = false
    private var symbols = false
    private var suggestion: String? = null
    private var sourceText: String? = null
    private var requestId = 0

    // "Falsches Wort? Antippen, nochmal antippen": Kandidaten für die zuletzt angetippte Stelle
    private var candidates: List<String> = emptyList()
    private var candidateIndex = 0
    private var candidateKey: String? = null // Text vor dem Wort; erkennt dieselbe Stelle wieder
    private val rejected = mutableListOf<String>()
    private var rewordBusy = false
    private var selection: IntRange? = null // markiertes (gelbes) Wort im Vorschlag
    private val letterKeys = mutableListOf<Pair<TextView, String>>()

    private val bg = Color.rgb(18, 18, 18)
    private val keyBg = Color.rgb(58, 58, 62)
    private val specialBg = Color.rgb(32, 82, 140)
    private val stopBg = Color.rgb(176, 42, 42)

    override fun onCreate() {
        super.onCreate()
        initTts()
    }

    /**
     * Verbindet mit der Sprachengine. Wird auch gebraucht, wenn Android die Engine zwischendurch beendet
     * ("not bound to TTS engine"): Dann muss neu verbunden werden, sonst bleibt die Tastatur stumm.
     */
    private fun initTts(onReady: (() -> Unit)? = null) {
        ttsReady = false
        tts?.shutdown()
        tts = TextToSpeech(this) { status ->
            main.post {
                if (status != TextToSpeech.SUCCESS) {
                    ttsReady = false
                    return@post
                }
                tts?.language = Locale.GERMAN
                tts?.setSpeechRate(0.95f)
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {}
                    override fun onDone(utteranceId: String?) = utteranceEnded(utteranceId)
                    override fun onStop(utteranceId: String?, interrupted: Boolean) = utteranceEnded(utteranceId)

                    @Deprecated("Pflicht-Override der Basisklasse")
                    override fun onError(utteranceId: String?) = utteranceEnded(utteranceId)
                })
                ttsReady = true
                onReady?.invoke()
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
            val gestures = GestureDetector(this@KeyboardService, object : GestureDetector.SimpleOnGestureListener() {
                override fun onSingleTapUp(e: MotionEvent): Boolean {
                    onWordTap(e.x, e.y)
                    return true
                }
            })
            // false: das Feld behandelt Wischen weiterhin selbst (Scrollen)
            setOnTouchListener { _, ev ->
                gestures.onTouchEvent(ev)
                false
            }
        }
        root.addView(suggestionView, LinearLayout.LayoutParams(-1, -2))

        hintRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.rgb(30, 30, 36))
            setPadding(dp(12), 0, dp(12), dp(6))
            visibility = View.GONE
        }
        spinner = Spinner(this, Color.rgb(255, 193, 7)).apply { visibility = View.GONE }
        hintRow.addView(spinner, LinearLayout.LayoutParams(dp(22), dp(22)).apply { rightMargin = dp(10) })
        scrollHint = TextView(this).apply {
            text = HINT_SELECT
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setTextColor(Color.rgb(255, 193, 7))
        }
        hintRow.addView(scrollHint, LinearLayout.LayoutParams(-2, -2))
        root.addView(hintRow, LinearLayout.LayoutParams(-1, -2))

        aiBar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        aiBar.addView(bigButton("Verbessern", Color.rgb(30, 120, 60)) { improve() }, weighted(1.2f))
        speakButton = bigButton("Vorlesen", specialBg) { speakCurrent() }
        aiBar.addView(speakButton, weighted(1f))
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
        stopSpeaking()
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
        showBusy("Ich überarbeite deinen Text …")
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
                        resetRewordState()
                        showSuggestionText(result)
                        suggestionView.scrollTo(0, 0)
                        suggestionView.visibility = View.VISIBLE
                        suggestionView.post { resetHint() }
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
        stopSpeaking()
        clearSuggestion()
        updateShiftFromCaps()
    }

    /** Beim Lesen wird der Knopf zu „Stopp“. */
    private fun speakCurrent() {
        if (speaking) {
            stopSpeaking()
            return
        }
        val text = suggestion ?: fieldText()
        if (text.isNullOrBlank()) speak("Es ist noch nichts geschrieben.") else speak(text)
    }

    private fun speak(text: String, retry: Boolean = true) {
        if (!ttsReady) {
            if (retry) initTts { speak(text, retry = false) }
            return
        }
        currentUtterance = "henri-${++utteranceCounter}"
        setSpeaking(true)
        val result = tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, currentUtterance)
        if (result != TextToSpeech.SUCCESS) {
            // Engine nicht mehr verbunden: einmal neu verbinden und noch einmal versuchen.
            setSpeaking(false)
            ttsReady = false
            if (retry) initTts { speak(text, retry = false) }
        }
    }

    private fun stopSpeaking() {
        tts?.stop()
        setSpeaking(false)
    }

    /** Ende einer Ansage; Meldungen einer schon abgelösten Ansage werden ignoriert. */
    private fun utteranceEnded(id: String?) {
        main.post { if (id == currentUtterance) setSpeaking(false) }
    }

    private fun setSpeaking(on: Boolean) {
        speaking = on
        if (!::speakButton.isInitialized) return
        speakButton.text = if (on) "Stopp" else "Vorlesen"
        (speakButton.background as? GradientDrawable)?.setColor(if (on) stopBg else specialBg)
    }

    private fun showStatus(msg: String) {
        suggestion = null
        sourceText = null
        suggestionView.text = msg
        suggestionView.scrollTo(0, 0)
        suggestionView.visibility = View.VISIBLE
        hideHint()
        refreshApplyButton()
    }

    private fun clearSuggestion() {
        requestId++
        suggestion = null
        sourceText = null
        resetRewordState()
        if (::suggestionView.isInitialized) {
            suggestionView.text = ""
            suggestionView.scrollTo(0, 0)
            suggestionView.visibility = View.GONE
            hideHint()
            refreshApplyButton()
        }
    }

    // ---------- Falsches Wort ersetzen ----------

    private fun resetRewordState() {
        candidates = emptyList()
        candidateIndex = 0
        candidateKey = null
        rejected.clear()
        rewordBusy = false
        selection = null
    }

    /** Zeigt den Vorschlag; ein geändertes Wort ([hlStart] bis [hlEnd]) wird gelb markiert. */
    private fun showSuggestionText(text: String, hlStart: Int = -1, hlEnd: Int = -1) {
        val styled = SpannableString(text)
        if (hlStart in 0 until hlEnd) {
            styled.setSpan(BackgroundColorSpan(Color.rgb(255, 193, 7)), hlStart, hlEnd, 0)
            styled.setSpan(ForegroundColorSpan(Color.BLACK), hlStart, hlEnd, 0)
        }
        suggestionView.text = styled
    }

    private fun resetHint() {
        val base = if (selection != null) HINT_RENEW else HINT_SELECT
        scrollHint.text = if (suggestionView.canScrollVertically(1)) "$base  ·  ↕ Mehr Text: wischen" else base
        spinner.visibility = View.GONE
        hintRow.visibility = if (suggestion == null) View.GONE else View.VISIBLE
    }

    private fun showHint(msg: String) {
        scrollHint.text = msg
        spinner.visibility = View.GONE
        hintRow.visibility = View.VISIBLE
    }

    /** Hinweiszeile mit sich drehendem Kreis: zeigt, dass der Server gerade arbeitet. */
    private fun showBusy(msg: String) {
        scrollHint.text = msg
        spinner.visibility = View.VISIBLE
        hintRow.visibility = View.VISIBLE
    }

    private fun hideHint() {
        spinner.visibility = View.GONE
        hintRow.visibility = View.GONE
    }

    private fun isWordChar(c: Char) = c.isLetterOrDigit() || c == '\'' || c == '’'

    /** Das Wort an der Textposition [offset]; ein Tipp direkt hinter ein Wort zählt zu ihm. */
    private fun wordRange(text: String, offset: Int): IntRange? {
        var i = offset.coerceIn(0, text.length)
        if (i >= text.length || !isWordChar(text[i])) i--
        if (i < 0 || !isWordChar(text[i])) return null
        var start = i
        while (start > 0 && isWordChar(text[start - 1])) start--
        var end = i
        while (end < text.length - 1 && isWordChar(text[end + 1])) end++
        return start..end
    }

    /** Der Text ab dem Anfang des Satzes, in dem [start] liegt, bis zum Ende. */
    private fun fromSentenceStart(text: String, start: Int): String {
        var s = start
        while (s > 0 && text[s - 1] !in ".!?\n") s--
        return text.substring(s).trim()
    }

    /** Erster Tipp markiert ein Wort gelb, ein zweiter Tipp auf das markierte Wort ersetzt es. */
    private fun onWordTap(x: Float, y: Float) {
        val text = suggestion ?: return // nur im Vorschlag, nicht bei Statusmeldungen
        if (rewordBusy) return
        val range = wordRange(text, suggestionView.getOffsetForPosition(x, y))
        when {
            range == null -> selectWord(text, null)
            range != selection -> selectWord(text, range)
            else -> renewWord(text, range)
        }
    }

    private fun selectWord(text: String, range: IntRange?) {
        selection = range
        showSuggestionText(text, range?.first ?: -1, (range?.last ?: -2) + 1)
        resetHint()
        if (range != null && Api.autoSpeak(this)) speak(text.substring(range.first, range.last + 1))
    }

    private fun renewWord(text: String, range: IntRange) {
        val before = text.substring(0, range.first)
        val word = text.substring(range.first, range.last + 1)
        val after = text.substring(range.last + 1)

        // Andere Stelle: Kandidaten und abgelehnte Wörter beginnen von vorn.
        if (before != candidateKey) {
            resetRewordState()
            candidateKey = before
        }
        if (rejected.none { it.equals(word, ignoreCase = true) }) rejected.add(word)

        // Noch Kandidaten übrig: sofort das nächste einsetzen, ohne neue Anfrage.
        if (candidateIndex < candidates.size) {
            replaceWord(before, candidates[candidateIndex++], after)
            return
        }

        val source = sourceText ?: return
        val id = requestId
        val rejectedNow = rejected.toList()
        rewordBusy = true
        showBusy("Suche ein anderes Wort …")
        executor.execute {
            val result = try {
                Api.reword(this, source, before, word, after, rejectedNow)
            } catch (e: Exception) {
                null
            }
            main.post {
                if (id != requestId || suggestion != text) return@post // Vorschlag wurde inzwischen ersetzt
                rewordBusy = false
                when {
                    result == null -> showHint("Keine Verbindung zum Server.")
                    result.isEmpty() -> showHint("Kein anderes Wort gefunden.")
                    else -> {
                        candidates = result
                        candidateIndex = 0
                        replaceWord(before, candidates[candidateIndex++], after)
                    }
                }
            }
        }
    }

    private fun replaceWord(before: String, newWord: String, after: String) {
        val updated = before + newWord + after
        suggestion = updated
        selection = before.length until before.length + newWord.length
        showSuggestionText(updated, before.length, before.length + newWord.length)
        resetHint()
        suggestionView.post { // markiertes Wort in den sichtbaren Bereich holen
            val layout = suggestionView.layout ?: return@post
            val line = layout.getLineForOffset(before.length)
            val maxY = (layout.height + suggestionView.totalPaddingTop + suggestionView.totalPaddingBottom -
                suggestionView.height).coerceAtLeast(0)
            suggestionView.scrollTo(0, layout.getLineTop((line - 1).coerceAtLeast(0)).coerceAtMost(maxY))
        }
        // Ab dem Satz mit dem neuen Wort bis zum Ende weiterlesen
        if (Api.autoSpeak(this)) speak(fromSentenceStart(updated, before.length))
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
        private const val HINT_SELECT = "Falsches Wort? Antippen zum Markieren."
        private const val HINT_RENEW = "Gelbes Wort nochmal antippen: anderes Wort."
        private const val KEY_HEIGHT_DP = 58
    }
}


/** Kleiner, selbst gezeichneter Drehkreis. Bewusst ohne System-Fortschrittsanzeige (Design-Abhängigkeit). */
private class Spinner(context: Context, accent: Int) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = accent
    }
    private val box = RectF()
    private var angle = 0f
    private val animator = ValueAnimator.ofFloat(0f, 360f).apply {
        duration = 900
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
            angle = it.animatedValue as Float
            invalidate()
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (visibility == VISIBLE) animator.start()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        if (visibility == VISIBLE && isAttachedToWindow) animator.start() else animator.cancel()
    }

    override fun onDraw(canvas: Canvas) {
        val stroke = width / 7f
        paint.strokeWidth = stroke
        box.set(stroke, stroke, width - stroke, height - stroke)
        canvas.drawArc(box, angle, 270f, false, paint)
    }
}
