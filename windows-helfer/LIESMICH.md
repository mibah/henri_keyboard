# Henri Windows-Helfer

Ein eigenständiges Hilfsprogramm für Windows. Es verändert weder die Henri-Tastatur noch den Server noch die Steuerung.
Es hilft, wenn das Handy den Rechner nicht erreicht („Server nicht erreichbar“).

## Benutzen

1. Python 3 muss installiert sein (wie für Henri selbst).
2. `Henri-Helfer.bat` doppelt anklicken. Im Browser öffnet sich die Seite.
3. Auf **Alles prüfen** klicken. Der Helfer **ändert nichts** am Rechner. Er zeigt die Ursache und Lösungsvorschläge
   mit Befehlen zum Kopieren, die man selbst ausführt.
4. Am Handy im Browser die angezeigte Adresse (`http://…:8788`) öffnen. Meldet sich das Handy, steht es auf der Seite.
5. **Bericht erstellen** und den Bericht (oder den Ordner `protokoll`) weitergeben, falls es nicht klappt.

## Was geprüft wird

Henri-Server, Ollama und Modell, Netzwerkadressen (auch virtuelle), ob der Server auf allen Adressen lauscht,
ob sich der Rechner selbst über das Netz erreicht, Firewall (an/aus, Regel für Port 8787, Sperrregeln für Python/Ollama),
Firewall-Richtlinien (Firma/Schule, die lokale Regeln aushebeln), Sicherheitsprogramme anderer Hersteller,
Internetzugang (für einen Notfall-Tunnel). Trägt man die **IP des Handys** ein, prüft der Helfer außerdem, ob der Rechner
das Handy im Netz sieht (Ping und ARP): so lässt sich ein Router-Problem (Gastnetz, Geräte-Trennung) vom Firewall-Problem
unterscheiden. Dazu sammelt er Netzwerkdaten (ipconfig, Routen, Proxy, laufende Schutzprogramme) für den Bericht.

## Was geändert wird

Nichts. Der Helfer liest nur (PowerShell-Abfragen, Ping, ARP) und hört auf Port 8788 mit. Er legt keine Regeln an, schaltet nichts
ein oder aus und verlangt keine Administrator-Rechte. Lösungen stehen als Text und als Befehl zum Kopieren da.

## Protokoll

Jeder Befehl mit Ausgabe, jede Prüfung und jede Änderung steht in `protokoll/` (neben diesem Programm,
sonst im Temp-Ordner). Berichte enthalten keinen Benutzer- und keinen Rechnernamen. Schlüssel liest das Programm nicht.
