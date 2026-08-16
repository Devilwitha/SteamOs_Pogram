# lilygo

Arduino/PlatformIO-Programm fuer einen **LilyGo T-Display-S3** (ESP32-S3 +
1,9" ST7789-Display, 170x320), das die aktuelle CPU-/GPU-Auslastung sowie
eine Temperatur von SteamOS anzeigt. Laeuft unabhaengig von RFID-Pico
(siehe [../Pico](../Pico)) und Led_Pico (siehe [../Led_Pico](../Led_Pico))
im selben WLAN und wird von SteamOS periodisch mit frischen Werten
versorgt (siehe [../steamOs/stats_monitor.py](../steamOs/stats_monitor.py)
und [../steamOs/lilygo_link.py](../steamOs/lilygo_link.py)).

## Warum Arduino/PlatformIO statt MicroPython?

Alle anderen Geraete in diesem Projekt (Pico, Led_Pico) laufen mit
MicroPython. Das T-Display-S3 steuert sein Display aber ueber einen
**parallelen 8-Bit-Bus** an, nicht ueber SPI wie das aeltere T-Display.
Fuer diesen Bus gibt es in Standard-MicroPython keinen ausgereiften
Treiber (bitgebangter Zugriff waere langsam/flackrig); TFT_eSPI
unterstuetzt ihn dagegen nativ und ist der von LilyGo selbst fuer dieses
Board empfohlene Weg. Deshalb ist dieser Ordner - anders als `Pico/` und
`Led_Pico/` - ein PlatformIO-Projekt (C++/Arduino).

## Protokoll

Analog zu [`Led_Pico/led_server.py`](../Led_Pico/led_server.py), nur mit
eigenen Ports:

- **TCP-Steuer-Server (Port 5009):** zeilenbasiert:
  - `PING` -> Antwort `erreichbar`
  - `STATS:<cpu>:<gpu>:<temp>` -> aktualisiert das Display; Antwort
    `OK:STATS`. `<cpu>`/`<gpu>` sind ganzzahlige Prozentwerte oder `-`
    (nicht ermittelbar), `<temp>` eine Zahl in Grad Celsius oder `-`.
- **UDP-Discovery-Server (Port 5010):** antwortet auf `DISCOVER_LILYGO`
  mit `LILYGO:<eigene-ip>`, damit SteamOS das Geraet automatisch im
  Netzwerk findet.

## Flashen

Voraussetzung: [PlatformIO](https://platformio.org/) (z. B. als
VS-Code-Extension oder CLI `pip install platformio`).

```bash
cd lilygo
pio run --target upload
pio device monitor   # optional, zeigt Log-Ausgaben inkl. der zugewiesenen IP
```

Falls PlatformIO das Board `lilygo-t-display-s3` nicht kennt (aeltere
`platform-espressif32`-Version):

```bash
pio pkg update
```

## Ablauf

1. Beim ersten Start (kein gespeichertes WLAN) oeffnet
   [WiFiManager](https://github.com/tzapu/WiFiManager) automatisch einen
   Access Point **`LilyGo-Setup`** (Passwort `picosetup123` - dasselbe
   Schema wie bei Pico/Led_Pico, nur ein anderer Name zur Unterscheidung).
   Verbinde dich mit einem Handy/Laptop mit diesem WLAN; WiFiManager
   oeffnet automatisch die Einrichtungsseite (falls nicht: im Browser
   `http://192.168.4.1/` aufrufen), dort SSID/Passwort des Heim-WLANs
   eintragen. Nach 180 Sekunden ohne Eingabe startet das Geraet neu und
   versucht es erneut.
2. Nach erfolgreicher Verbindung zeigt das Display kurz die eigene
   IP-Adresse an, dann startet der TCP-/UDP-Server (siehe oben).
3. `steamOs/stats_monitor.py` findet das Geraet per UDP-Broadcast (oder
   ueber eine feste IP in `steamOs/lilygo_config.json`) und schickt alle
   `interval_seconds` (Standard 2s) aktuelle Werte per `STATS:...`.
4. Das Geraet ist komplett **optional**: ohne Verbindung/ohne
   `stats_monitor.py` bleibt einfach der letzte Stand (bzw. die
   Labels ohne Werte) stehen - der Rest des Projekts (Spielstart per Tag,
   LED-Streifen) ist davon unabhaengig.

## Hardware-Hinweise

- **`PIN_POWER_ON` (GPIO 15) muss auf HIGH gesetzt werden**, sonst bleibt
  das Display beim T-Display-S3 dunkel - das macht `setup()` in
  `src/main.cpp` bereits automatisch. Bleibt der Bildschirm trotzdem
  schwarz: `ROTATION` in `src/main.cpp` betrifft nur die Bildausrichtung,
  nicht die Stromversorgung - dann eher Pinbelegung/TFT_eSPI-Build-Flags
  in `platformio.ini` gegen LilyGos offizielles `pin_config.h` fuer den
  T-Display-S3 pruefen (Board-Revisionen koennen leicht abweichen).
- `ROTATION` (0-3) in `src/main.cpp` an die eigene Einbaulage anpassen.
- Die Pinbelegung in `platformio.ini` (`build_flags`) entspricht LilyGos
  Standard-Pinout fuer den T-Display-S3. Bei einer anderen Revision oder
  einem aehnlichen Board ggf. dort anpassen.

## Zusammenspiel mit SteamOS

Konfiguration auf SteamOS-Seite:
[`steamOs/lilygo_config.json`](../steamOs/lilygo_config.json)
(`lilygo_ip` leer lassen fuer automatische Suche per UDP-Broadcast, sonst
fest eintragen - analog zu `steamOs/led_config.json`). Der Hintergrund-
Dienst `steamos-lilygo-monitor.service` wird von
[`steamOs/install.sh`](../steamOs/install.sh) automatisch mit
eingerichtet.

## Hinweise

- Die WLAN-Zugangsdaten speichert WiFiManager verschluesselt im
  ESP32-eigenen NVS-Flash-Speicher (nicht als Klartextdatei wie
  `wlan.conf` bei Pico/Led_Pico) - technisch bedingt durch die
  WiFiManager-Bibliothek.
- Die Firmware in diesem Ordner wurde nicht auf echter Hardware
  gegenkompiliert (kein PlatformIO/ESP32-Toolchain in der
  Entwicklungsumgebung verfuegbar, in der dieser Code entstand). Pin-
  Belegung und Register-Namen sind sorgfaeltig gegen LilyGos offizielle
  Dokumentation fuer den T-Display-S3 abgeglichen, aber bitte beim ersten
  Flashen auf Kompilierfehler/Fehlverhalten pruefen und melden.
