@echo off
rem Windows-Gegenstueck zu steamOs/steamos-game-scanner.timer (OnBootSec=1min,
rem OnUnitActiveSec=30min): scannt die installierten Steam-Spiele einmal sofort
rem und danach alle 30 Minuten erneut, damit neu installierte/entfernte Spiele
rem automatisch in games.db erfasst werden. Wird ueblicherweise nicht direkt
rem doppelgeklickt, sondern per install_autostart.bat unsichtbar im Hintergrund
rem gestartet (siehe dort).
title SteamOsPogram-GameScanner
setlocal
set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\game_scanner.log"

:loop
echo ---- %date% %time% - Scanne Steam-Bibliothek ---- >> "%LOG_FILE%"
python "%SCRIPT_DIR%game_scanner.py" >> "%LOG_FILE%" 2>&1
echo ---- %date% %time% - Naechster Scan in 30 Minuten ---- >> "%LOG_FILE%"
ping -n 1801 127.0.0.1 >nul
goto loop
