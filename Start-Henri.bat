@echo off
rem Doppelklick unter Windows: startet die Henri-Steuerung im Browser.
cd /d "%~dp0proxy"
where py >nul 2>nul && (py -3 launcher.py & goto :ende)
where python >nul 2>nul && (python launcher.py & goto :ende)
echo Python 3 fehlt. Bitte von python.org installieren und dabei "Add Python to PATH" anhaken.
:ende
pause
