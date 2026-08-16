# steamOs

Hintergrundprogramm fuer den **Steam Deck / SteamOS**, das den [Pico](../Pico)
im Netzwerk ueberwacht - auch waehrend Steam im **Game Mode** laeuft.

## Funktionsweise

`pico_client.py` laeuft in einer Endlosschleife und sendet alle
`interval_seconds` (Standard: 3 Sekunden) eine Anfrage an den Pico:

- Ist die IP des Pico noch nicht bekannt (`pico_ip` in `config.json` leer),
  wird sie per UDP-Broadcast automatisch im lokalen Netzwerk gesucht
  (`DISCOVER_PICO`).
- Danach wird per TCP `PING` an den Pico geschickt; antwortet er mit
  `erreichbar`, wird das geloggt und in `state.json` festgehalten.
- Ist der Pico erreichbar, wird zusaetzlich per `TAG?` nachgefragt, ob am
  RC522 ein Tag mit einer neuen Spiel-UID aufliegt (siehe
  [Automatischer Spielstart](#automatischer-spielstart-per-rfid-tag) unten).
- **Antwortet der Pico voruebergehend nicht mehr** (WLAN-Aussetzer,
  Neustart des Pico, ...): Ist `pico_ip` fest in `config.json` eingetragen,
  wird genau diese IP beim naechsten Durchlauf einfach erneut angepingt -
  das Programm "haengt" sich also nicht endgueltig aus, sobald der Pico
  wieder erreichbar ist, verbindet es sich automatisch neu. Nur wenn keine
  feste `pico_ip` konfiguriert ist, wird stattdessen erneut per
  UDP-Broadcast gesucht (siehe oben, funktioniert nicht auf jedem Netzwerk
  zuverlaessig - siehe Hinweis bei `pico_ip` weiter unten).

Alle Ausgaben landen im systemd-Journal (`journalctl`), der aktuelle Status
zusaetzlich in `state.json` neben dem Skript, falls andere Programme ihn
auslesen wollen.

Die eigentliche Netzwerklogik (Discovery, Ping, Spielauswahl senden,
Tag-Status abfragen) liegt in `pico_link.py` und wird sowohl von
`pico_client.py` als auch von der GUI (`gui/gui_server.py`) verwendet.

## Warum es auch im Game Mode laeuft

Der "Game Mode" von SteamOS ist lediglich die grafische
gamescope/Steam-Oberflaeche - das Betriebssystem darunter (systemd) laeuft
unveraendert weiter. Der Dienst wird deshalb als **systemd --user Dienst**
installiert und per `loginctl enable-linger` dauerhaft aktiv gehalten, auch
wenn keine grafische Sitzung angemeldet ist. Dadurch ist kein Eingriff in das
schreibgeschuetzte Root-Dateisystem von SteamOS noetig.

## Installation

```bash
cd steamOs
chmod +x install.sh uninstall.sh
./install.sh
```

Das Skript kopiert `steamos-pico-monitor.service`, `steamos-gui.service`
sowie `steamos-game-scanner.service`/`.timer` nach
`~/.config/systemd/user/`, aktiviert und startet alle drei und richtet
Linger fuer den aktuellen Benutzer ein. Die GUI (siehe unten) laeuft danach
dauerhaft im Hintergrund unter `http://127.0.0.1:8080/`, ohne dass sie
manuell gestartet werden muss.

Status pruefen:

```bash
systemctl --user status steamos-pico-monitor.service
systemctl --user status steamos-gui.service
journalctl --user -u steamos-pico-monitor.service -f
journalctl --user -u steamos-gui.service -f
```

Deinstallieren:

```bash
./uninstall.sh
```

## Spiele-Datenbank (`game_scanner.py`)

`game_scanner.py` liest die installierten Steam-Spiele des Benutzers aus
und schreibt sie in eine lokale SQLite-Datenbank `games.db` (neben dem
Skript). Dazu werden die Steam-eigenen `libraryfolders.vdf`- und
`appmanifest_*.acf`-Dateien geparst (kein Steam-Account/API-Key noetig,
kein Internetzugriff erforderlich).

Tabelle `games`:

| Spalte | Beschreibung |
|---|---|
| `uid` | Stabile, aus der AppID abgeleitete UUID (bleibt bei erneuten Scans gleich) |
| `appid` | Original-AppID von Steam |
| `name` | Spieltitel |
| `installed` | `1`, falls der Installationsordner tatsaechlich vorhanden ist, sonst `0` |
| `install_path` | Pfad zum installierten Spiel, nur gesetzt wenn `installed = 1` |
| `launch_command` | `steam -applaunch <appid>`, nur gesetzt wenn `installed = 1` (startet das Spiel inkl. Proton-Kompatibilitaetsschicht ueber den Steam-Client) |
| `color` | Farbe (Hex, z. B. `#ff8800`) fuer LED-Anzeige (Led_Pico/OpenRGB) - manuell in der GUI zuweisbar, sonst automatisch aus dem Steam-Cover ermittelt (siehe unten) - wird von `game_scanner.py` beim erneuten Scannen **nicht** ueberschrieben, sobald einmal gesetzt |
| `audio_path` | Pfad zur in der GUI hochgeladenen Sound-Datei (siehe `gui/gui_server.py`), oder `NULL` ohne hinterlegten Sound - wird beim erneuten Scannen **nicht** ueberschrieben |
| `audio_enabled` | `1` (Standard) = Sound wird beim Tag-Start automatisch abgespielt, `0` = Datei bleibt erhalten, wird aber nur noch manuell (Test-Play-Button) abgespielt - per "Aktiv"/"Inaktiv"-Button in der GUI umschaltbar |
| `last_scanned` | Zeitpunkt des letzten Scans |

Manuell ausfuehren:

```bash
python3 steamOs/game_scanner.py
```

`./install.sh` richtet zusaetzlich einen systemd-Timer
(`steamos-game-scanner.timer`) ein, der die Bibliothek beim Booten und
danach alle 30 Minuten neu scannt, damit neu installierte oder entfernte
Spiele automatisch erfasst werden.

### Automatische Farbermittlung aus dem Steam-Cover

Neue Spiele ohne eigene `color` bekommen bei jedem Scan automatisch eine
zugewiesen: `game_scanner.py` sucht in Steams eigenem lokalem Bildcache
(`~/.local/share/Steam/appcache/librarycache/<appid>/`, bevorzugt
`library_600x900.jpg`, sonst `header.jpg` oder eine beliebige andere Datei
im Ordner) nach einem Cover und ermittelt daraus per
[Pillow](https://pillow.readthedocs.io/) (`pip install --user pillow` -
anders als der Rest von `steamOs/` bewusst nicht auf die Standardbibliothek
beschraenkt, siehe `openrgb-python`-Begruendung weiter unten) die
haeufigste Farbe einer stark reduzierten Farbpalette (deutlich lebendiger
als ein reiner Pixel-Mittelwert). Ohne brauchbares Cover oder ohne
installiertes Pillow wird stattdessen eine kraeftige Zufallsfarbe
verwendet - nie fuer alle Spiele dieselbe Farbe. Einmal gesetzte Farben
werden bei spaeteren Scans **nicht** mehr angetastet (weder automatisch
noch manuell gesetzte).

In der GUI (sowie der Pico-Steuerseite) setzt der Button
**"Farben zuruecksetzen..."** oberhalb der Spieletabelle die Farbe
*aller* Spiele auf ihre automatisch ermittelte zurueck - das
ueberschreibt auch manuell zugewiesene Farben (mit
Sicherheitsabfrage, da nicht rueckgaengig zu machen).

### Windows-Testversion (`game_scanner_windows.py`)

Zum lokalen Testen der GUI/des Pico-Clients auf einem Windows-Rechner
(ohne SteamOS-Hardware), z. B. waehrend der Entwicklung: sucht die
Steam-Installation ueber die Windows-Registry
(`HKCU\Software\Valve\Steam` -> `SteamPath`, faellt sonst auf die
uebliche `Program Files (x86)\Steam` zurueck) statt der Linux-Pfade.
Nutzt ansonsten exakt dieselbe Scan-/Datenbanklogik wie `game_scanner.py`
(keine Code-Duplikation - ueberschreibt nur `find_steam_root`) und
schreibt in dieselbe `games.db`:

```bash
python game_scanner_windows.py
```

## Spielauswahl-GUI (`gui/`)

[`gui/gui_server.py`](gui/gui_server.py) ist eine eigene, in `gui/`
gekapselte Weboberflaeche zur Auswahl eines Spiels aus `games.db`. Nach
`./install.sh` (siehe oben) laeuft sie bereits automatisch als
`steamos-gui.service`; manueller Start ist nur fuers lokale Testen ausserhalb
des Dienstes noetig:

```bash
python3 steamOs/gui/gui_server.py
```

Startet einen lokalen Webserver (`http://localhost:8090`, siehe `gui_port`
in `config.json`) und versucht,
ihn automatisch im Standardbrowser zu oeffnen (Desktop-Modus) - klappt das
nicht (z. B. kein Standardbrowser registriert), einfach die Adresse von
Hand im Browser aufrufen. Ausgeliefert wird dabei standardmaessig das
[Controller-Einstellungsmenue](#controller-einstellungsmenue--und-verwaltungs-gui-admin)
(`/`) - die hier beschriebene Tabellen-Ansicht liegt unter `/admin`. Das
HTML liegt in [`gui/index.html`](gui/index.html) (nicht im Python-Code
eingebettet); `gui_server.py` fuellt darin nur die Platzhalter
`__MESSAGE__`/`__ROWS__`/`__TAG_ROWS__`. Angezeigt werden alle Spiele aus
der Datenbank mit Name, Installationsstatus und UID. Klick auf
**"An Pico senden"**:

1. sucht den Pico im Netzwerk (oder nutzt die konfigurierte `pico_ip`),
2. sendet `SELECT:<uid>` an den Pico (Port `tcp_port`, Standard 5005),
3. der Pico merkt die UID zum Verknuepfen mit dem naechsten aufgelegten Tag
   vor (in `Pico/selected_game.txt` protokolliert) und antwortet mit `OK:<uid>`,
4. die GUI zeigt die vom Pico bestaetigte UID als Erfolgsmeldung an (bzw.
   eine Fehlermeldung, falls keine oder eine abweichende Bestaetigung kam).

Es wird bewusst eine reine Weboberflaeche auf Basis der Python-
Standardbibliothek verwendet (kein Tkinter/Qt), da auf SteamOS keine
zusaetzlichen System-Pakete installiert werden muessen (schreibgeschuetztes
Root-Dateisystem) - Firefox ist im Desktop-Modus bereits vorinstalliert.

Nach dem `SELECT`-Schritt muss noch ein Tag an den RC522 gehalten werden -
erst dann verknuepft der Pico ihn tatsaechlich mit der UID (siehe
[Pico/README.md](../Pico/README.md)).

### Controller-Einstellungsmenue (`/`) und Verwaltungs-GUI (`/admin`)

Spielstart selbst ist auf SteamOS bereits Aufgabe von **Steam Big Picture**
- ein zusaetzliches Kachel-Menue dafuer waere redundant. Stattdessen ist
[`gui/dashboard.html`](gui/dashboard.html) (neue Startseite von
`gui_server.py`) ein Einstellungsmenue fuer genau das, was Big Picture
nicht kann: die Hardware-Steuerung dieses Projekts (LEDs, Sound-Modus,
Sound/Farbe pro Spiel, RFID-Tag-Verknuepfung). Aufgebaut wie ein
Konsolen-Systemmenue (Kategorien links, Einstellungen rechts) und
vollstaendig per Tastatur/Maus **oder** per an den PC angeschlossenem
Controller ueber die
[Gamepad-Web-API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API)
bedienbar (kein zusaetzlicher Treiber noetig, sofern der Controller vom
Browser als Standard-Gamepad erkannt wird - funktioniert zuverlaessig bei
direktem Aufruf im normalen Desktop-Browser; **fuer den Start aus Big
Picture heraus siehe stattdessen
[gui/native_console.py](#als-nicht-steam-spiel-in-big-picture-hinzufuegen)
weiter unten** - dort liefert die Gamepad-Web-API unter Wayland keine
zuverlaessigen Events, siehe dort fuer Details):

| Aktion | Tastatur | Controller |
|---|---|---|
| Zeile/Kategorie wechseln | Pfeiltasten | D-Pad / linker Stick |
| Wert aendern (Toggle/Farbe/Modus) | Pfeil links/rechts | D-Pad/Stick links/rechts |
| Auswaehlen/Umschalten/Untermenue oeffnen | Enter/Leertaste | A |
| Zurueck | Esc/Backspace | B |
| Kategorie wechseln (von ueberall) | Q / E | LB / RB |

**Kategorien:** *LEDs* (Sync an/aus, Leerlauf-Farbe, Blinken bei
Sleep/Shutdown, Download-Pulsieren, Farbverlauf mit frei waehlbaren
Stuetzfarben bei 0/50/100% Downloadfortschritt), *Sound* (Modus-Umschalter
`songs`/`boot_sound`/`video`, Test-Wiedergabe), *Spiele* (pro Spiel: Farbe,
Sound aktiv/inaktiv + Test, "fuer naechsten Tag vormerken" - oeffnet sich
als Untermenue aus der Spieleliste), *Tags* (verknuepfen/trennen, Farbe,
loeschen - ebenfalls als Untermenue je Tag), *Werkzeuge* (alle
Spielfarben zuruecksetzen, mit Inline-Sicherheitsabfrage) und *Info*
(Softwareversion, Hersteller "BolliSoft", Code von Nico Bollhalder).
Farben werden
nicht per echtem Farbwaehler gesetzt (per Gamepad nicht praktikabel
bedienbar), sondern per fester Palette durchgeschaltet - jede Aenderung
speichert sofort ueber dieselben JSON-Endpunkte, die auch `/admin`
verwendet (`/api/set_game_color`, `/api/link_tag`, ...).

Datei-Uploads (neuer Sound/Boot-Video) bleiben bewusst der Tabellen-GUI
unter `/admin` vorbehalten - ein Datei-Dialog ist per Controller ohnehin
nicht sinnvoll bedienbar. Erreichbar ueber das Zahnrad-Icon oben rechts im
Menue bzw. direkt unter `http://localhost:8090/admin`.

### Als Nicht-Steam-Spiel in Big Picture hinzufuegen

Das Controller-Einstellungsmenue laeuft in Big Picture als **natives
Programm** ([`gui/native_console.py`](gui/native_console.py), gestartet
ueber den duennen Einstiegspunkt
[`gui/launch_dashboard.py`](gui/launch_dashboard.py)) statt in einem
Browser-Kiosk-Fenster. Grund: Chromes/Firefoxs Gamepad-Web-API liefert
unter Wayland (SteamOS/Bazzite) keine zuverlaessigen Controller-Events,
sobald die Seite von Steam aus gestartet wird - weder mit noch ohne Steam
Input (sowohl der Eintrags-Schalter als auch die globalen
"Xbox/PlayStation/Generic-Konfigurationsunterstuetzung"-Haken wurden
getestet, ohne Wirkung; nur Steams eigener "Steam-Taste halten"-
Systemcursor, unabhaengig vom Fenster, funktionierte). `native_console.py`
liest den Controller stattdessen direkt ueber SDL2 (`pygame-ce`, siehe
Voraussetzung unten) - dieselbe Eingabe-Schicht, die auch echte native
Linux-Spiele fuer Controller-Support nutzen, unabhaengig von
Fenster-Fokus-Weiterleitung durch Compositor/Steam/Browser. Das Backend
(`gui_server.py`, alle `/api/*`-Routen) ist davon unberuehrt - dasselbe
`native_console.py` spricht exakt dieselbe JSON-API wie zuvor
`dashboard.html`.

**Voraussetzung:** `pip install --user pygame-ce` (Version >=2.0 fuer das
SDL_GameController-API, `pygame._sdl2.controller` - normalisiert auch
exotischere Controller-Layouts auf ein Standard-Xbox-Layout). Falls
`pip install --user pygame` mit einem Fehler wie "Unable to run
sdl-config" fehlschlaegt (kein vorgebautes Wheel fuer die installierte
Python-Version, Build aus dem Quellcode braucht SDL2-Entwicklungspakete,
die auf SteamOS/Bazzite ohne `rpm-ostree install` nicht verfuegbar sind):
`pygame-ce` (https://pyga.me/) ist ein API-kompatibler Fork mit
aktuelleren vorgebauten Wheels und bringt dieselbe `import pygame`-API
mit - kein Code-Unterschied, nur ein anderes zu installierendes Paket.

**Einrichtung (einmalig, im Desktop-Modus):**

1. `pip install --user pygame-ce` (siehe oben).
2. Datei ausfuehrbar machen (falls noch nicht geschehen):
   `chmod +x steamOs/gui/launch_dashboard.py`.
3. Im Steam-Client: **Spiele -> Ein Nicht-Steam-Spiel zu meiner Bibliothek
   hinzufuegen...**, "Durchsuchen" und `steamOs/gui/launch_dashboard.py`
   auswaehlen.
4. Den neuen Eintrag umbenennen (z. B. "SteamOS Konsole").
5. Optional eigenes Vorschaubild: Eintrag in der Bibliothek mit der rechten
   Maustaste -> **Eigenschaften verwalten -> Benutzerdefinierte Grafiken
   festlegen...** und
   [`gui/assets/dashboard_grid.png`](gui/assets/dashboard_grid.png)
   auswaehlen (600x900, im selben HUD-Look wie das Menue selbst - per
   `python3 gui/assets/make_grid_art.py` neu erzeugbar, braucht Pillow).
6. In den Game Mode/Big Picture wechseln - der Eintrag erscheint in der
   Bibliothek wie ein Spiel.

**Bedienung:** D-Pad/linker Stick zum Navigieren, `A` waehlt/schaltet um,
`B` geht zurueck, `LB`/`RB` wechseln die Kategorie, `B` ca. 1s halten
beendet das Programm (Big Picture kehrt danach zur Bibliothek zurueck).
Tastatur (Pfeile/Enter/Escape/Q/E) und Maus (Klick auf eine Zeile bzw. auf
die `‹`/`›`-Pfeile bei Farb-/Modus-Zeilen) funktionieren zusaetzlich -
nuetzlich zum Testen ohne Controller, z. B. direkt per
`python3 steamOs/gui/launch_dashboard.py` im Desktop-Modus.

### Farbe pro Spiel (fuer den Led_Pico)

In der Spiele-Tabelle gibt es eine Spalte "Farbe" mit einem Farbfeld je
Zeile - Aenderungen werden sofort direkt in `games.db` gespeichert. Genau
eine Farbe pro Spiel (bewusst keine zusaetzliche, separate Tag-Farbe mehr -
fruehers TAGCOLOR-Feature war zwei potenziell widerspruechliche Farben pro
Spiel/Tag-Paar). Die Tag-Tabelle hat deshalb keine eigene Farbspalte mehr;
im Controller-Einstellungsmenue (siehe unten) zeigt ein Farbklecks je Tag
aber weiterhin zur Information die Farbe des jeweils verknuepften Spiels.
`pico_client.py` nutzt die Spielfarbe, um einen optionalen
zweiten Pico (siehe [../Led_Pico](../Led_Pico)) mit der passenden Farbe
fuer einen LED-Streifen zu versorgen - siehe
[Automatischer Spielstart](#automatischer-spielstart-per-rfid-tag) und
[Konfiguration des Led_Pico](#konfiguration-des-led_pico-led_configjson)
unten.

### Bekannte Tags verwalten (beide Richtungen)

Unterhalb der Spieleliste zeigt die GUI eine zweite Tabelle "Bekannte
RFID-Tags" - abgerufen per `TAGS?` vom Pico. Jeder Tag, der jemals an den
RC522 gehalten wurde, taucht hier automatisch auf, auch ohne vorher ein
Spiel ausgewaehlt zu haben. Von hier aus laesst sich ein Tag direkt (ohne
erneutes Auflegen) per `LINK:<uid>:<spiel-uid>` mit einem Spiel
verknuepfen oder wieder trennen - die zweite Richtung neben "Spiel
waehlen, dann Tag scannen".

Der Button **"Tag loeschen..."** ueber dieser Tabelle entfernt dagegen
einen Tag komplett (nicht nur die Verknuepfung): ein Klick schickt
`FORGET` an den Pico (`pico_link.forget_next_tag()`) und versetzt ihn
damit in den Loeschmodus; die Seite zeigt danach die Aufforderung, den zu
loeschenden Tag an den RC522 zu halten. Der Pico entfernt die naechste
aufgelegte Karte beim naechsten Lesen vollstaendig aus `tags.json` (siehe
`Pico/README.md#rfid-verhalten-tag_managerpy--tag_storepy`) - sie
verschwindet dadurch aus der Tag-Liste und muss danach erneut aufgelegt
werden, um wieder als bekannter Tag zu erscheinen. Es gibt (wie beim
uebrigen Formular-basierten Aufbau der GUI) keine Live-Bestaetigung per
JavaScript, sobald die Loeschung tatsaechlich stattgefunden hat - ein
Neuladen der Seite zeigt den aktuellen Stand.

## Fernsteuerung direkt von der Pico-Webseite aus (`/control`)

Alles, was die GUI oben kann (Farben, Tag-Verknuepfung/-Farbe/-Loeschen,
Sound-Upload/-Wiedergabe, "An Pico senden"), laesst sich zusaetzlich direkt
ueber eine vom **Pico selbst** gehostete Seite bedienen -
`http://<pico-ip>/control` (siehe [`Pico/control.html`](../Pico/control.html),
Details zur Pico-seitigen Umsetzung in
[`Pico/README.md`](../Pico/README.md#fernsteuerseite-control)). Praktisch,
wenn man am Pico/RFID-Leser steht und nicht extra zum PC gehen will, z. B.
um schnell einen neuen Sound hochzuladen.

Technisch bleibt `games.db` dabei die einzige Datenbank: der Pico speichert
selbst nichts dauerhaft, sondern liefert nur die Seite aus. Deren
JavaScript spricht anschliessend direkt (per `fetch()`, aus dem Browser des
Geraets, mit dem man die Pico-Seite aufgerufen hat) mit `gui_server.py` auf
dem PC - inklusive Datei-Uploads (Songs landen dadurch unveraendert direkt
auf dem PC/in `games.db`, ohne durch den speicherschwachen Pico
"hindurchzumuessen"). Damit das funktioniert, muss `gui_server.py`:

1. mit `"gui_bind": "0.0.0.0"` in `config.json` bewusst fuers LAN geoeffnet
   werden (Standard ist weiterhin `"127.0.0.1"`, also nur lokal erreichbar -
   ohne diese Aenderung bleibt `/control` ohne Wirkung), und
2. ein `"remote_control_token"` in `config.json` gesetzt haben - siehe
   [Konfiguration](#konfiguration-configjson) unten. Anfragen von
   `127.0.0.1` (die normale Desktop-GUI) sind davon unberuehrt, alles
   andere (also auch `/control`) braucht das Token, sonst `401`.

Einrichtung auf der Pico-Seite (einmalig, im Formular oben auf
`/control`): PC-IP, PC-Port (Standard `8080`) und dasselbe Token wie in
`config.json` eintragen und speichern - die IP wird dabei bereits als
Vorschlag vorausgefuellt, sobald `pico_client.py` mindestens einmal
gelaufen ist (siehe `Pico/README.md`).

## Automatischer Spielstart per RFID-Tag

Sobald `pico_client.py` laeuft (siehe oben), passiert bei jedem 3-Sekunden-
Takt zusaetzlich Folgendes:

1. Es wird per `TAG?` beim Pico nachgefragt, ob eine neue/unbestaetigte
   Spiel-UID auf einem aufliegenden Tag erkannt wurde.
2. Ist eine UID gemeldet, wird sie in `games.db` nachgeschlagen.
   - Unbekannte UID -> es wird nur eine Warnung geloggt, nichts gestartet.
   - Bekannte UID, aber Spiel nicht installiert -> Warnung, nichts gestartet.
   - Bekannte, installierte UID -> das Spiel wird per `launch_command`
     (`steam -applaunch <appid>`) gestartet.
3. War der Start erfolgreich, wird dem Pico per `STARTED:<uid>` bestaetigt,
   dass das Spiel laeuft. Der Pico meldet diese UID danach nicht mehr, bis
   ein anderer Tag aufgelegt oder der Tag entfernt (und neu aufgelegt) wird -
   ein bereits gestartetes Spiel wird also nicht bei jedem Poll erneut
   gestartet, solange derselbe Tag liegen bleibt.
4. Unabhaengig davon wird bei jedem Takt zusaetzlich per `CURRENT?` der
   aktuell aufliegende Tag abgefragt (nicht einmalig wie `TAG?`, siehe
   oben) und die daraus ermittelte Farbe (Farbe des verknuepften Spiels,
   sonst Weiss im Leerlauf - konfigurierbar, siehe `led_settings.py`/
   `resolve_led_color()`) an einen optionalen [Led_Pico](../Led_Pico)
   sowie optionale lokale USB-RGB-LEDs per OpenRGB (siehe
   [Corsair/OpenRGB-LEDs](#corsair-openrgb-usb-rgb-leds)) weitergereicht -
   jeweils nur wenn sie sich seit dem letzten Takt geaendert hat.
5. **Auch ganz ohne aufliegenden Tag** (oder ganz ohne Pico) ermittelt
   `pico_client.py` bei jedem Takt zusaetzlich per Prozess-Scan
   (`_scan_for_process_color()`), ob eines der installierten Spiele gerade
   laeuft (z. B. direkt ueber Steam Big Picture gestartet, ohne RFID) -
   dessen Farbe wird dann genauso an die LEDs weitergereicht wie bei einem
   per Tag erkannten Spiel. Bevorzugt dafuer Steams eigenen `reaper`-
   Prozess (`SteamLaunch AppId=<id>`, bleibt zuverlaessig fuer die
   komplette Spielsitzung bestehen) statt eines reinen Abgleichs gegen den
   Installationspfad, der bei Proton-Spielen nur kurzlebige Bootstrap-
   Prozesse faende, nicht das eigentliche (unter einem virtuellen
   Windows-Pfad laufende) Spiel.

### Automatisches Beenden bei entferntem/gewechseltem Tag

Dieselbe `CURRENT?`-Abfrage aus Schritt 4 wird auch genutzt, um ein per
Tag gestartetes Spiel automatisch wieder zu beenden (`check_game_still_active()`
in `pico_client.py`):

- Liegt der Tag, mit dem das laufende Spiel gestartet wurde, weiterhin auf
  (auch mit gelegentlichen Lesefehlern - der Pico toleriert das bereits
  selbst bis zu `tag_manager.TAG_GRACE_MS`, Standard 3 Sekunden, siehe
  `Pico/README.md`), passiert nichts.
- Liegt er laenger nicht mehr auf, oder liegt inzwischen ein anderer Tag
  auf, wird das Spiel beendet, bevor (falls zutreffend) das neue Spiel
  gestartet wird.
- **Wichtiger Hinweis zu `steam -applaunch <appid>`:** Dieser Befehl
  benachrichtigt nur den bereits laufenden Steam-Client und beendet sich
  selbst meist sofort wieder - das eigentliche Spiel laeuft als eigener,
  von Steam gestarteter Prozess. Ein simples `terminate()` auf den beim
  Start erzeugten Prozess wuerde das Spiel selbst also i. d. R. **nicht**
  stoppen. `stop_game()` sucht deshalb zusaetzlich (Linux/`/proc`) nach
  laufenden Prozessen unterhalb von `install_path` des Spiels und schickt
  diesen `SIGTERM` - zusaetzlich, sofern gefunden, auch an Steams eigenen
  `reaper`-Prozess (`SteamLaunch AppId=<id>`, siehe oben): der beendet
  beim Empfang von `SIGTERM` zuverlaessig auch das von ihm ueberwachte
  Spiel mit, selbst wenn der eigentliche Spielprozess (z. B. bei Proton
  unter einem virtuellen Windows-Pfad) sich nicht ueber `install_path`
  finden liesse. Das bleibt trotzdem ein Best-Effort-Ansatz (kein
  offizieller Steam-Mechanismus) - bei Spielen mit ungewoehnlicher
  Prozessstruktur kann das Beenden unvollstaendig bleiben.

Die worst-case Verzoegerung zwischen tatsaechlichem Entfernen des Tags und
dem Beenden des Spiels ist die Summe aus `tag_manager.TAG_GRACE_MS` (Pico,
Standard 3 s) und `interval_seconds` (SteamOS-Poll-Takt, Standard 3 s) -
also bis zu ca. 6 Sekunden. Fuer eine schnellere Reaktion beide Werte
entsprechend verkleinern (Kompromiss: kleinere Werte reagieren schneller,
tolerieren aber weniger Lesefehler/Netzwerk-Jitter, bevor faelschlich ein
laufendes Spiel beendet wird).

## Konfiguration des Led_Pico (`led_config.json`)

```json
{
  "led_pico_ip": "",
  "tcp_port": 5007,
  "udp_port": 5008
}
```

Analog zu `config.json` fuer den RFID-Pico, aber fuer den optionalen
zweiten Pico ([../Led_Pico](../Led_Pico)), der einen LED-Streifen in der
Farbe des aktuellen Spiels/Tags ansteuert. `led_pico_ip` leer lassen fuer
automatische Suche per UDP-Broadcast, sonst fest eintragen. Ist kein
Led_Pico im Netzwerk konfiguriert/erreichbar, wird das beim Farb-Update
stillschweigend uebersprungen - er ist rein optional, der RFID-Pico/
Spielstart funktioniert unabhaengig davon.

<a id="corsair-openrgb-usb-rgb-leds"></a>
## OpenRGB (lokale USB-RGB-LEDs, `openrgb_config.json`)

```json
{
  "enabled": true,
  "host": "127.0.0.1",
  "port": 6742,
  "target_names": ["Corsair"]
}
```

Ein viertes, ebenfalls optionales "Geraet": lokal per USB angeschlossene
RGB-LEDs (z. B. ein Corsair-LED-Streifen), angesteuert ueber
[OpenRGB](https://openrgb.org) statt eines eigenen Pico. Zeigt dieselbe
Farbe wie der Led_Pico (siehe oben), aber lokal am PC. Setzt voraus:

1. OpenRGB installiert (auf SteamOS/Bazzite z. B. per
   `flatpak install flathub org.openrgb.OpenRGB`) und als Dienst aktiv
   (`steamos-openrgb.service`, wird von `install.sh` nur eingerichtet,
   wenn OpenRGB tatsaechlich installiert ist - sonst wuerde der Dienst mit
   `Restart=always` endlos gegen eine fehlende Flatpak-App fehlschlagen).
   Laeuft dabei bewusst mit `QT_QPA_PLATFORM=offscreen` (siehe
   `steamos-openrgb.service`): im Game Mode sind weder `DISPLAY` noch
   `WAYLAND_DISPLAY` in der systemd-Sitzung gesetzt, OpenRGB (Qt) stuerzt
   ohne diese Variable dort sofort und dauerhaft ab, sobald es einen
   Anzeige-Server sucht - unnoetig, da OpenRGB hier nur als headless
   SDK-Server laeuft.
2. Die offizielle Python-Bibliothek installiert:
   `pip install --user openrgb-python` (anders als der Rest von `steamOs/`
   bewusst nicht auf die Standardbibliothek beschraenkt - das binaere
   OpenRGB-SDK-Protokoll ist zu komplex fuer eine eigene, robuste
   Nachimplementierung).

Ein PC meldet OpenRGB typischerweise mehrere RGB-faehige Geraete
(Grafikkarte, Mainboard, Maus, ...), von denen aber nur die zu
`target_names` passenden (Gross-/Kleinschreibung egal, Teilstring reicht)
die Spiel-/Leerlauf-Farbe bekommen - Standard `["Corsair"]`. **Alle
uebrigen Geraete werden einmalig beim Start von `pico_client.py` komplett
ausgeschaltet** (siehe `openrgb_link.turn_off_others()`), damit sie nicht
mit eigenen Werkseffekten (Rainbow etc.) weiterlaufen und stoeren. Bei
mehreren/anderen Ziel-Geraeten `target_names` anpassen - Namen wie in
`flatpak run org.openrgb.OpenRGB --list-devices` angezeigt.
`enabled: false` deaktiviert die gesamte Integration (weder Farb-Sync
noch Ausschalten der uebrigen Geraete), ohne `openrgb_link.py` selbst
aendern zu muessen. Ist OpenRGB nicht installiert/erreichbar oder die
Bibliothek fehlt, wird das beim Farb-Update stillschweigend uebersprungen
(siehe `openrgb_link.py`) - rein optional, der RFID-Pico/Spielstart
funktioniert unabhaengig davon.

## LilyGo-Statusdisplay (`lilygo_config.json`)

```json
{
  "lilygo_ip": "",
  "tcp_port": 5009,
  "udp_port": 5010,
  "interval_seconds": 2
}
```

Ein drittes, ebenfalls optionales Geraet: ein
[LilyGo T-Display-S3](../lilygo), das CPU-/GPU-Auslastung sowie eine
Temperatur anzeigt. `stats_monitor.py` liest die Werte ohne
Zusatzpakete direkt aus sysfs/procfs (siehe `system_stats.py`) und
schickt sie alle `interval_seconds` an das Display (siehe
`lilygo_link.py`) - analog zum Led_Pico laeuft das als eigener,
unabhaengiger Hintergrund-Dienst (`steamos-lilygo-monitor.service`, wird
von `install.sh` mit eingerichtet). `lilygo_ip` leer lassen fuer
automatische Suche per UDP-Broadcast, sonst fest eintragen. Ist kein
Display im Netzwerk konfiguriert/erreichbar, laeuft der Dienst einfach
weiter, ohne dass das sonst irgendwelche Auswirkungen hat.

## Wake-on-USB (Controller weckt den PC aus dem Standby)

`install.sh` richtet zusaetzlich eine udev-Regel ein, die den PC aus dem
Standby (S3-Suspend) aufweckt, sobald am konfigurierten USB-Controller
etwas passiert (z. B. Einschalten) - unabhaengig vom RFID-Pico/Wake-on-LAN
weiter oben. Betrifft standardmaessig den **8BitDo Ultimate 2**
(USB-ID `2dc8:6013`) - fuer einen anderen Controller die Variablen
`CONTROLLER_VENDOR_ID`/`CONTROLLER_PRODUCT_ID` am Anfang des
entsprechenden Abschnitts in `install.sh` anpassen (Wert per `lsusb`
ermitteln).

Ablauf beim Ausfuehren von `install.sh`:

1. Die USB-Bus-Nummer des Controllers wird dynamisch ueber seine USB-ID
   ermittelt (nicht fest einkompiliert, da sie sich mit dem physischen
   Port aendern kann).
2. Eine persistente Regel wird nach `/etc/udev/rules.d/10-wakeup.rules`
   geschrieben (`SUBSYSTEM=="usb", KERNEL=="usbN", ATTR{power/wakeup}="enabled"`),
   die dafuer sorgt, dass der Bus nach jedem Neustart/erneuten Einstecken
   automatisch als Wake-Quelle aktiviert wird.
3. Der aktuelle Zustand wird zusaetzlich sofort direkt gesetzt
   (`udevadm trigger` allein wirkt bei einem bereits verbundenen Geraet
   oft nicht zuverlaessig).

**Voraussetzungen (im BIOS/UEFI, nicht Teil dieses Repos):**
"Wake from USB"/"USB Wake Support" aktivieren, "ErP Mode" deaktivieren
(schaltet sonst USB-Strom im Standby ab). Wake funktioniert **nicht** ueber
Bluetooth, nur ueber eine echte USB-Verbindung (auch ein 2,4-GHz-USB-Dongle
zaehlt dafuer als USB).

Dieser Schritt ist der einzige in `install.sh`, der `sudo` braucht (Schreiben
nach `/etc/udev/rules.d/`) - schlaegt er fehl, wird das mit einer
Fehlermeldung uebersprungen, ohne den Rest des Skripts abzubrechen. Ist der
Controller beim Ausfuehren von `install.sh` nicht angeschlossen, wird dieser
Schritt uebersprungen (Hinweis wird ausgegeben) - `install.sh` bei
angeschlossenem Controller erneut ausfuehren, um es nachzuholen. Status
pruefen: `cat /sys/bus/usb/devices/usbN/power/wakeup` (sollte `enabled`
zeigen, `usbN` durch die tatsaechliche Bus-Nummer ersetzen). `uninstall.sh`
entfernt die Regel wieder.

## Konfiguration (`config.json`)

```json
{
  "pico_ip": "",
  "tcp_port": 5005,
  "udp_port": 5006,
  "interval_seconds": 3,
  "gui_bind": "127.0.0.1",
  "gui_port": 8090,
  "remote_control_token": ""
}
```

- `pico_ip`: Optional. Leer lassen fuer automatische Suche im Netzwerk, oder
  eine feste IP eintragen, falls UDP-Broadcasts in deinem Netzwerk
  blockiert werden.
- `tcp_port` / `udp_port`: Muessen mit den Ports in `Pico/ping_server.py`
  uebereinstimmen (Standard 5005 / 5006).
- `interval_seconds`: Wie oft (in Sekunden) angefragt wird.
- `gui_bind`: Auf welcher Adresse `gui_server.py` lauscht. Standard
  `"127.0.0.1"` (nur lokal erreichbar, unveraendertes Verhalten). Nur auf
  `"0.0.0.0"` setzen, wenn die [Fernsteuerung von der Pico-Seite aus](#fernsteuerung-direkt-von-der-pico-webseite-aus-control)
  genutzt werden soll - **oeffnet dann Schreibzugriff (Spiele starten,
  Tags loeschen, Sounds ersetzen, ...) fuers gesamte LAN**, siehe
  `remote_control_token`.
- `gui_port`: Auf welchem Port `gui_server.py` lauscht. Standard `8090`
  (nicht `8080`, da dieser Port auf SteamOS bereits vom clientinternen
  `steamwebhelper` von Steam selbst belegt ist).
- `remote_control_token`: Leer = Fernzugriff komplett gesperrt (sicherer
  Default, auch wenn `gui_bind` auf `"0.0.0.0"` steht). Ein beliebiger,
  selbst gewaehlter Text aktiviert ihn - jede Anfrage, die nicht von
  `127.0.0.1` kommt, muss ihn im Header `X-Control-Token` mitschicken,
  sonst `401`. Dasselbe Token muss auf der Pico-Steuer-Seite (`/control`)
  hinterlegt werden.
