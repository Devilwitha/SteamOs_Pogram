@echo off
rem Windows-Gegenstueck zu steamOs/install.sh: richtet Pico-Monitor und
rem Spiele-Scanner als Autostart ein, der bei jeder Anmeldung automatisch
rem und unsichtbar (kein Konsolenfenster) im Hintergrund startet - analog
rem zum systemd --user Dienst + Timer auf SteamOS. Legt dazu zwei kleine
rem .vbs-Starter im Windows-Autostart-Ordner ab, die ihrerseits
rem pico_monitor_loop.bat bzw. game_scanner_loop.bat unsichtbar aufrufen
rem (ein direkt im Autostart-Ordner abgelegtes .bat wuerde ein sichtbares
rem Konsolenfenster oeffnen).
setlocal
set "SCRIPT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if not exist "%STARTUP_DIR%" (
    echo Autostart-Ordner nicht gefunden: "%STARTUP_DIR%"
    exit /b 1
)

echo Richte Autostart in "%STARTUP_DIR%" ein ...
echo CreateObject("WScript.Shell").Run """%SCRIPT_DIR%pico_monitor_loop.bat""", 0, False> "%STARTUP_DIR%\SteamOsPogram-PicoMonitor.vbs"
echo CreateObject("WScript.Shell").Run """%SCRIPT_DIR%game_scanner_loop.bat""", 0, False> "%STARTUP_DIR%\SteamOsPogram-GameScanner.vbs"

echo Autostart eingerichtet - ab der naechsten Anmeldung starten Pico-Monitor
echo und Spiele-Scanner automatisch und unsichtbar im Hintergrund.
echo.
echo Starte beide jetzt sofort (wie 'systemctl --user enable --now')...
wscript.exe "%STARTUP_DIR%\SteamOsPogram-PicoMonitor.vbs"
wscript.exe "%STARTUP_DIR%\SteamOsPogram-GameScanner.vbs"

echo.
echo Fertig. Logs liegen in "%SCRIPT_DIR%logs\".
echo Deinstallieren mit uninstall_autostart.bat.
pause
