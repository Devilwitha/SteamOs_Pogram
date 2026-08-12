# SteamOs_Pogram

Programme, die bis zu zwei Raspberry Pi Pico W ueberwachen und steuern -
und zwar auch dann, wenn das Steam Deck im Game Mode laeuft: einen mit
RFID-Leser (RC522) zur Spielerkennung, und optional einen zweiten mit
LED-Streifen, der das erkannte Spiel/den Tag farblich anzeigt.

- **[steamOs/](steamOs)** - laeuft als Hintergrunddienst (systemd --user) auf
  SteamOS. Sendet alle 3 Sekunden eine Anfrage an den Pico, liest die
  installierten Steam-Spiele in eine SQLite-Datenbank ein, bietet in
  [`steamOs/gui/`](steamOs/gui) eine Weboberflaeche zur Spielauswahl,
  zur Verwaltung der vom Pico bekannten RFID-Tags sowie zur Zuweisung
  einer Farbe pro Spiel/Tag, startet automatisch das Spiel, dessen Tag am
  Pico erkannt wird, und reicht die passende Farbe an den optionalen
  Led_Pico weiter.
- **[Pico/](Pico)** - MicroPython-Programm fuer einen Raspberry Pi Pico W.
  Verbindet sich mit dem gespeicherten WLAN (bis zu 3 Versuche); klappt das
  nicht, oeffnet der Pico einen eigenen Access Point mit einer Webseite zur
  WLAN-Einrichtung. Hostet im Normalbetrieb zusaetzlich eine dunkle,
  moderne Statuswebseite und steuert einen RC522-RFID-Leser: liest laufend
  aufliegende Tags, speichert jeden neu erkannten Tag und verknuepft ihn -
  in beide Richtungen - mit einer Spiel-UID sowie optional einer eigenen
  Farbe.
- **[Led_Pico/](Led_Pico)** - MicroPython-Programm fuer einen **zweiten,
  eigenstaendigen** Raspberry Pi Pico W mit WS2812/NeoPixel-LED-Streifen.
  Optional: laeuft unabhaengig vom RFID-Pico und zeigt per LED-Streifen
  die Farbe des aktuell erkannten Spiels bzw. Tags an.
- **[windows/](windows)** - duenne Windows-Einstiegspunkte fuer denselben
  `steamOs/`-Code, nur zum lokalen Testen/Entwickeln auf einem
  Windows-PC ohne Steam Deck oder Pico-Hardware (siehe dortige README).

## Einrichtungsreihenfolge

1. **Pico vorbereiten:** Siehe [Pico/README.md](Pico/README.md). Firmware
   flashen, RC522 verkabeln, Skripte kopieren, ueber den
   `Pico-Setup`-Access-Point das Heim-WLAN eintragen.
2. **SteamOS-Dienste installieren:** Siehe [steamOs/README.md](steamOs/README.md).
   `./install.sh` im Ordner `steamOs/` ausfuehren (Erreichbarkeits-Monitor +
   Spielstart-Trigger + periodischer Spiele-Scan).
3. **Spiel mit einem Tag verknuepfen:** `python3 steamOs/gui/gui_server.py`
   starten, entweder ein Spiel auswaehlen und danach einen Tag an den RC522
   halten, oder einen bereits erkannten Tag direkt aus der Tag-Liste einem
   Spiel zuweisen. In derselben GUI laesst sich optional auch eine Farbe
   pro Spiel/Tag zuweisen (fuer Schritt 6).
4. **Spiel starten:** Tag an den RC522 halten - SteamOS startet automatisch
   das zugehoerige Spiel.
5. Beide Geraete muessen sich im selben lokalen Netzwerk befinden. Die
   Pico-IP wird von SteamOS automatisch per UDP-Broadcast gefunden - eine
   manuelle Eintragung in `steamOs/config.json` ist nur noetig, falls
   Broadcasts im Netzwerk blockiert sind.
6. **(Optional) Led_Pico vorbereiten:** Siehe [Led_Pico/README.md](Led_Pico/README.md).
   Ein zweiter, eigener Pico W mit LED-Streifen; Einrichtung analog zu
   Schritt 1 (eigener Access Point `LedPico-Setup`). Zeigt danach
   automatisch die in Schritt 3 zugewiesene Farbe des erkannten Spiels/
   Tags an - `steamOs/led_config.json` funktioniert wie `config.json`.
7. Statusseite des Pico im Browser: `http://<pico-ip>/` (nur im normalen
   WLAN-Betrieb erreichbar).

