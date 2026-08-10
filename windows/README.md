# windows

Windows-Version des SteamOS-seitigen Programms - **nur zum lokalen
Testen/Entwickeln** auf einem Windows-PC, ohne Steam Deck/SteamOS oder
Pico-Hardware zu benoetigen. Fuer die tatsaechliche Steam-Deck-Installation
gilt weiterhin [`steamOs/`](../steamOs) (siehe dortige README).

Dieser Ordner enthaelt bewusst **keine eigene Logik**, sondern nur duenne
Windows-Einstiegspunkte, die den echten, gemeinsam genutzten Code aus
`steamOs/` importieren und ausfuehren:

| Datei | Ruft auf | Windows-spezifisch daran |
|---|---|---|
| `game_scanner.py` | `steamOs/game_scanner.py` | Findet Steam ueber die Windows-Registry (`HKCU\Software\Valve\Steam`) statt der Linux-Pfade |
| `pico_client.py` | `steamOs/pico_client.py` | Nichts extra - der Code dort loest `steam.exe` bereits selbst ueber die Registry auf (`SteamExe`-Wert), da `steam` unter Windows i. d. R. nicht im PATH steht |
| `gui_server.py` | `steamOs/gui/gui_server.py` | Nichts - reiner Python-Standardbibliothek-Code, laeuft unveraendert |

Konfiguration (`config.json`), die Spieledatenbank (`games.db`) und die
Netzwerklogik (`pico_link.py`) liegen weiterhin **ausschliesslich** in
`steamOs/` - die Wrapper hier lesen/schreiben dieselben Dateien, es gibt
keine separate Windows-Konfiguration.

## Verwendung

Voraussetzung: Ein Pico im selben Netzwerk, erreichbar unter einer
bekannten IP (siehe [Pico/README.md](../Pico/README.md)). UDP-Broadcast-
Discovery funktioniert auf manchen Windows-Netzwerken/Firewalls nicht
zuverlaessig - in dem Fall in `steamOs/config.json` die IP des Pico fest
eintragen (`pico_ip`).

```powershell
# 1. Installierte Steam-Spiele einlesen (schreibt nach steamOs/games.db)
python windows\game_scanner.py

# 2. Hintergrund-Monitor starten (Erreichbarkeits-Check + automatischer
#    Spielstart bei erkanntem RFID-Tag)
python windows\pico_client.py

# 3. In einem zweiten Terminal: Spielauswahl-/Tag-Verwaltungs-GUI starten
python windows\gui_server.py
# Danach im Browser: http://127.0.0.1:8080/
```

## Bekannte Windows-Eigenheiten

- **UDP-Broadcast-Discovery** (`DISCOVER_PICO`) findet den Pico auf
  manchen Windows-Rechnern/Netzwerkprofilen nicht zuverlaessig, obwohl der
  Pico direkt per IP einwandfrei erreichbar ist. Abhilfe: `pico_ip` in
  `steamOs/config.json` fest eintragen (umgeht die Suche komplett).
- **`steam` ist unter Windows meist nicht im PATH** (anders als auf
  SteamOS). `steamOs/pico_client.py` loest deshalb beim Start automatisch
  den echten Pfad zu `steam.exe` ueber die Registry auf
  (`HKCU\Software\Valve\Steam\SteamExe`) und ersetzt damit das `steam` im
  gespeicherten `launch_command`, bevor das Spiel gestartet wird.
- Manche IDEs/Linter (z. B. Pylance) markieren die
  `sys.platform != "win32"`-Pruefungen im Code als "immer falsch" -
  das ist auf einem Windows-Entwicklungsrechner erwartet und kein Fehler;
  auf SteamOS/Linux ist der Zweig aktiv.
