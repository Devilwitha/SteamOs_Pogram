# Pico

MicroPython-Programm fuer einen **Raspberry Pi Pico W / Pico 2 W** (WLAN-Chip
wird benoetigt) mit angeschlossenem **RFID-Leser/Schreiber RC522** und
optionalem **16x2-I2C-LCD**.

## Ablauf

1. Beim Start versucht `main.py` ueber `wlan.py`, sich mit dem in `wlan.conf`
   gespeicherten WLAN zu verbinden (bis zu **3 Versuche**, je 10 Sekunden
   Timeout). Ist ein LCD angeschlossen, zeigt es "WLAN verbinden..." an.
2. Klappt das nicht, oder ist noch keine `wlan.conf` vorhanden, oeffnet
   `wlan.py` automatisch einen eigenen **Access Point** namens `Pico-Setup`
   (Passwort `picosetup123`). Verbinde dich mit einem Handy/Laptop mit
   diesem WLAN und rufe im Browser `http://192.168.4.1/` auf. Dort kannst
   du SSID und Passwort deines Heim-WLANs eingeben und speichern. Der Pico
   startet danach automatisch neu und versucht sich erneut zu verbinden.
   Wird laenger als `HOTSPOT_TIMEOUT_SEK` (Standard 10 Minuten) niemand
   aktiv, startet sich der Pico von selbst neu und versucht es erneut -
   nuetzlich, falls z. B. ein WLAN-Ausfall nur voruebergehend war.
3. Ist die Verbindung erfolgreich, zeigt das LCD (falls vorhanden) fuer
   5 Sekunden "WLAN OK" + die IP-Adresse an, danach initialisiert der Pico
   den RC522 (`tag_manager.py`) und startet:
   - **TCP-Steuer-Server (Port 5005):** Zeilenbasiertes Protokoll:
     - `PING` -> Antwort `erreichbar` (periodischer Erreichbarkeits-Check von SteamOS)
     - `SELECT:<uid>` -> merkt die UID zum Verknuepfen mit dem **naechsten
       aufgelegten RFID-Tag** vor; Antwort `OK:<uid>`
       (wird von der [SteamOS-GUI](../steamOs/gui) genutzt)
     - `TAG?` -> Antwort `TAG:<uid>`, falls ein Tag mit einer neuen/noch nicht
       bestaetigten Spiel-UID aufliegt, sonst `TAG:NONE`
     - `STARTED:<uid>` -> SteamOS bestaetigt, dass das Spiel gestartet wurde;
       Antwort `OK:STARTED:<uid>` (oder `ERROR:mismatch`, falls der Tag inzwischen
       gewechselt hat)
     - `TAGS?` -> Antwort `TAGS:<json-liste>` aller bisher erkannten Tags mit
       ihrer (ggf. fehlenden) Spiel-Verknuepfung
     - `LINK:<uid>:<spiel-uid>` -> verknuepft einen bereits bekannten Tag
       direkt mit einem Spiel, ohne dass er erneut aufgelegt werden muss
       (leere Spiel-UID = Verknuepfung aufheben); Antwort `OK:LINK:<uid>`
       oder `ERROR:unknown_tag`
   - **HTTP-Statuswebseite (Port 80):** `/` zeigt eine dunkel/modern
     gestaltete Statusseite (Geraetestatus, aktueller Tag, alle bekannten
     Tags), `/status.json` liefert dieselben Daten als JSON. Nur im
     normalen WLAN-Betrieb aktiv (nicht im Hotspot-Setup-Modus, siehe
     `captive_portal.py`).
   - **UDP-Discovery-Server (Port 5006):** Antwortet auf `DISCOVER_PICO` mit
     `PICO:<eigene-ip>`, damit SteamOS den Pico automatisch im Netzwerk finden
     kann, ohne die IP von Hand eintragen zu muessen.

### Nur ein Hintergrund-Thread (wichtig!)

