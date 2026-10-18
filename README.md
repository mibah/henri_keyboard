# Henri Tastatur

Eine Android-Tastatur für Menschen, die schlecht sehen und beim Tippen viele Fehler machen.
Ein Sprachmodell korrigiert die Nachricht, die Tastatur liest das Ergebnis vor, und der Nutzer
sendet selbst. Sie funktioniert in jeder App (WhatsApp, Signal, SMS, E-Mail), ohne Zugriff
auf die Messenger selbst.

## Ablauf

1. Nutzer tippt (oder diktiert) mit der Henri Tastatur.
2. **Verbessern**: Der Text geht an den Proxy, das Modell korrigiert Rechtschreibung und Zeichensetzung.
3. Der Vorschlag erscheint groß und wird **vorgelesen** (Android-TTS).
4. Falsches Wort im Vorschlag? Antippen markiert es gelb, nochmal antippen holt ein anderes
   (Kandidaten vom Server, `/reword`). Danach wird ab diesem Satz weitergelesen.
5. **Übernehmen** ersetzt den Feldtext. Gesendet wird nie automatisch.

In Passwortfeldern sind die KI-Funktionen ausgeblendet.

## Aufbau

| Ordner | Inhalt |
|---|---|
| `keyboard/` | Android-App (Kotlin, ohne Fremdbibliotheken): Tastatur und Einrichtungs-Activity |
| `proxy/` | Dünner HTTP-Proxy (Python, nur Standardbibliothek) vor einer OpenAI-kompatiblen LLM-API |

Der API-Key und der Prompt liegen nur im Proxy, nie auf dem Handy.

## Schnellstart mit Steuerungsseite

Doppelklick auf `Start-Henri.command` (Mac) oder `Start-Henri.bat` (Windows) öffnet eine Seite
mit Start/Beenden-Knopf und Statusanzeige. Details in [QUICKSTART.md](QUICKSTART.md).

## Proxy von Hand starten

```sh
cd proxy
LLM_MODEL=gemma3:4b python3 server.py          # gegen lokales Ollama
python3 eval.py gemma3:4b qwen2.5:7b           # Modelle mit cases.json vergleichen
```

Umgebungsvariablen: `LLM_BASE_URL` (Standard `http://localhost:11434/v1`), `LLM_MODEL`,
`LLM_API_KEY`, `APP_TOKEN` (optional, erwartet `Authorization: Bearer <token>`), `PORT` (8787).
Der Proxy loggt keine Nachrichteninhalte.

## App bauen

Voraussetzungen: JDK 17+, Android SDK (Plattform 35).

```sh
cd keyboard
./gradlew assembleDebug
```

Die APK liegt dann unter `keyboard/app/build/outputs/apk/debug/`. In der App die Proxy-Adresse
eintragen (z. B. `http://<IP des Rechners>:8787`).

## Stand und Einschränkungen

- Entwicklungsstand: Die App erlaubt unverschlüsseltes HTTP (`usesCleartextTraffic`) und wird als
  Debug-Build gebaut. Für den echten Einsatz HTTPS verwenden und das entfernen.
- Der Proxy hat nur ein einfaches Rate-Limit pro IP, kein Benutzerkonto.
- Noch offen: Vorlesen eingehender Nachrichten (Benachrichtigungen/Bedienungshilfe), Spracheingabe.

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE).
