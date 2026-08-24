@echo off
rem Windows-Gegenstueck zu build_zip.sh: installiert bei Bedarf zuerst Node.js
rem (ueber winget) und pnpm (ueber corepack, kommt mit Node.js), baut danach
rem das Frontend (pnpm install / pnpm run build) und packt alles zu derselben
rem release\<Name>-<Version>.zip wie die .sh-Variante - nur zum lokalen
rem Bauen/Testen auf einem Windows-PC gedacht, installiert wird das Plugin
rem trotzdem nur auf dem Steam Deck (siehe README.md, Abschnitt "Installieren").
setlocal
rem Verhindert, dass corepack bei der ersten Nutzung interaktiv nach einer
rem Bestaetigung fragt (wuerde in einem doppelt geklickten Fenster ohne
rem Tastatureingabe haengen bleiben).
set "COREPACK_ENABLE_DOWNLOAD_PROMPT=0"

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw 'plugin.json' | ConvertFrom-Json).name -replace ' ', '-'"`) do set "PLUGIN_NAME=%%A"
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw 'package.json' | ConvertFrom-Json).version"`) do set "VERSION=%%A"

if "%PLUGIN_NAME%"=="" (
    echo Fehler: Konnte "name" nicht aus plugin.json lesen.
    goto :fail
)
if "%VERSION%"=="" (
    echo Fehler: Konnte "version" nicht aus package.json lesen.
    goto :fail
)

if exist "dist\index.js" goto :stage

echo dist\index.js fehlt - baue Frontend zuerst...

where node >nul 2>nul
if errorlevel 1 (
    echo Node.js nicht gefunden - installiere ueber winget ...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo Fehler: winget nicht gefunden. Bitte Node.js ^(^>=18^) manuell von
        echo https://nodejs.org/ installieren und dieses Skript erneut ausfuehren.
        goto :fail
    )
    winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo Fehler: Node.js-Installation ueber winget fehlgeschlagen.
        goto :fail
    )
    rem winget aktualisiert den PATH erst in einer neuen Konsole - fuer diesen
    rem Lauf hier provisorisch ergaenzen, damit direkt weitergebaut werden kann.
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
    where node >nul 2>nul
    if errorlevel 1 (
        echo Node.js wurde installiert, ist in diesem Fenster aber noch nicht im PATH.
        echo Bitte dieses Fenster schliessen, ein neues oeffnen und build_zip.bat
        echo erneut ausfuehren.
        goto :fail
    )
)

rem pnpm wird bewusst nicht ueber "corepack enable" global eingerichtet -
rem das legt Shims in "Program Files\nodejs" an und braucht dafuer
rem Administrator-Rechte. "corepack pnpm ..." ruft dieselbe (bei Bedarf
rem automatisch heruntergeladene) pnpm-Version direkt auf, ganz ohne
rem Elevation - siehe COREPACK_ENABLE_DOWNLOAD_PROMPT oben fuer den
rem einmaligen Download im Hintergrund.
set "PNPM=corepack pnpm"
where pnpm >nul 2>nul
if not errorlevel 1 set "PNPM=pnpm"

if not exist "node_modules" (
    call %PNPM% install
    if errorlevel 1 goto :fail
)
call %PNPM% run build
if errorlevel 1 goto :fail

:stage
set "RELEASE_DIR=%SCRIPT_DIR%release"
set "STAGE_DIR=%TEMP%\decky-build-%RANDOM%%RANDOM%"
set "PLUGIN_DIR=%STAGE_DIR%\%PLUGIN_NAME%"

mkdir "%PLUGIN_DIR%" || goto :fail
copy /y "plugin.json" "%PLUGIN_DIR%\" >nul
rem package.json muss mit ins installierte Verzeichnis - Decky Loader
rem (backend/decky_loader/plugin/plugin.py) liest daraus "type": "module" und
rem waehlt nur dann den modernen ESMODULE_V1-Ladepfad (dynamisches import());
rem fehlt package.json oder das Feld, faellt es auf den alten
rem LEGACY_EVAL_IIFE-Pfad zurueck, der unser ESM-gebautes dist/index.js per
rem eval() ausfuehrt und an dessen "export"-Anweisung mit SyntaxError scheitert.
copy /y "package.json" "%PLUGIN_DIR%\" >nul
copy /y "main.py" "%PLUGIN_DIR%\" >nul
xcopy /e /i /q "dist" "%PLUGIN_DIR%\dist" >nul
if exist "README.md" copy /y "README.md" "%PLUGIN_DIR%\" >nul
if exist "LICENSE" copy /y "LICENSE" "%PLUGIN_DIR%\" >nul

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
set "ZIP_PATH=%RELEASE_DIR%\%PLUGIN_NAME%-%VERSION%.zip"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

rem Bewusst tar.exe statt PowerShells Compress-Archive: Compress-Archive
rem speichert Ordnertrennzeichen als Backslash im ZIP-Eintragsnamen ab, was
rem am Zielsystem (Steam Deck, Linux) beim Entpacken keine Unterordner
rem ergibt, sondern Dateien mit woertlichem Backslash im Namen - das
rem installierte "Plugin" landet dann nicht dort, wo Decky Loader es
rem erwartet, und im Quick-Access-Menu passiert scheinbar nichts. tar.exe
rem (in Windows seit 10/1803 fest eingebaut, volle Pfadangabe hier, weil ein
rem evtl. vorhandenes Git-fuer-Windows-tar.exe frueher im PATH kein "-a" mit
rem .zip unterstuetzt) schreibt stattdessen korrekt Forward-Slashes.
"%SystemRoot%\System32\tar.exe" -a -cf "%ZIP_PATH%" -C "%STAGE_DIR%" "%PLUGIN_NAME%"
if errorlevel 1 (
    echo Fehler beim Erstellen der ZIP-Datei.
    rmdir /s /q "%STAGE_DIR%"
    goto :fail
)
rmdir /s /q "%STAGE_DIR%"

echo.
echo Fertig: %ZIP_PATH%
echo Installation ^(auf dem Steam Deck^): im Decky-Loader-Menu -^> Einstellungen
echo -^> "Aus ZIP installieren" auswaehlen, oder manuell nach
echo ~/homebrew/plugins/%PLUGIN_NAME%/ entpacken.
goto :end

:fail
echo.
echo Abgebrochen wegen obigem Fehler.
endlocal
pause
exit /b 1

:end
endlocal
pause
exit /b 0
