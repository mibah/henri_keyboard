@echo off
rem Doppelklick unter Windows: startet den Henri Windows-Helfer im Browser.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 helfer.py & goto :fertig)
where python >nul 2>nul && (python helfer.py & goto :fertig)
echo Python 3 fehlt. Bitte von python.org installieren und dabei "Add Python to PATH" anhaken.
pause
exit /b 1
:fertig
rem Normal beendet: Fenster schliessen. Bei einem Fehler bleibt es offen, damit man die Meldung lesen kann.
if errorlevel 1 pause
exit
