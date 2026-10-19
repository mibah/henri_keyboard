#!/bin/bash
# Doppelklick am Mac: startet die Henri-Steuerung im Browser.
cd "$(dirname "$0")/proxy" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 fehlt. Bitte von python.org installieren."
  read -r -p "Eine Taste drücken zum Schließen …" -n 1
  exit 1
fi

TITLE="Henri-Steuerung"
printf '\033]0;%s\007' "$TITLE" # Fenstertitel, daran erkennen wir das Fenster später

python3 launcher.py
STATUS=$?

# Normal beendet ("Programm ganz beenden" oder Strg+C): dieses Terminal-Fenster mit schließen.
# Das Skript endet sofort; ein kurz verzögerter Hintergrundbefehl schließt das Fenster, damit
# Terminal nicht nach noch laufenden Prozessen fragt. Bei einem Fehler bleibt das Fenster offen.
if [ "$STATUS" -eq 0 ]; then
  (
    sleep 1
    osascript >/dev/null 2>&1 <<OSA
tell application "Terminal"
  repeat with w in windows
    if name of w contains "$TITLE" then close w
  end repeat
end tell
OSA
  ) &
  disown
fi
exit "$STATUS"
