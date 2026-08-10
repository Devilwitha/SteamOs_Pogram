# SteamOs_Pogram

Zwei zusammengehoerige Programme, die pruefen, ob ein Raspberry Pi Pico W im
Netzwerk erreichbar ist - und zwar auch dann, wenn das Steam Deck im
Game Mode laeuft.

- **[steamOs/](steamOs)** - laeuft als Hintergrunddienst (systemd --user) auf
  SteamOS. Sendet alle 3 Sekunden eine Anfrage an den Pico.
- **[Pico/](Pico)** - MicroPython-Programm fuer einen Raspberry Pi Pico W.
  Verbindet sich mit dem gespeicherten WLAN (bis zu 3 Versuche); klappt das
  nicht, oeffnet der Pico einen eigenen Access Point mit einer Webseite zur
  WLAN-Einrichtung. Antwortet danach auf jede Anfrage von SteamOS mit
  `erreichbar`.

## Einrichtungsreihenfolge

1. **Pico vorbereiten:** Siehe [Pico/README.md](Pico/README.md). Firmware
   flashen, Skripte kopieren, ueber den `Pico-Setup`-Access-Point das
   Heim-WLAN eintragen.
2. **SteamOS-Dienst installieren:** Siehe [steamOs/README.md](steamOs/README.md).
   `./install.sh` im Ordner `steamOs/` ausfuehren.
3. Beide Geraete muessen sich im selben lokalen Netzwerk befinden. Die
   Pico-IP wird von SteamOS automatisch per UDP-Broadcast gefunden - eine
   manuelle Eintragung in `steamOs/config.json` ist nur noetig, falls
   Broadcasts im Netzwerk blockiert sind.

## Protokoll zwischen SteamOS und Pico

| Richtung | Port | Nachricht | Zweck |
|---|---|---|---|
| SteamOS -> Pico | UDP 5006 | `DISCOVER_PICO` | Pico im Netzwerk finden |
| Pico -> SteamOS | UDP 5006 | `PICO:<ip>` | Antwort mit eigener IP |
| SteamOS -> Pico | TCP 5005 | `ping` | Erreichbarkeits-Check (alle 3s) |
| Pico -> SteamOS | TCP 5005 | `erreichbar` | Bestaetigung |
