# Tests

Nur Standardbibliothek, kein Ollama und keine Schlüssel nötig (ein Schein-Anbieter ersetzt das Sprachmodell).

```sh
python3 tests/run_tests.py                 # alles ohne Ollama
python3 tests/run_tests.py bestand         # nur der Bestand (vor dem Anbieter-Feature)
python3 tests/run_tests.py neu             # nur Anbieter
python3 tests/run_tests.py --integration   # zusätzlich kompletter Ablauf mit echtem Ollama und gemma3:4b
python3 tests/run_tests.py --build         # zusätzlich die Android-App bauen
```

## Was gehört wozu
| Datei | Prüft |
|---|---|
| `test_bestand_server.py` | Korrektur, Wortvorschläge (gelb), Formulierungen (grün), Token, Begrenzung, Fehler |
| `test_bestand_launcher.py` | Zustände der Steuerung, Schutz der lokalen Seite, Start und Beenden |
| `test_bestand_prompts.py` | **Prompts und Beispiele sind eingefroren** (Prüfsummen) |
| `test_bestand_startdateien.py` | `Start-Henri.command` / `.bat` |
| `test_bestand_android.py` | Standard-Aussehen, Hinweistexte, Schnittstellen, Manifest, Schutz vor dem Scrollbalken-Absturz |
| `test_bestand_integration.py` | voller Ablauf mit echtem Ollama (nur mit `--integration`) |
| `test_neu_anbieter.py` | Anbieter-Modul, Einbindung, Oberfläche |

**Bestand** heißt: Das hat vor dem Anbieter-Feature funktioniert und muss weiter funktionieren. Die Dateien
`test_bestand_*` laufen gegen jeden Stand, auch gegen einen älteren:

```sh
git archive <commit> | tar -x -C /tmp/alt
HENRI_ROOT=/tmp/alt python3 tests/run_tests.py bestand
```

## Prompts bewusst ändern
Ändert sich `prompt*.txt` oder eine Beispielliste, schlägt `test_bestand_prompts.py` fehl. Ist das gewollt:
`python3 tests/print_prompt_hashes.py` ausführen und die Werte in den Test übernehmen.

## Nicht abgedeckt
Das Aussehen der Oberflächen und das Verhalten auf einem echten Handy lassen sich so nicht prüfen. Die
Android-Tests prüfen den Quelltext, nicht die laufende App. Windows ist nicht getestet.
