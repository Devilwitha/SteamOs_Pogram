@echo off
rem Windows-Gegenstueck zu steamOs/steamos-pico-monitor.service (Restart=always,
rem RestartSec=5): startet pico_client.py und startet es automatisch neu, falls
rem es sich beendet (Absturz, Netzwerkfehler, ...) - laeuft dadurch dauerhaft,
rem genau wie der systemd-Dienst auf SteamOS. Wird ueblicherweise nicht direkt
rem doppelgeklickt, sondern per install_autostart.bat unsichtbar im Hintergrund
rem gestartet (siehe dort).
title SteamOsPogram-PicoMonitor
setlocal
set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\pico_monitor.log"

:loop
echo ---- %date% %time% - Starte pico_client.py ---- >> "%LOG_FILE%"
python "%SCRIPT_DIR%pico_client.py" >> "%LOG_FILE%" 2>&1
echo ---- %date% %time% - pico_client.py beendet, Neustart in 5s ---- >> "%LOG_FILE%"
ping -n 6 127.0.0.1 >nul
goto loop
