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

Das Skript kopiert `steamos-pico-monitor.service` nach
`~/.config/systemd/user/`, aktiviert und startet den Dienst und richtet
Linger fuer den aktuellen Benutzer ein.

Status pruefen:

```bash
systemctl --user status steamos-pico-monitor.service
journalctl --user -u steamos-pico-monitor.service -f
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
| `color` | Optionale, in der GUI zugewiesene Farbe (Hex, z. B. `#ff8800`) fuer den [Led_Pico](../Led_Pico) - wird von `game_scanner.py` beim erneuten Scannen **nicht** ueberschrieben |
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
gekapselte Weboberflaeche zur Auswahl eines Spiels aus `games.db`:

```bash
python3 steamOs/gui/gui_server.py
```

Startet einen lokalen Webserver (`http://localhost:8090`, siehe `gui_port`
in `config.json`) und versucht,
ihn automatisch im Standardbrowser zu oeffnen (Desktop-Modus) - klappt das
nicht (z. B. kein Standardbrowser registriert), einfach die Adresse von
Hand im Browser aufrufen. Das HTML liegt in [`gui/index.html`](gui/index.html)
(nicht im Python-Code eingebettet); `gui_server.py` fuellt darin nur die
Platzhalter `__MESSAGE__`/`__ROWS__`/`__TAG_ROWS__`. Angezeigt werden alle
Spiele aus der Datenbank mit Name, Installationsstatus und UID. Klick auf
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

### Farbe pro Spiel/Tag (fuer den Led_Pico)

Sowohl in der Spiele- als auch in der Tag-Tabelle gibt es eine Spalte
"Farbe" mit einem Farbfeld je Zeile - Aenderungen werden sofort
gespeichert (Spiel-Farbe direkt in `games.db`, Tag-Farbe per
`TAGCOLOR:<uid>:<farbe>` auf dem Pico). Eine am Tag gesetzte Farbe hat
Vorrang vor der Farbe des verknuepften Spiels. Beide werden von
`pico_client.py` genutzt, um einen optionalen zweiten Pico (siehe
[../Led_Pico](../Led_Pico)) mit der passenden Farbe fuer einen
LED-Streifen zu versorgen - siehe
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
   oben) und die daraus ermittelte Farbe (Tag-Farbe, sonst Spiel-Farbe,
   sonst aus) an einen optionalen [Led_Pico](../Led_Pico) weitergereicht -
   nur wenn sie sich seit dem letzten Takt geaendert hat.

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
  diesen `SIGTERM`. Das ist ein Best-Effort-Ansatz (kein offizieller
  Steam-Mechanismus) - bei Spielen mit ungewoehnlicher Prozessstruktur
  (z. B. mehrere unabhaengige Prozesse ausserhalb von `install_path`,
  manche Proton-Spiele) kann das Beenden unvollstaendig bleiben.

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
