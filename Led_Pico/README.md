# Led_Pico

MicroPython-Programm fuer einen **zweiten, eigenstaendigen Raspberry Pi
Pico W / Pico 2 W** mit angeschlossenem **WS2812/NeoPixel-LED-Streifen**.
Laeuft unabhaengig vom RFID-Pico (siehe [../Pico](../Pico)) im selben
WLAN und wird von SteamOS mit der Farbe des aktuell erkannten Spiels bzw.
Tags versorgt (siehe [../steamOs/led_link.py](../steamOs/led_link.py) und
[../steamOs/pico_client.py](../steamOs/pico_client.py)).

Dieser Ordner ist bewusst **komplett eigenstaendig**: alles, was dieser
Pico zum Betrieb braucht, liegt hier drin (auch wo Dateien identisch zu
`../Pico` sind, z. B. `wlan.py`) - beide Geraete haben getrennten
Flash-Speicher und muessen unabhaengig voneinander bespielt werden
koennen.

## Ablauf

1. Beim Start versucht `main.py` ueber `wlan.py`, sich mit dem in
   `wlan.conf` gespeicherten WLAN zu verbinden (bis zu **3 Versuche**, je
   10 Sekunden Timeout) - technisch identisch zum RFID-Pico.
2. Klappt das nicht, oeffnet `wlan.py` automatisch einen eigenen
   **Access Point** namens `LedPico-Setup` (Passwort `picosetup123`) -
   bewusst ein anderer Name als beim RFID-Pico (`Pico-Setup`), damit beide
   Geraete beim Ersteinrichten unterscheidbar sind. Verbinde dich mit
   einem Handy/Laptop mit diesem WLAN und rufe im Browser
   `http://192.168.4.1/` auf, um SSID/Passwort deines Heim-WLANs
   einzutragen. Der Pico startet danach automatisch neu.
3. Ist die Verbindung erfolgreich, initialisiert der Pico den
   LED-Streifen (aus, bis die erste Farbe ankommt) und startet:
   - **TCP-Steuer-Server (Port 5007):** Zeilenbasiertes Protokoll:
     - `PING` -> Antwort `erreichbar`
     - `COLOR:<hex>` -> setzt den Streifen auf die angegebene Farbe (z. B.
       `#ff8800`, `ff8800` oder die Kurzform `f80`); Antwort
       `OK:COLOR:<hex>` oder `ERROR:bad_color` bei ungueltiger Eingabe
     - `OFF` -> schaltet den Streifen aus; Antwort `OK:OFF`
   - **UDP-Discovery-Server (Port 5008):** Antwortet auf
     `DISCOVER_LED_PICO` mit `LEDPICO:<eigene-ip>`, damit SteamOS den
     Led_Pico automatisch im Netzwerk findet.
4. Anders als der RFID-Pico braucht der Led_Pico **kein** Hintergrund-
   Polling - TCP- und UDP-Server laufen deshalb gemeinsam per `select()`
   im Hauptthread (`led_server.start()`), ganz ohne `_thread`.

## Zusammenspiel mit SteamOS / dem RFID-Pico

- In der [SteamOS-GUI](../steamOs/gui) laesst sich jedem **Spiel** und
  jedem **Tag** eine eigene Farbe zuweisen (Farbfeld je Zeile). Die
  Tag-Farbe hat Vorrang vor der Farbe des verknuepften Spiels.
- `steamOs/pico_client.py` fragt im selben 3-Sekunden-Takt wie den
  Erreichbarkeits-Check per `CURRENT?` beim RFID-Pico den gerade
  aufliegenden Tag ab (siehe [../Pico/README.md](../Pico/README.md)),
  ermittelt daraus die anzuzeigende Farbe (Tag-Farbe, sonst Spiel-Farbe,
  sonst aus) und schickt sie - nur bei Aenderung - per `COLOR:<hex>` bzw.
  `OFF` an den Led_Pico.
- Der Led_Pico ist dabei **optional**: ist keiner im Netzwerk
  konfiguriert/erreichbar, wird das beim Farb-Update stillschweigend
  uebersprungen, der RFID-Pico/Spielstart funktioniert unveraendert
  weiter.
- Konfiguration auf SteamOS-Seite: [`steamOs/led_config.json`](../steamOs/led_config.json)
  (`led_pico_ip` leer lassen fuer automatische Suche per UDP-Broadcast,
  sonst fest eintragen - analog zu `steamOs/config.json` beim RFID-Pico).

## Hardware / Verkabelung

Ein WS2812/NeoPixel-Streifen hat drei Anschluesse: **5V**, **GND** und
**DIN** (Dateneingang, oft auch "DI" oder "Data In" beschriftet - beim
Streifen selbst ist die Datenrichtung meist mit einem Pfeil markiert).

| Streifen-Pin | Anschluss |
|---|---|
| DIN (Data In) | Pico GP15 (Pin 20) - konfigurierbar über `LED_PIN` in `main.py` |
| GND | Gemeinsame Masse mit dem Pico (z. B. Pico-Pin 3, 8 oder 38) |
| 5V | **Eigenes 5V-Netzteil**, siehe unten |

