@echo off
rem Doppelklick unter Windows: startet die Henri-Steuerung im Browser.
cd /d "%~dp0proxy"
where py >nul 2>nul && (py -3 launcher.py & goto :fertig)
where python >nul 2>nul && (python launcher.py & goto :fertig)
echo Python 3 fehlt. Bitte von python.org installieren und dabei "Add Python to PATH" anhaken.
pause
exit /b 1
:fertig
rem Normal beendet: Fenster schliessen. Bei einem Fehler bleibt es offen, damit man die Meldung lesen kann.
if errorlevel 1 pause
exit
