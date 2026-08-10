# SteamOs_Pogram

Zwei zusammengehoerige Programme, die einen Raspberry Pi Pico W (mit
RFID-Leser RC522) ueberwachen und steuern - und zwar auch dann, wenn das
Steam Deck im Game Mode laeuft.

- **[steamOs/](steamOs)** - laeuft als Hintergrunddienst (systemd --user) auf
  SteamOS. Sendet alle 3 Sekunden eine Anfrage an den Pico, liest die
  installierten Steam-Spiele in eine SQLite-Datenbank ein, bietet in
  [`steamOs/gui/`](steamOs/gui) eine Weboberflaeche zur Spielauswahl sowie
  zur Verwaltung der vom Pico bekannten RFID-Tags, und startet automatisch
  das Spiel, dessen Tag am Pico erkannt wird.
- **[Pico/](Pico)** - MicroPython-Programm fuer einen Raspberry Pi Pico W.
  Verbindet sich mit dem gespeicherten WLAN (bis zu 3 Versuche); klappt das
  nicht, oeffnet der Pico einen eigenen Access Point mit einer Webseite zur
  WLAN-Einrichtung. Hostet im Normalbetrieb zusaetzlich eine dunkle,
  moderne Statuswebseite und steuert einen RC522-RFID-Leser: liest laufend
  aufliegende Tags, speichert jeden neu erkannten Tag und verknuepft ihn -
  in beide Richtungen - mit einer Spiel-UID.

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
   Spiel zuweisen.
4. **Spiel starten:** Tag an den RC522 halten - SteamOS startet automatisch
   das zugehoerige Spiel.
5. Beide Geraete muessen sich im selben lokalen Netzwerk befinden. Die
   Pico-IP wird von SteamOS automatisch per UDP-Broadcast gefunden - eine
   manuelle Eintragung in `steamOs/config.json` ist nur noetig, falls
   Broadcasts im Netzwerk blockiert sind.
6. Statusseite des Pico im Browser: `http://<pico-ip>/` (nur im normalen
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
| Browser -> Pico | HTTP 80 | `GET /` bzw. `/status.json` | Statuswebseite / -daten (nur im Normalbetrieb) |