**Wichtig - Stromversorgung:** Jede LED kann im Vollausschlag (weiss, volle
Helligkeit) bis zu ~60 mA ziehen. Schon ein kurzer 30er-Streifen kann also
kurzzeitig >1 A benoetigen - deutlich mehr, als der Pico über seinen
3V3-Regler oder USB-Port liefern kann. Den Streifen deshalb **immer über
ein eigenes 5V-Netzteil** versorgen (ausreichend dimensioniert fuer die
Anzahl LEDs), **nicht** über den Pico. Pico und Netzteil brauchen eine
**gemeinsame Masse** (GND-Leitung verbinden), sonst funktioniert die
Datenuebertragung nicht zuverlaessig. `LED_BRIGHTNESS` in `main.py`
(Standard `0.5`) begrenzt zusaetzlich per Software die maximale
Helligkeit/den Strombedarf.

**Datenleitung:** Der Pico liefert 3,3-V-Logikpegel, WS2812-Streifen sind
fuer 5-V-Logik spezifiziert. Bei kurzen Leitungen (< ca. 1 m) und wenigen
LEDs funktioniert die direkte Verbindung in der Praxis meist trotzdem
zuverlaessig; bei laengeren Leitungen, vielen LEDs oder Aussetzern/
Flackern wird ein Logic-Level-Shifter (3,3 V -> 5 V) auf der Datenleitung
empfohlen. Ein 300-500 Ω Widerstand direkt am Streifeneingang sowie ein
groesserer Pufferkondensator (z. B. 1000 µF) zwischen 5V und GND direkt
am Streifenanfang sind bei WS2812 uebliche, empfohlene Massnahmen gegen
Einschalt-Spannungsspitzen bzw. Datenfehler durch lange Leitungen.

`LED_PIN` und `LED_COUNT` (Anzahl LEDs im Streifen) in `main.py` an die
eigene Hardware anpassen.

## Dateien

| Datei | Zweck |
|---|---|
| `main.py` | Einstiegspunkt, wird beim Booten automatisch ausgefuehrt |
| `wlan.py` | WLAN-Verbindung + Hotspot-Fallback (identisch zu `../Pico/wlan.py`) |
| `captive_portal.py` | Webserver zur WLAN-Einrichtung im Access-Point-Modus (Logik; HTML in `setup.html`) |
| `setup.html` | Seite der WLAN-Einrichtung (Formular fuer SSID/Passwort) |
| `led_strip.py` | Treiber fuer den WS2812/NeoPixel-Streifen (ueber MicroPythons eingebautes `neopixel`-Modul) sowie Hex-Farb-Parsing |
| `led_server.py` | TCP-Steuer-Server (`PING`/`COLOR`/`OFF`) + UDP-Discovery-Server (per `select()`, kein Hintergrund-Thread noetig) |
| `wlan.conf` | Wird automatisch erzeugt, sobald WLAN-Daten gespeichert wurden |

## Installation auf dem Pico

1. Flashe die aktuelle **MicroPython-Firmware fuer Pico W/Pico 2 W** (z. B.
   mit [Thonny](https://thonny.org) über *Run > Configure interpreter >
   Install or update firmware*) - auf einem **zweiten, separaten** Pico W,
   nicht auf dem RFID-Pico.
2. Kopiere alle Dateien aus diesem Ordner auf den Pico (z. B. mit Thonny
   per "Speichern unter" -> "Raspberry Pi Pico", oder mit `mpremote`):

   ```
   mpremote cp main.py wlan.py captive_portal.py setup.html led_strip.py led_server.py :
   ```

3. LED-Streifen gemaess obiger Tabelle anschliessen (eigenes 5V-Netzteil
   nicht vergessen).
4. Pico neu starten (Reset-Taste oder Strom trennen/wieder anschliessen).
5. Beim ersten Start ist noch kein WLAN gespeichert -> der Access Point
   `LedPico-Setup` erscheint. Damit verbinden und unter
   `http://192.168.4.1/` das Heim-WLAN einrichten.
6. In `steamOs/led_config.json` optional die feste IP eintragen, falls
   UDP-Broadcast-Discovery im eigenen Netzwerk nicht zuverlaessig
   funktioniert (siehe [steamOs/README.md](../steamOs/README.md)).

## Hinweise

- Die Zugangsdaten liegen unverschluesselt als `wlan.conf` auf dem Pico -
  wie beim RFID-Pico, siehe [Pico/README.md](../Pico/README.md#hinweise).
- Ist kein LED-Streifen angeschlossen, meldet `neopixel.NeoPixel(...)`
  beim Schreiben keinen Fehler (es gibt schlicht nichts, das reagiert) -
  der restliche Server (WLAN, `PING`) funktioniert trotzdem normal
  weiter.
- Fuer die Fehlerbehandlung bei WLAN-Verbindungsproblemen gilt exakt
  dieselbe Anleitung wie beim RFID-Pico, siehe
  [Pico/README.md - Problembehandlung](../Pico/README.md#problembehandlung-wlan-verbindet-nicht--access-point-fallback-erscheint-nicht).
