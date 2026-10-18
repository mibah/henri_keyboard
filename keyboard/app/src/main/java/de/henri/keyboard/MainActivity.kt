package de.henri.keyboard

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/** Einrichtung: Tastatur aktivieren, Proxy-Adresse eintragen, Verbindung und Tastatur testen. */
class MainActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = dp(16)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }

        fun label(text: String, size: Float = 16f, bold: Boolean = false) = TextView(this).apply {
            this.text = text
            textSize = size
            if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, dp(12), 0, dp(4))
        }

        col.addView(label("Henri Tastatur", 26f, true))
        col.addView(label("1. Tastatur einschalten, dann hier zurückkehren."))
        col.addView(Button(this).apply {
            text = "Tastatur aktivieren"
            setOnClickListener { startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS)) }
        })
        col.addView(label("2. Tastatur auswählen (bzw. im Textfeld auf das Tastatursymbol tippen)."))
        col.addView(Button(this).apply {
            text = "Tastatur auswählen"
            setOnClickListener {
                (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker()
            }
        })

        col.addView(label("3. Adresse des Proxys (Mac im selben WLAN)"))
        val url = EditText(this).apply {
            setText(Api.baseUrl(this@MainActivity))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        col.addView(url)
        col.addView(label("Token (leer lassen, wenn der Proxy keinen verlangt)"))
        val token = EditText(this).apply {
            setText(Api.token(this@MainActivity))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        col.addView(token)
        val speak = CheckBox(this).apply {
            text = "Verbesserten Text automatisch vorlesen"
            isChecked = Api.autoSpeak(this@MainActivity)
        }
        col.addView(speak)

        val result = label("")
        col.addView(Button(this).apply {
            text = "Speichern und Verbindung testen"
            setOnClickListener {
                Api.save(this@MainActivity, url.text.toString(), token.text.toString(), speak.isChecked)
                result.text = "Teste …"
                thread {
                    val msg = try {
                        "Verbunden, Modell: " + Api.health(this@MainActivity)
                    } catch (e: Exception) {
                        "Keine Verbindung (${e.javaClass.simpleName}). Gleiches WLAN? Proxy gestartet?"
                    }
                    runOnUiThread { result.text = msg }
                }
            }
        })
        col.addView(result)

        col.addView(label("4. Hier ausprobieren"))
        col.addView(EditText(this).apply {
            hint = "Tippe hier mit der Henri Tastatur …"
            minLines = 3
            textSize = 20f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        })

        // Android 15 zeichnet Apps hinter Status- und Navigationsleiste: Inhalt darunter schieben.
        setContentView(ScrollView(this).apply {
            addView(col)
            clipToPadding = false
            @Suppress("DEPRECATION")
            setOnApplyWindowInsetsListener { v, insets ->
                v.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
                insets
            }
        })
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}
