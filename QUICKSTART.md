# Quickstart: Henri Tastatur zu Hause testen

Die Tastatur auf dem Handy schickt den Text an einen kleinen Proxy auf dem Mac,
der ihn an das Sprachmodell in Ollama weitergibt. Alle drei müssen laufen.

```
Handy (Tastatur)  --WLAN-->  Proxy (Mac, Port 8787)  -->  Ollama (Mac)
```

## Am einfachsten: Steuerungsseite (ein Klick)

Doppelklick auf **`Start-Henri.command`** (Mac) bzw. **`Start-Henri.bat`** (Windows).
Es öffnet sich eine Seite im Browser:

- **Starten** prüft und startet Ollama, lädt bei Bedarf das Sprachmodell (einmalig, mit
  Fortschrittsbalken) und startet den Server.
- Die **Statusanzeige** zeigt grün/rot, ob alles läuft, und wann das Handy zuletzt benutzt wurde.
- Die **Adresse fürs Handy** steht groß da (mit Knopf zum Kopieren).
- **Beenden** stoppt den Server. **Programm ganz beenden** schließt alles.

Voraussetzung: Python 3 und Ollama sind installiert. Ein von Hand gestarteter Server (siehe unten)
wird erkannt und kann parallel weiterlaufen.

Auf Windows fragt die Firewall beim ersten Start "Zugriff zulassen?". Das muss mit **Zulassen**
bestätigt werden (für private Netzwerke), sonst erreicht das Handy den Server nicht.

## Manuell (ohne Steuerungsseite)

Die Schritte weiter unten funktionieren unverändert und ersetzen die Steuerungsseite.

## Voraussetzungen

- Mac und Handy sind im **selben WLAN** (kein Gast-WLAN, kein VPN).
- Der Mac ist **wach** (nicht im Ruhezustand).
- Ollama ist installiert und das Modell ist geladen: `ollama pull gemma3:4b`

## 1. Ollama prüfen

```sh
ollama list
```

In der Liste muss `gemma3:4b` stehen. Falls Ollama nicht antwortet, die Ollama-App starten.

## 2. Proxy starten

```sh
cd ~/VSCodeProjects/henri/proxy
LLM_MODEL=gemma3:4b python3 server.py
```

Das Terminal-Fenster bleibt offen, solange der Proxy läuft. Beenden mit `Strg+C`.

## 3. IP-Adresse des Macs herausfinden

```sh
ipconfig getifaddr en0
```

Die Ausgabe (z. B. `192.168.1.23`) ist die Adresse für das Handy. Sie kann sich nach einem
Neustart des Macs oder des Routers ändern.

## 4. Verbindung vom Handy prüfen

Im Handy-Browser öffnen (mit `http://`, nicht `https://`):

```
http://<IP-DES-MACS>:8787/health
```

Es muss `{"ok": true, "model": "gemma3:4b"}` erscheinen.

## 5. App einrichten (einmalig)

1. App **Henri Tastatur** öffnen.
2. **Tastatur aktivieren** und in den Android-Einstellungen einschalten.
3. **Tastatur auswählen**.
4. Die Adresse eintragen: `http://<IP-DES-MACS>:8787`
5. **Speichern und Verbindung testen**. Es muss "Verbunden, Modell: gemma3:4b" erscheinen.

## 6. Benutzen

1. In einer App (z. B. WhatsApp) ins Nachrichtenfeld tippen, die Henri Tastatur ist aktiv.
2. Schreiben, auch mit Fehlern.
3. **Verbessern** drücken. Der Vorschlag erscheint groß und wird vorgelesen.
4. **Übernehmen** ersetzt den Text im Feld. **Vorlesen** liest ihn noch einmal vor.
5. Gesendet wird nie automatisch. Das machst du selbst in der App.

## Bessere Wortvorschläge (optional)

Tippt man im Vorschlag ein Wort an (gelb) und noch einmal, schlägt der Server ein anderes Wort vor.
Das kleine Modell `gemma3:4b` trifft das nur mäßig. Ein zweites, größeres Modell nur dafür hilft:

