# steamOs

Hintergrundprogramm fuer den **Steam Deck / SteamOS**, das den [Pico](../Pico)
im Netzwerk ueberwacht - auch waehrend Steam im **Game Mode** laeuft.

## Funktionsweise

`pico_client.py` laeuft in einer Endlosschleife und sendet alle
`interval_seconds` (Standard: 3 Sekunden) eine Anfrage an den Pico:

- Ist die IP des Pico noch nicht bekannt, wird sie per UDP-Broadcast
  automatisch im lokalen Netzwerk gesucht (`DISCOVER_PICO`).
- Danach wird per TCP `ping` an den Pico geschickt; antwortet er mit
  `erreichbar`, wird das geloggt und in `state.json` festgehalten.
- Antwortet der Pico nicht mehr, wird die gespeicherte IP verworfen und beim
  naechsten Durchlauf erneut gesucht.

Alle Ausgaben landen im systemd-Journal (`journalctl`), der aktuelle Status
zusaetzlich in `state.json` neben dem Skript, falls andere Programme ihn
auslesen wollen.

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
