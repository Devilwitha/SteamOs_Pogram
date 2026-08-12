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

Startet einen lokalen Webserver (`http://localhost:8080`) und versucht,
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
  "interval_seconds": 3
}
```

- `pico_ip`: Optional. Leer lassen fuer automatische Suche im Netzwerk, oder
  eine feste IP eintragen, falls UDP-Broadcasts in deinem Netzwerk
  blockiert werden.
- `tcp_port` / `udp_port`: Muessen mit den Ports in `Pico/ping_server.py`
  uebereinstimmen (Standard 5005 / 5006).
- `interval_seconds`: Wie oft (in Sekunden) angefragt wird.
