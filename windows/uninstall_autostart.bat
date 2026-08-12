@echo off
rem Windows-Gegenstueck zu steamOs/uninstall.sh: entfernt die Autostart-Eintraege
rem wieder und beendet bereits laufende Hintergrundprozesse sofort (statt erst
rem bei der naechsten Abmeldung) - Erkennung ueber den in pico_monitor_loop.bat
rem bzw. game_scanner_loop.bat per 'title' gesetzten Fenstertitel (auch bei
rem unsichtbarem Fenster vorhanden, siehe install_autostart.bat).
setlocal
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Stoppe laufende Hintergrundprozesse ...
taskkill /F /T /FI "WINDOWTITLE eq SteamOsPogram-PicoMonitor" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq SteamOsPogram-GameScanner" >nul 2>&1

echo Entferne Autostart-Eintraege ...
del /f /q "%STARTUP_DIR%\SteamOsPogram-PicoMonitor.vbs" >nul 2>&1
del /f /q "%STARTUP_DIR%\SteamOsPogram-GameScanner.vbs" >nul 2>&1

echo Fertig. Autostart deaktiviert und laufende Prozesse beendet.
pause