Der Pico (RP2040/RP2350) hat nur einen einzigen zweiten Kern, den
MicroPythons `_thread` fuer genau **einen** zusaetzlichen Thread nutzen
kann - ein zweiter `_thread.start_new_thread()`-Aufruf schlaegt mit
`OSError: core1 in use` fehl. Deshalb:
- laufen UDP-Discovery-Server **und** RFID-Polling zusammen im einen
  verfuegbaren Hintergrund-Thread (`ping_server._background_loop`),
- laufen TCP-Steuer-Server (Port 5005) **und** HTTP-Statusserver (Port 80)
  ueber `select()` gemeinsam im Hauptthread (`ping_server._serve`).

`tag_manager.py` startet selbst **keinen** eigenen Thread mehr - falls du
eigene Erweiterungen mit `_thread` schreibst, beachte diese Einschraenkung.

### RFID-Verhalten (`tag_manager.py` / `tag_store.py`)

- Der Pico **liest laufend** die aufliegende Karte (physische UID, per
  Anti-Kollisionserkennung - immer moeglich, unabhaengig vom Tag-Typ).
- Jede neu gesehene Karte wird automatisch (ohne Verknuepfung) in
  `tags.json` gespeichert und ist damit sofort in der Statuswebseite bzw.
  ueber `TAGS?`/die SteamOS-GUI sichtbar.
- Die Verknuepfung Tag <-> Spiel-UID funktioniert in **beide Richtungen**:
  1. **Spiel zuerst:** `SELECT:<uid>` merkt die Spiel-UID vor; sobald
     danach eine Karte aufgelegt wird, wird genau diese damit verknuepft.
  2. **Tag zuerst:** Ein bereits erkannter (aber noch nicht verknuepfter)
     Tag laesst sich per `LINK:<uid>:<spiel-uid>` direkt mit einem Spiel
     verbinden, ohne ihn erneut aufzulegen - so nutzt es auch die
     SteamOS-GUI beim Verknuepfen aus der Tag-Liste heraus.
- Es wird **nichts mehr auf den Tag selbst geschrieben** (anders als in
  einer frueheren Version) - die Zuordnung lebt ausschliesslich in
  `tags.json` auf dem Pico. Dadurch funktioniert es auch mit Tags, die
  sich nicht beschreiben lassen bzw. mit einem anderen Schluessel
  gesichert sind.
- Eine mit einem Spiel verknuepfte Karte wird SteamOS ueber `TAG?` so
  lange gemeldet, bis SteamOS es per `STARTED:<uid>` bestaetigt (SteamOS
  hat das Spiel gestartet). Danach wird dieselbe UID **nicht erneut**
  gemeldet - erst wieder, wenn ein anderer Tag aufgelegt oder der Tag
  entfernt (und ggf. erneut aufgelegt) wird.
- Zum Testen/Debuggen des rohen RC522-Speicherinhalts (unabhaengig von
  main.py): `rfid_test.py` direkt in Thonny ausfuehren - zeigt die
  physische UID sowie den kompletten Speicherinhalt (alle
  Sektoren/Bloecke) einer aufgelegten Karte im Shell-Fenster an.

## Hardware / Verkabelung

Der RC522 wird per **SPI** an das Standard-SPI0 des Pico angeschlossen. Er
hat 8 Pins (`SDA`, `SCK`, `MOSI`, `MISO`, `IRQ`, `GND`, `RST`, `VCC`) - `IRQ`
wird nicht benoetigt und bleibt unbeschaltet:

| RC522-Pin | Pico-GPIO | Pico-Pinnummer (physisch) |
|---|---|---|
| SDA (auch SS/CS genannt) | GP5 | Pin 7 |
| SCK | GP2 | Pin 4 |
| MOSI | GP3 | Pin 5 |
| MISO | GP4 | Pin 6 |
| IRQ | - | nicht anschliessen |
| GND | GND | z. B. Pin 3, 8 oder 38 |
| RST | GP6 | Pin 9 |
| VCC | 3V3(OUT) | Pin 36 |

