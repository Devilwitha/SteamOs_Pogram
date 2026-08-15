# Pico

MicroPython-Programm fuer einen **Raspberry Pi Pico W / Pico 2 W** (WLAN-Chip
wird benoetigt) mit angeschlossenem **RFID-Leser/Schreiber RC522**,
optionalem **16x2-I2C-LCD** sowie optionalen **zwei Status-LEDs** (rot/gruen -
auf demselben Pico wie der RFID-Leser, nicht zu verwechseln mit dem
separaten [Led_Pico](../Led_Pico) fuer den LED-Streifen).

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
   den RC522 (`tag_manager.py`) und startet. Ab hier zeigen auch die
   beiden optionalen Status-LEDs den Tag-Zustand an (gruen = Tag erkannt
   UND Spielstart von SteamOS bestaetigt; rot = alles andere, siehe unten):
   - **TCP-Steuer-Server (Port 5005):** Zeilenbasiertes Protokoll:
     - `PING` -> Antwort `erreichbar` (periodischer Erreichbarkeits-Check von SteamOS)
     - `SELECT:<uid>[:<name>]` -> merkt die UID (optional mit
       Anzeigename fuers LCD) zum Verknuepfen mit dem **naechsten
       aufgelegten RFID-Tag** vor; Antwort `OK:<uid>`
       (wird von der [SteamOS-GUI](../steamOs/gui) genutzt)
     - `TAG?` -> Antwort `TAG:<uid>`, falls ein Tag mit einer neuen/noch nicht
       bestaetigten Spiel-UID aufliegt, sonst `TAG:NONE`
     - `STARTED:<uid>` -> SteamOS bestaetigt, dass das Spiel gestartet wurde;
       Antwort `OK:STARTED:<uid>` (oder `ERROR:mismatch`, falls der Tag inzwischen
       gewechselt hat)
     - `TAGS?` -> Antwort `TAGS:<json-liste>` aller bisher erkannten Tags mit
       ihrer (ggf. fehlenden) Spiel-Verknuepfung (inkl. Anzeigename)
     - `LINK:<uid>:<spiel-uid>[:<name>]` -> verknuepft einen bereits
       bekannten Tag direkt mit einem Spiel, ohne dass er erneut
       aufgelegt werden muss (leere Spiel-UID = Verknuepfung aufheben);
       Antwort `OK:LINK:<uid>` oder `ERROR:unknown_tag`
     - `TAGCOLOR:<uid>:<farbe>` -> setzt (leere Farbe = loescht) die
       eigene LED-Farbe eines bereits bekannten Tags, unabhaengig von der
       Spiel-Verknuepfung; Antwort `OK:TAGCOLOR:<uid>` oder
       `ERROR:unknown_tag`
     - `CURRENT?` -> Antwort `CURRENT:<json>` mit dem gerade aufliegenden
       Tag (`uid`/`game_uid`/`game_name`/`color`), unabhaengig vom
       einmaligen `TAG?`-Meldezustand, sonst `CURRENT:NONE` - wird von
       `steamOs/pico_client.py` genutzt, um den optionalen
       [Led_Pico](../Led_Pico) kontinuierlich mit der passenden Farbe zu
       versorgen, und intern von `ping_server._background_loop` genutzt,
       um das optionale LCD aktuell zu halten (siehe unten)
     - `FORGET` -> versetzt den Pico in den Loeschmodus: die naechste
       aufgelegte Karte wird beim naechsten Lesen komplett aus `tags.json`
       entfernt (nicht nur entknuepft wie bei `LINK` mit leerer Spiel-UID)
       und muss danach erneut aufgelegt werden, um wieder bekannt zu sein;
       Antwort `OK:FORGET` (genutzt vom "Tag loeschen..."-Button in der
       [SteamOS-GUI](../steamOs/gui))
   - **HTTP-Statuswebseite (Port 80):** `/` zeigt eine dunkel/modern
     gestaltete Statusseite (Geraetestatus, aktueller Tag, alle bekannten
     Tags), `/status.json` liefert dieselben Daten als JSON. `/control`
     zeigt zusaetzlich eine vollwertige **Fernsteuerseite** (siehe
     [Fernsteuerseite `/control`](#fernsteuerseite-control) unten),
     `/control/settings` (POST) speichert deren Verbindungseinstellungen.
     Alles nur im normalen WLAN-Betrieb aktiv (nicht im
     Hotspot-Setup-Modus, siehe `captive_portal.py`).
   - **UDP-Discovery-Server (Port 5006):** Antwortet auf `DISCOVER_PICO` mit
     `PICO:<eigene-ip>`, damit SteamOS den Pico automatisch im Netzwerk finden
     kann, ohne die IP von Hand eintragen zu muessen.
4. Faellt die WLAN-Verbindung **waehrend des Betriebs** weg (z. B.
   Router-Neustart, kurzer Aussetzer), erkennt der Hintergrund-Thread das
   spaetestens nach `WLAN_CHECK_INTERVAL_MS` (Standard 30 s) und startet
   den Pico automatisch neu - dadurch greift wieder die robuste
   Boot-Logik aus Schritt 1-2 (mehrere Verbindungsversuche, danach
   Hotspot-Fallback). Ohne diese Pruefung wuerde ein WLAN-Ausfall nach dem
   Booten unbemerkt bleiben und der Pico dauerhaft unerreichbar sein, auch
   wenn das WLAN spaeter wieder verfuegbar waere.

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
- Der MFRC522 liest eine aufliegende Karte nicht in jedem der
  `POLL_INTERVAL_MS` (300 ms)-Zyklen zuverlaessig. Deshalb gilt ein Tag
  erst als entfernt, wenn er `TAG_GRACE_MS` (Standard 3000 ms, siehe
  `tag_manager.py`) lang nicht mehr gelesen wurde - solange derselbe Tag
  (auch mit gelegentlichen Aussetzern) weiter aufliegt, bleibt der
  gemeldete Zustand (`TAG?`/`CURRENT?`, LCD) unveraendert stabil. Ein
  Wechsel auf einen **anderen** Tag wird dagegen sofort ohne
  Toleranzzeit uebernommen. `steamOs/pico_client.py` nutzt genau das,
  um ein per Tag gestartetes Spiel automatisch zu beenden, sobald der
  Tag laenger fehlt oder gewechselt hat (siehe `steamOs/README.md`).
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
- Zusaetzlich zur Spiel-Verknuepfung kann jedem Tag ueber `TAGCOLOR` (aus
  der SteamOS-GUI) eine eigene Farbe zugewiesen werden. Anders als die
  Spielstart-Meldung ist das **nicht** einmalig: `CURRENT?` liefert die
  Farbe des aktuell aufliegenden Tags bei jeder Abfrage frisch, damit der
  optionale [Led_Pico](../Led_Pico) einen LED-Streifen laufend in der
  passenden Farbe zeigt, solange der Tag aufliegt (Tag-Farbe hat Vorrang
  vor der Farbe des verknuepften Spiels).
- Ueber `FORGET` (aus der SteamOS-GUI per "Tag loeschen..."-Button) laesst
  sich ein Tag komplett vergessen statt nur entknuepft: der Pico merkt
  sich die Anfrage vor und entfernt die naechste aufgelegte Karte beim
  naechsten Lesen vollstaendig aus `tags.json` (inkl. Spiel-Verknuepfung
  und Farbe) - sie muss danach erneut aufgelegt werden, um wieder als
  bekannter Tag zu erscheinen. Hat Vorrang vor einer gleichzeitig per
  `SELECT` vorgemerkten Verknuepfung.
- Zum Testen/Debuggen des rohen RC522-Speicherinhalts (unabhaengig von
  main.py): `rfid_test.py` direkt in Thonny ausfuehren - zeigt die
  physische UID sowie den kompletten Speicherinhalt (alle
  Sektoren/Bloecke) einer aufgelegten Karte im Shell-Fenster an.

## Fernsteuerseite `/control`

Neben der read-only Statusseite (`/`) hostet der Pico unter
`http://<pico-ip>/control` eine zweite, vollstaendig bedienbare Seite
(`control.html`), die alles kann, was sonst nur die
[SteamOS-GUI](../steamOs/gui) auf dem PC bietet: Spielfarben setzen, Tags
verknuepfen/trennen/faerben/loeschen, Sounds hochladen/abspielen/entfernen,
ein Spiel "An Pico senden".

**Wichtig zu verstehen:** Der Pico fuehrt dabei selbst nichts davon aus und
speichert auch keine eigene Kopie von `games.db`. `status_server.py`
liefert nur die Seite aus (`render_control_page()` in `status_server.py`
fuellt lediglich die Platzhalter fuer die Verbindungseinstellungen ein,
siehe unten) - alle eigentlichen Aktionen fuehrt anschliessend das
JavaScript in `control.html` direkt im **Browser des Nutzers** aus, indem
es `steamOs/gui/gui_server.py` auf dem PC per `fetch()` anspricht (neue
`/api/...`-Routen dort, siehe `steamOs/README.md`). Der Pico ist also nur
"Web-Hosting", keine Datenverbindung dazwischen - das haelt seinen sehr
begrenzten Speicher (~264 KB RAM) unbelastet, insbesondere bei Sound-
Uploads (mehrere MB), die dadurch nie durch den Pico selbst muessen.

Vor der ersten Nutzung einmalig einrichten (Formular oben auf `/control`):

- **PC-IP**: wird automatisch als Vorschlag vorausgefuellt, sobald
  `steamOs/pico_client.py` mindestens einmal beim Pico angeklopft hat
  (siehe `net_state.py` - reine Nebenwirkung des sowieso alle paar
  Sekunden eintreffenden `PING`, kein eigener Mechanismus noetig). Laeuft
  `pico_client.py` noch nicht oder ist die IP falsch, von Hand eintragen.
- **PC-Port**: Standard `8090` (Port von `gui_server.py`).
- **Token**: muss exakt mit `remote_control_token` in `steamOs/config.json`
  uebereinstimmen - siehe dort, ohne passendes Token weist der PC alle
  Anfragen mit `401` zurueck.
- **PC-MAC** (optional): siehe [Wake-on-LAN](#wake-on-lan-pc-aus-dem-schlaf-wecken)
  unten.

Diese Werte werden in `remote_config.json` auf dem Pico gespeichert
(`remote_config.py`, Formular-POST auf `/control/settings`) und bei jedem
Aufruf von `/control` wieder in die Seite eingesetzt - sowohl escaped fuers
HTML-Formular als auch (separat escaped) fuers eingebettete JavaScript, da
sich das Token bewusst frei waehlen laesst und dabei theoretisch
Sonderzeichen wie `"` oder `&` enthalten kann. Die PC-MAC wird nur
serverseitig vom Pico selbst genutzt (siehe unten) und nicht ins JavaScript
eingebettet.

## Wake-on-LAN (PC aus dem Schlaf wecken)

Liegt ein mit einem Spiel verknuepfter Tag auf, antwortet SteamOS aber laenger
nicht (der Meldezustand bleibt auf "erkannt", d. h. nicht einmal `TAG?` kam
an - siehe `ping_server._maybe_send_wol()`), sendet der Pico automatisch ein
Wake-on-LAN "Magic Packet" per UDP-Broadcast (`wol.py`). Ist der PC danach
wach, uebernimmt `steamOs/pico_client.py` den Spielstart ganz normal wie
gewohnt - am Ablauf selbst aendert sich nichts, es kommt nur die
Aufweck-Verzoegerung hinzu.

Bei angeschlossenem LCD ist dieser Ablauf live mitverfolgbar (Zeile 1 bleibt
dabei durchgehend der Spielname): "Tag erkannt" -> nach `WOL_GRACE_MS` ohne
Reaktion von SteamOS "Keine Antwort" -> "Sende WOL..." (Magic Packet wird
verschickt) -> "Warte auf PC..." (bis SteamOS antwortet oder erneut gesendet
wird) -> sobald SteamOS antwortet ganz normal "An SteamOS..." und danach
"Spiel gestartet" (siehe `ping_server._wol_phase()`/`_WOL_ZEILE2`).

Voraussetzungen auf PC-Seite (jeweils einmalig einzurichten, nicht Teil
dieses Repos):

- **PC-MAC** im `/control`-Formular hinterlegen (MAC-Adresse der
  Netzwerkkarte, z. B. `AA:BB:CC:DD:EE:FF`) - unter Linux z. B. per
  `ip link show` oder `nmcli device show <interface>` zu ermitteln. Leer
  gelassen bleibt Wake-on-LAN komplett deaktiviert.
- **Kabelgebundenes Netzwerk empfohlen**: WLAN-Adapter unterstuetzen
  Wake-on-WLAN im Ruhezustand meist nicht zuverlaessig.
- **Wake-on-LAN im BIOS/UEFI aktivieren.**
- **Wake-on-LAN am Netzwerkadapter des Betriebssystems aktivieren**, z. B.
  unter Linux mit `ethtool -s <interface> wol g` (dauerhaft je nach
  Distribution per NetworkManager-Profil: `nmcli connection modify
  <verbindung> 802-3-ethernet.wake-on-lan magic`) oder in den
  Windows-Adaptereinstellungen unter "Energieoptionen" ->
  "Wake on Magic Packet".
- Der PC muss dafuer in einen Zustand versetzt worden sein, in dem die
  Netzwerkkarte weiterhin Standby-Strom erhaelt (z. B. Suspend-to-RAM/S3) -
  bei vollstaendig ausgeschaltetem PC haengt das von Mainboard/BIOS ab.

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

### Status-LEDs rot/gruen (optional, in `main.py`/`ping_server.py`)

Zwei einfache LEDs an freien GPIOs (RC522 belegt GP2-GP6, das optionale
LCD GP0-GP1), **auf demselben Pico wie der RFID-Leser** (nicht auf dem
separaten [Led_Pico](../Led_Pico) fuer den LED-Streifen), zeigen
unabhaengig vom LCD immer den aktuellen Tag-Zustand:

| LED | Pico-GPIO | Pico-Pinnummer (physisch) | Bedeutung |
|---|---|---|---|
| Rot (+, ueber Vorwiderstand) | GP7 | Pin 10 | **Kein Tag** aufgelegt, oder ein Tag liegt auf, aber SteamOS hat den Spielstart noch **nicht** bestaetigt (unverknuepfter Tag, oder `STARTED:<uid>` steht noch aus) |
| Gruen (+, ueber Vorwiderstand) | GP8 | Pin 11 | Tag liegt auf **und** SteamOS hat den Spielstart per `STARTED:<uid>` bestaetigt (`status == "gestartet"`, siehe `tag_manager._status_locked()`) |
| Beide (-) | GND | z. B. Pin 3, 8, 13 oder 38 | gemeinsame Masse |

Beide LEDs sind zueinander exklusiv (nie gleichzeitig an) und werden direkt
vom GPIO getrieben - dazwischen jeweils einen **Vorwiderstand (ca.
220-330 Ohm)** in Reihe zur LED schalten, sonst droht ein zu hoher Strom
durch den GPIO-Pin. Waehrend des WLAN-Verbindungsaufbaus bzw. im
Access-Point-Einrichtungsmodus bleiben beide LEDs aus (dafuer signalisiert
die eingebaute LED des Pico W den WLAN-Status, siehe `wlan.py`) - erst
sobald `ping_server.start()` laeuft (siehe Ablauf oben), uebernimmt
`ping_server._update_status_leds()` die Anzeige und haelt sie direkt nach
jedem RFID-Lesezyklus aktuell, genau wie beim LCD.

Die Pins lassen sich in `main.py` ueber `LED_ROT_PIN`/`LED_GRUEN_PIN`
anpassen. Ist die Initialisierung nicht erfolgreich oder werden keine LEDs
angeschlossen, wird das automatisch erkannt und uebersprungen - der Rest
des Programms laeuft unveraendert weiter.

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
darauf zunaechst den WLAN-Verbindungsstatus:

| Zeitpunkt | LCD-Anzeige |
|---|---|
| Waehrend des Verbindungsversuchs | `WLAN verbinden` / `...` |
| Erfolgreich verbunden (5 Sekunden) | `WLAN OK` / `<IP-Adresse>` |
| Danach, bis der erste RFID-Zyklus laeuft | `System bereit` / `<IP-Adresse>` |
| Verbindung fehlgeschlagen (Hotspot aktiv) | `WLAN Fehler` / `AP: Pico-Setup` |

Sobald WLAN und RFID-Leser stehen, uebernimmt
`ping_server._background_loop` die Anzeige und haelt sie direkt nach
jedem RFID-Lesezyklus (alle `tag_manager.POLL_INTERVAL_MS`, Standard
300 ms) aktuell - das LCD zeigt also laufend den Zustand des aufgelegten
Tags:

| Zustand | LCD-Anzeige |
|---|---|
| Keine Karte aufgelegt | `System bereit` / `<IP-Adresse>` |
| Karte aufgelegt, aber (noch) keinem Spiel zugeordnet | `Unbekannter Tag` / `UID:<hex-uid>` |
| Karte verknuepft, Spielname bekannt, SteamOS hat noch nicht per `TAG?` gefragt | `<Spielname>` / `Tag erkannt` |
| ... SteamOS hat per `TAG?` abgefragt, `STARTED:<uid>` steht noch aus | `<Spielname>` / `An SteamOS...` |
| ... SteamOS hat den Start per `STARTED:<uid>` bestaetigt | `<Spielname>` / `Spiel gestartet` |
| Karte verknuepft, aber (noch) kein Name hinterlegt | `Spiel verknuepft` / `UID:<spiel-uid>` |

Dieser Meldezustand (`erkannt`/`gesendet`/`gestartet`, siehe
`tag_manager._status_locked()`) wird auch als `status`-Feld im aktuellen
Tag von `CURRENT?` und `/status.json` mitgeliefert. Der Spielname stammt
aus dem optionalen dritten Feld von `SELECT:<uid>:<name>`
bzw. `LINK:<uid>:<spiel-uid>:<name>` (siehe oben) - die
[SteamOS-GUI](../steamOs/gui) schickt ihn automatisch mit, wenn ein Spiel
per "An Pico senden" ausgewaehlt oder ein Tag aus der Tag-Liste heraus
verknuepft wird. Er wird zusammen mit der Verknuepfung in `tags.json`
gespeichert, bleibt also auch nach einem Neustart des Pico erhalten und
wird bei einer erneuten Verknuepfung ohne Namen nicht ueberschrieben.

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
| `ping_server.py` | TCP-Steuer-Server (`PING`/`SELECT`/`TAG?`/`STARTED`/`TAGS?`/`LINK`/`TAGCOLOR`/`CURRENT?`) + HTTP-Statusserver (per `select()`) + kombinierter UDP-Discovery-/RFID-Hintergrund-Thread |
| `status_server.py` | HTTP-Logik/JSON fuer Statusseite (`status.html`) **und** Fernsteuerseite (`control.html`) |
| `status.html` | Statuswebseite (dark/modern), laedt Daten per JS von `/status.json` |
| `control.html` | Fernsteuerseite (siehe [Fernsteuerseite `/control`](#fernsteuerseite-control)) - spricht per JS direkt mit `gui_server.py` auf dem PC |
| `remote_config.py` | Persistiert die Verbindungseinstellungen (PC-IP/-Port/Token) der Fernsteuerseite (`remote_config.json`) |
| `net_state.py` | Haelt die zuletzt gesehene PC-IP im RAM (aus den periodischen `PING`s), nur als Formular-Vorschlag fuer `/control` |
| `mfrc522.py` | Low-Level-SPI-Treiber fuer den RC522-Chip |
| `rfid_reader.py` | Erkennt die physische UID eines aufgelegten Tags |
| `tag_store.py` | Persistente Zuordnungstabelle Tag-UID -> Spiel-UID + eigene Farbe (`tags.json`) |
| `tag_manager.py` | Debounce-Zustand fuer die Tag-Erkennung/-Meldung, `poll_once()` wird von `ping_server.py` aufgerufen |
| `rfid_test.py` | Eigenstaendiges Diagnoseskript: zeigt alle Daten einer aufgelegten Karte in Thonny an |
| `i2c_lcd.py` | Treiber fuer das 16x2-I2C-LCD (PCF8574-Backpack) |
| `lcd_test.py` | Eigenstaendiges Testskript: I2C-Scan + Testtext auf dem LCD |
| `wlan.conf` | Wird automatisch erzeugt, sobald WLAN-Daten gespeichert wurden (fruehere Versionen nutzten `wifi_config.json` - wird beim ersten Start automatisch dorthin migriert) |
| `tags.json` | Wird automatisch erzeugt/erweitert, sobald ein Tag erkannt bzw. verknuepft wird |
| `selected_game.txt` | Wird automatisch erzeugt/ueberschrieben, sobald SteamOS ein Spiel per `SELECT:<uid>` sendet |
| `remote_config.json` | Wird automatisch erzeugt, sobald die Verbindungseinstellungen auf `/control` gespeichert werden |

## Installation auf dem Pico

1. Flashe die aktuelle **MicroPython-Firmware fuer Pico W/Pico 2 W** (z. B. mit
   [Thonny](https://thonny.org) über *Run > Configure interpreter >
   Install or update firmware*).
2. Kopiere alle `.py`- **und `.html`-Dateien** aus diesem Ordner auf den Pico
   (z. B. mit Thonny per "Speichern unter" -> "Raspberry Pi Pico", oder mit
   `mpremote`) - `status_server.py`/`captive_portal.py` laden ihre Seiten zur
   Laufzeit aus `status.html`/`setup.html`/`control.html`, diese muessen also
   mit hochgeladen werden:

   ```
   mpremote cp main.py wlan.py captive_portal.py setup.html ping_server.py status_server.py status.html control.html net_state.py remote_config.py mfrc522.py rfid_reader.py tag_store.py tag_manager.py i2c_lcd.py :
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
  Das Gleiche gilt fuer ein fehlendes/nicht erkanntes LCD sowie fuer
  fehlende Status-LEDs.

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
