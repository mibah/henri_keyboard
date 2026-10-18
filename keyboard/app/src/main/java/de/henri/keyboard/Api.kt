package de.henri.keyboard

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Einstellungen und Aufrufe des Proxys (POST /correct, GET /health). */
object Api {
    const val DEFAULT_URL = "http://192.168.1.10:8787" // Beispiel: IP des Rechners mit dem Proxy

    private fun prefs(c: Context) = c.getSharedPreferences("henri", Context.MODE_PRIVATE)

    fun baseUrl(c: Context): String {
        val raw = prefs(c).getString("url", DEFAULT_URL).orEmpty().trim().trimEnd('/')
        return if (raw.startsWith("http://") || raw.startsWith("https://")) raw else "http://$raw"
    }

    fun token(c: Context) = prefs(c).getString("token", "").orEmpty().trim()

    fun autoSpeak(c: Context) = prefs(c).getBoolean("autospeak", true)

    fun save(c: Context, url: String, token: String, autoSpeak: Boolean) {
        prefs(c).edit()
            .putString("url", url)
            .putString("token", token)
            .putBoolean("autospeak", autoSpeak)
            .apply()
    }

    /** Blockierend, nur außerhalb des UI-Threads aufrufen. Wirft bei Fehlern. */
    fun correct(c: Context, text: String): String {
        val body = JSONObject().put("text", text).toString().toByteArray()
        val conn = open(c, "/correct", "POST")
        conn.doOutput = true
        conn.outputStream.use { it.write(body) }
        return JSONObject(read(conn)).getString("text")
    }

    /**
     * Bis zu 5 andere Wörter für [word] im Satzzusammenhang (wahrscheinlichstes zuerst).
     * [original] ist der getippte Text, [before]/[after] umgeben das Wort im Vorschlag.
     */
    fun reword(c: Context, original: String, before: String, word: String, after: String, rejected: List<String>): List<String> {
        val body = JSONObject()
            .put("original", original)
            .put("before", before)
            .put("word", word)
            .put("after", after)
            .put("rejected", JSONArray(rejected))
            .toString().toByteArray()
        val conn = open(c, "/reword", "POST")
        conn.doOutput = true
        conn.outputStream.use { it.write(body) }
        val words = JSONObject(read(conn)).getJSONArray("words")
        return List(words.length()) { words.getString(it) }
    }

    fun health(c: Context): String {
        val conn = open(c, "/health", "GET")
        return JSONObject(read(conn)).optString("model", "?")
    }

    private fun open(c: Context, path: String, method: String): HttpURLConnection {
        val conn = URL(baseUrl(c) + path).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 8000
        conn.readTimeout = 60000
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        val token = token(c)
        if (token.isNotEmpty()) conn.setRequestProperty("Authorization", "Bearer $token")
        return conn
    }

    private fun read(conn: HttpURLConnection): String {
        try {
            if (conn.responseCode != 200) throw RuntimeException("HTTP ${conn.responseCode}")
            return conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }
}