```sh
HENRI_REWORD_MODEL=qwen2.5:7b ./Start-Henri.command     # Mac
```

Beim ersten Start wird es geladen (ca. 4,7 GB). Zwei Modelle brauchen mehr Arbeitsspeicher.
Von Hand: `LLM_MODEL=gemma3:4b LLM_REWORD_MODEL=qwen2.5:7b python3 server.py`.

## Anderen Anbieter nutzen, z. B. wenn der Rechner zu langsam ist (optional)

Standard ist **Lokal (Ollama)**. Auf der Steuerungsseite gibt es den zugeklappten Bereich
**Anbieter für das Sprachmodell**. Dort lässt sich stattdessen ein Cloud-Dienst wählen
(Groq, Mistral, Google Gemini, OpenRouter oder ein eigener mit OpenAI-Schnittstelle):

1. Beim Anbieter ein Konto anlegen und einen **Schlüssel (API-Key)** erstellen. Der Link dazu steht im Bereich.
2. Anbieter wählen, Schlüssel einfügen, bei Bedarf das Modell ändern. Die Modellnamen ändern sich bei den
   Anbietern öfter, bei Fehlern dort den aktuellen Namen nachsehen.
3. **Testen** prüft Schlüssel und Modell und sagt auf Deutsch, was nicht stimmt.
4. **Speichern und übernehmen**. Läuft der Server, startet er damit neu.

Das Handy bleibt unverändert, es zeigt nur den Modellnamen mit dem Zusatz "(Cloud)". Der Schlüssel liegt nur
in `proxy/henri-config.json` auf diesem Rechner (nicht im Git, nur für den Benutzer lesbar).

**Datenschutz:** Bei Cloud-Anbietern verlassen die Texte den Rechner. Kostenlose Stufen dürfen Eingaben teils
zur Verbesserung nutzen. Für echte Nachrichten ein bezahltes Konto mit Standort in der EU wählen.
Zurück zu lokal: im Bereich wieder **Lokal (Ollama)** wählen und speichern.

## Wenn etwas nicht klappt

| Problem | Ursache und Lösung |
|---|---|
| "Keine Verbindung zum Server" | Proxy läuft nicht (Schritt 2), Handy nicht im WLAN oder die IP hat sich geändert (Schritt 3 und 5). |
| `/health` lädt im Handy-Browser nicht | Mit `http://` eintippen. Prüfen, dass Handy und Mac im selben WLAN sind. Mac-Firewall: Python muss eingehende Verbindungen erlauben. |
| Verbessern dauert sehr lange | Beim ersten Aufruf lädt Ollama das Modell, das kann einige Sekunden dauern. Danach etwa 2 Sekunden. |
| Falsche oder zu freie Korrektur | Den Prompt in `proxy/prompt.txt` anpassen und den Proxy neu starten. Mit `python3 eval.py gemma3:4b` lassen sich Änderungen gegen die Testfälle in `proxy/cases.json` prüfen. |
| App lässt sich nicht installieren ("Problem beim Parsen") | Zu wenig freier Speicher auf dem Handy. Mindestens etwa 1 GB freiräumen. |

## App neu bauen und auf dem Handy aktualisieren

```sh
cd ~/VSCodeProjects/henri/keyboard
./gradlew assembleDebug
```

Die APK liegt unter `app/build/outputs/apk/debug/app-debug.apk`. Sie lässt sich per Dateiübertragung
oder mit `adb install -r app-debug.apk` installieren. Eine neue Version aktualisiert die App und
behält die Einstellungen.

## Hinweise

- Der Proxy hat in dieser Entwicklungsversion **keinen Zugriffsschutz** und ist für jeden im
  selben WLAN erreichbar. Nur in vertrauenswürdigen Netzen laufen lassen oder mit
  `APP_TOKEN=<geheimer Wert>` starten und denselben Wert in der App eintragen.
- Es werden keine Nachrichteninhalte vom Proxy gespeichert oder geloggt.