## Protokoll zwischen SteamOS und Pico

| Richtung | Port | Nachricht | Zweck |
|---|---|---|---|
| SteamOS -> Pico | UDP 5006 | `DISCOVER_PICO` | Pico im Netzwerk finden |
| Pico -> SteamOS | UDP 5006 | `PICO:<ip>` | Antwort mit eigener IP |
| SteamOS -> Pico | TCP 5005 | `PING` | Erreichbarkeits-Check (alle 3s) |
| Pico -> SteamOS | TCP 5005 | `erreichbar` | Bestaetigung |
| SteamOS -> Pico | TCP 5005 | `SELECT:<uid>` | Ausgewaehltes Spiel senden (aus der GUI); wird mit dem naechsten aufgelegten Tag verknuepft |
| Pico -> SteamOS | TCP 5005 | `OK:<uid>` | Bestaetigt Empfang der Auswahl |
| SteamOS -> Pico | TCP 5005 | `TAG?` | Fragt, ob ein Tag mit neuer Spiel-UID aufliegt |
| Pico -> SteamOS | TCP 5005 | `TAG:<uid>` / `TAG:NONE` | Erkannte Spiel-UID, oder nichts Neues |
| SteamOS -> Pico | TCP 5005 | `STARTED:<uid>` | Bestaetigt, dass das Spiel gestartet wurde |
| Pico -> SteamOS | TCP 5005 | `OK:STARTED:<uid>` | Bestaetigung; Pico meldet diese UID erst wieder bei Tag-Wechsel/-Entfernung |
| SteamOS -> Pico | TCP 5005 | `TAGS?` | Fragt die Liste aller bekannten Tags ab |
| Pico -> SteamOS | TCP 5005 | `TAGS:<json>` | Liste `[{"uid":..., "game_uid":...}, ...]` |
| SteamOS -> Pico | TCP 5005 | `LINK:<uid>:<spiel-uid>` | Verknuepft einen bekannten Tag direkt mit einem Spiel (leer = trennen) |
| Pico -> SteamOS | TCP 5005 | `OK:LINK:<uid>` / `ERROR:unknown_tag` | Bestaetigung bzw. Fehler |
| SteamOS -> Pico | TCP 5005 | `TAGCOLOR:<uid>:<farbe>` | Setzt (leer = loescht) die eigene Farbe eines bekannten Tags |
| Pico -> SteamOS | TCP 5005 | `OK:TAGCOLOR:<uid>` / `ERROR:unknown_tag` | Bestaetigung bzw. Fehler |
| SteamOS -> Pico | TCP 5005 | `CURRENT?` | Fragt den gerade aufliegenden Tag ab (nicht einmalig wie `TAG?`) |
| Pico -> SteamOS | TCP 5005 | `CURRENT:<json>` / `CURRENT:NONE` | `{"uid":..., "game_uid":..., "game_name":..., "color":..., "status":...}`, oder nichts aufliegend - Grundlage fuer die Led_Pico-Farbe. `status` ist `erkannt`/`gesendet`/`gestartet` (siehe [Pico/README.md](Pico/README.md)) |
| Browser -> Pico | HTTP 80 | `GET /` bzw. `/status.json` | Statuswebseite / -daten (nur im Normalbetrieb) |

## Protokoll zwischen SteamOS und dem optionalen Led_Pico

| Richtung | Port | Nachricht | Zweck |
|---|---|---|---|
| SteamOS -> Led_Pico | UDP 5008 | `DISCOVER_LED_PICO` | Led_Pico im Netzwerk finden |
| Led_Pico -> SteamOS | UDP 5008 | `LEDPICO:<ip>` | Antwort mit eigener IP |
| SteamOS -> Led_Pico | TCP 5007 | `PING` | Erreichbarkeits-Check |
| Led_Pico -> SteamOS | TCP 5007 | `erreichbar` | Bestaetigung |
| SteamOS -> Led_Pico | TCP 5007 | `COLOR:<hex>` | Setzt den LED-Streifen auf diese Farbe |
| Led_Pico -> SteamOS | TCP 5007 | `OK:COLOR:<hex>` / `ERROR:bad_color` | Bestaetigung bzw. Fehler |
| SteamOS -> Led_Pico | TCP 5007 | `OFF` | Schaltet den LED-Streifen aus |
| Led_Pico -> SteamOS | TCP 5007 | `OK:OFF` | Bestaetigung |
