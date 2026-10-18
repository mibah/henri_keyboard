#!/bin/bash
# Doppelklick am Mac: startet die Henri-Steuerung im Browser.
cd "$(dirname "$0")/proxy" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 fehlt. Bitte von python.org installieren."
  read -r -p "Eine Taste drücken zum Schließen …" -n 1
  exit 1
fi
python3 launcher.py
