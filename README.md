# SteamOs_Pogram

Zwei zusammengehoerige Programme, die einen Raspberry Pi Pico W ueberwachen
und steuern - und zwar auch dann, wenn das Steam Deck im Game Mode laeuft.

- **[steamOs/](steamOs)** - laeuft als Hintergrunddienst (systemd --user) auf
  SteamOS. Sendet alle 3 Sekunden eine Anfrage an den Pico, liest die
  installierten Steam-Spiele in eine SQLite-Datenbank ein und bietet in
  [`steamOs/gui/`](steamOs/gui) eine Weboberflaeche, um ein Spiel daraus
  auszuwaehlen und dessen UID an den Pico zu senden.
- **[Pico/](Pico)** - MicroPython-Programm fuer einen Raspberry Pi Pico W.
  Verbindet sich mit dem gespeicherten WLAN (bis zu 3 Versuche); klappt das
  nicht, oeffnet der Pico einen eigenen Access Point mit einer Webseite zur
  WLAN-Einrichtung. Beantwortet danach Anfragen von SteamOS: `PING` mit
  `erreichbar`, `SELECT:<uid>` durch Speichern der UID in
  `selected_game.txt` und Bestaetigung mit `OK:<uid>`.

## Einrichtungsreihenfolge

1. **Pico vorbereiten:** Siehe [Pico/README.md](Pico/README.md). Firmware
   flashen, Skripte kopieren, ueber den `Pico-Setup`-Access-Point das
   Heim-WLAN eintragen.
2. **SteamOS-Dienste installieren:** Siehe [steamOs/README.md](steamOs/README.md).
   `./install.sh` im Ordner `steamOs/` ausfuehren (Erreichbarkeits-Monitor +
   periodischer Spiele-Scan).
3. **Spiel auswaehlen:** `python3 steamOs/gui/gui_server.py` starten, im
   Browser ein Spiel auswaehlen und an den Pico senden.
4. Beide Geraete muessen sich im selben lokalen Netzwerk befinden. Die
   Pico-IP wird von SteamOS automatisch per UDP-Broadcast gefunden - eine
   manuelle Eintragung in `steamOs/config.json` ist nur noetig, falls
   Broadcasts im Netzwerk blockiert sind.

## Protokoll zwischen SteamOS und Pico

| Richtung | Port | Nachricht | Zweck |
|---|---|---|---|
| SteamOS -> Pico | UDP 5006 | `DISCOVER_PICO` | Pico im Netzwerk finden |
| Pico -> SteamOS | UDP 5006 | `PICO:<ip>` | Antwort mit eigener IP |
| SteamOS -> Pico | TCP 5005 | `PING` | Erreichbarkeits-Check (alle 3s) |
| Pico -> SteamOS | TCP 5005 | `erreichbar` | Bestaetigung |
| SteamOS -> Pico | TCP 5005 | `SELECT:<uid>` | Ausgewaehltes Spiel senden (aus der GUI) |
| Pico -> SteamOS | TCP 5005 | `OK:<uid>` | Bestaetigt gespeicherte UID (siehe `Pico/selected_game.txt`) |