**Wichtig:** Der RC522 arbeitet mit **3,3 V**. `VCC` muss an `3V3(OUT)`
(Pin 36) angeschlossen werden - **nicht** an `VBUS`/5V (Pin 40), da das den
Chip beschaedigen kann.

Die Pin-Zuordnung (welche GPIOs verwendet werden) laesst sich beim Aufruf
von `tag_manager.init()` in `main.py` bei Bedarf anpassen (Parameter
`sck`, `mosi`, `miso`, `cs`, `rst`, `spi_id`, siehe `mfrc522.py`).

Verwendet werden MIFARE-Classic-Tags (z. B. die typischen weissen RC522-Testkarten/-Keyfobs) -
es wird nur deren physische UID gelesen, siehe RFID-Verhalten oben.

### 16x2-I2C-LCD (optional, `i2c_lcd.py` / `lcd_test.py`)

Fuer ein 16x2-Display mit dem ueblichen PCF8574-I2C-Backpack ("I2C
LCD1602"), ueber **I2C0** an freien GPIOs (RC522 belegt bereits GP2-GP6):

| LCD-Modul-Pin | Pico-GPIO | Pico-Pinnummer (physisch) |
|---|---|---|
| GND | GND | z. B. Pin 3, 8 oder 38 |
| VCC | 3V3(OUT) | Pin 36 |
| SDA | GP0 | Pin 1 |
| SCL | GP1 | Pin 2 |

**Wichtig:** Auch hier `VCC` an `3V3(OUT)` anschliessen, **nicht** an
`VBUS`/5V. Viele LCD1602-I2C-Module ziehen ihre I2C-Pullups auf `VCC` hoch -
bei 5V wuerden `SDA`/`SCL` dann mit ~5V auf die Pico-GPIOs treffen, die
nicht 5V-tolerant sind, und diese potenziell beschaedigen. Mit 3,3V
funktioniert das Display, der Kontrast ist ggf. etwas schwaecher (am
Potentiometer auf dem Backpack einstellbar).

`main.py` versucht das LCD automatisch zu initialisieren (I2C-Scan, erst
Adresse `0x27`, sonst die erste gefundene Adresse z. B. `0x3F`) und zeigt
darauf den WLAN-Verbindungsstatus:

| Zeitpunkt | LCD-Anzeige |
|---|---|
| Waehrend des Verbindungsversuchs | `WLAN verbinden` / `...` |
| Erfolgreich verbunden (5 Sekunden) | `WLAN OK` / `<IP-Adresse>` |
| Danach dauerhaft | `Pico bereit` / `<IP-Adresse>` |
| Verbindung fehlgeschlagen (Hotspot aktiv) | `WLAN Fehler` / `AP: Pico-Setup` |

Ist kein LCD angeschlossen (I2C-Scan findet nichts) oder schlaegt die
Initialisierung fehl, wird das automatisch erkannt und uebersprungen - der
Rest des Programms (WLAN, RFID, TCP-Server) laeuft unveraendert weiter.

Fuer einen einfachen, unabhaengigen Test: `lcd_test.py` direkt in Thonny
ausfuehren ("Run current script"). Das Skript scannt den I2C-Bus und zeigt
einen Testtext an.

## Dateien

| Datei | Zweck |
|---|---|
| `main.py` | Einstiegspunkt, wird beim Booten automatisch ausgefuehrt |
| `wlan.py` | WLAN-Verbindung + Hotspot-Fallback (Struktur analog zu [github.com/Devilwitha/Pico/Picodesk](https://github.com/Devilwitha/Pico/tree/main/Picodesk)) |
| `captive_portal.py` | Webserver zur WLAN-Einrichtung im Access-Point-Modus (Logik; HTML in `setup.html`) |
| `setup.html` | Seite der WLAN-Einrichtung (Formular fuer SSID/Passwort) |
| `ping_server.py` | TCP-Steuer-Server (`PING`/`SELECT`/`TAG?`/`STARTED`/`TAGS?`/`LINK`) + HTTP-Statusserver (per `select()`) + kombinierter UDP-Discovery-/RFID-Hintergrund-Thread |
| `status_server.py` | HTTP-Logik/JSON fuer die Statuswebseite (HTML in `status.html`) |
| `status.html` | Statuswebseite (dark/modern), laedt Daten per JS von `/status.json` |
| `mfrc522.py` | Low-Level-SPI-Treiber fuer den RC522-Chip |
| `rfid_reader.py` | Erkennt die physische UID eines aufgelegten Tags |
| `tag_store.py` | Persistente Zuordnungstabelle Tag-UID -> Spiel-UID (`tags.json`) |
| `tag_manager.py` | Debounce-Zustand fuer die Tag-Erkennung/-Meldung, `poll_once()` wird von `ping_server.py` aufgerufen |
| `rfid_test.py` | Eigenstaendiges Diagnoseskript: zeigt alle Daten einer aufgelegten Karte in Thonny an |
| `i2c_lcd.py` | Treiber fuer das 16x2-I2C-LCD (PCF8574-Backpack) |
| `lcd_test.py` | Eigenstaendiges Testskript: I2C-Scan + Testtext auf dem LCD |
| `wlan.conf` | Wird automatisch erzeugt, sobald WLAN-Daten gespeichert wurden (fruehere Versionen nutzten `wifi_config.json` - wird beim ersten Start automatisch dorthin migriert) |
| `tags.json` | Wird automatisch erzeugt/erweitert, sobald ein Tag erkannt bzw. verknuepft wird |
| `selected_game.txt` | Wird automatisch erzeugt/ueberschrieben, sobald SteamOS ein Spiel per `SELECT:<uid>` sendet |

## Installation auf dem Pico

1. Flashe die aktuelle **MicroPython-Firmware fuer Pico W/Pico 2 W** (z. B. mit
   [Thonny](https://thonny.org) über *Run > Configure interpreter >
   Install or update firmware*).
2. Kopiere alle `.py`- **und `.html`-Dateien** aus diesem Ordner auf den Pico
   (z. B. mit Thonny per "Speichern unter" -> "Raspberry Pi Pico", oder mit
   `mpremote`) - `status_server.py`/`captive_portal.py` laden ihre Seiten zur
   Laufzeit aus `status.html`/`setup.html`, diese muessen also mit hochgeladen
   werden:

   ```
   mpremote cp main.py wlan.py captive_portal.py setup.html ping_server.py status_server.py status.html mfrc522.py rfid_reader.py tag_store.py tag_manager.py i2c_lcd.py :
   ```

3. RC522 (und optional das LCD) gemaess obiger Tabellen anschliessen.
4. Pico neu starten (Reset-Taste oder Strom trennen/wieder anschliessen).
5. Beim ersten Start ist noch kein WLAN gespeichert -> der Access Point
   `Pico-Setup` erscheint. Damit verbinden und unter `http://192.168.4.1/`
   das Heim-WLAN einrichten.

## Hinweise

- Die Zugangsdaten liegen unverschluesselt als `wlan.conf` auf dem Pico.
  Das ist fuer ein privates Heimnetzwerk unkritisch, sollte bei
  sensibleren Umgebungen aber beruecksichtigt werden.
- Um das WLAN neu einzurichten, kann `wlan.conf` einfach vom Pico geloescht
  werden (z. B. mit Thonny) - beim naechsten Start erscheint dann wieder
  der Einrichtungs-Access-Point.
- Ist kein RC522 angeschlossen oder schlaegt die Initialisierung fehl, faengt
  `main.py` das ab und startet trotzdem normal weiter (nur ohne RFID-Funktion) -
  WLAN-Verbindung und Erreichbarkeits-Ping funktionieren dann weiterhin.
  Das Gleiche gilt fuer ein fehlendes/nicht erkanntes LCD.

## Problembehandlung: Statusseite/Setup-Seite bleibt im Browser leer

- MicroPython auf diesem Board unterstuetzt bei `bytes.decode()` **keine
  Keyword-Argumente** (z. B. `decode(errors="ignore")` schlaegt mit
  `TypeError: function doesn't take keyword arguments` fehl) - im Code
  wird deshalb durchgehend das argumentlose `decode()` verwendet.
- **Seite laedt im Browser leer/grau, obwohl das Log auf dem Pico
  "HTTP-Antwort gesendet" zeigt und curl/urllib die Antwort korrekt
  empfangen:** Ursache war, dass beim Lesen der Anfrage nur bis zum
  ersten Zeilenumbruch (`\n`) gelesen wurde statt bis zum Ende der
  HTTP-Header (`\r\n\r\n`). Echte Browser schicken deutlich mehr Header
  (User-Agent, Accept-\*, Sec-Fetch-\*, ...) als z. B. `urllib` - blieben
  davon Reste ungelesen im Socket-Puffer, wenn die Verbindung geschlossen
  wurde, schickte der TCP-Stack teils ein RST statt eines sauberen FIN,
  wodurch der Browser die bereits gesendete Antwort komplett verwarf.
  `ping_server.py`/`captive_portal.py` lesen deshalb jetzt vollstaendig
  bis `\r\n\r\n` und senden zusaetzlich einen expliziten
  `Content-Length`-Header, statt sich nur auf `Connection: close` zu
  verlassen.

## Problembehandlung: WLAN verbindet nicht / Access-Point-Fallback erscheint nicht

- **Pico W unterstuetzt nur 2,4-GHz-WLAN.** Ist im Router nur eine
  5-GHz-SSID sichtbar oder Band-Steering aktiv, schlaegt die Verbindung
  immer fehl. Testweise ein reines 2,4-GHz-Netz (z. B. Handy-Hotspot)
  verwenden.
- **Verbindung haengt dauerhaft im Status `CONNECTING (1)`**, obwohl SSID
  und Passwort stimmen und das Signal stark ist (im Log durch die
  Status-Ausgabe in `wlan.py` sichtbar): Das ist bei modernen
  WLAN-6-Routern (802.11ax) ein bekanntes Kompatibilitaetsproblem des
  CYW43439-Chips mit **WPA3**/**WPA2-WPA3-Mixed-Modus** oder mit
  **Protected Management Frames (802.11w)** auf "erforderlich". Abhilfe:
  Router-Sicherheitsmodus auf reines WPA2-Personal stellen, PMF auf
  "optional" setzen, oder ein separates 2,4-GHz-WPA2-Netz (z. B.
  IoT-/Gaeste-SSID) fuer den Pico einrichten. Das ist eine Router-
  Einstellung, kein Fehler im Programm. Live auf echter Hardware
  reproduziert: mit einer WPA2-Personal-Fritz!Box verbindet sich der Pico
  problemlos, mit einem WLAN6-Router mit WPA3/Mixed-Modus haengt er
  dauerhaft bei `CONNECTING`.
- Ein fehlgeschlagener Verbindungsversuch (z. B. falsches Passwort) laesst
  das Programm nicht mehr abstuerzen, bevor der Access-Point-Fallback
  gestartet wurde - `wlan.py` faengt Verbindungsfehler ab und faellt
  zuverlaessig auf den Access Point zurueck.
- `hotspot_starten()` wartet mit Timeout (Standard 15 s) auf den Access
  Point statt endlos zu blockieren - eine bekannte Eigenheit des
  CYW43439-Chips ist, dass der Access Point nach einem gescheiterten
  WLAN-Verbindungsversuch manchmal nicht sofort hochkommt. Kommt er bis
  dahin nicht hoch, startet sich der Pico automatisch neu.
- Falls der Access Point trotzdem nicht erscheint: `wlan.conf` vom
  Pico loeschen und einen kompletten Neustart (Strom trennen/wieder
  anschliessen) durchfuehren. Ueber ein Serial-Terminal (z. B. Thonny)
  angeschlossen lassen sich die `print()`-Ausgaben live mitverfolgen, um
  zu sehen, an welcher Stelle es haengt.
