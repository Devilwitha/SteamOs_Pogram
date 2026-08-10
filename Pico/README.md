# Pico

MicroPython-Programm fuer einen **Raspberry Pi Pico W** (WLAN-Chip wird benoetigt).

## Ablauf

1. Beim Start versucht `main.py`, sich mit dem in `wifi_config.json` gespeicherten
   WLAN zu verbinden (bis zu **3 Versuche**, je 10 Sekunden Timeout).
2. Klappt das nicht, oder ist noch keine `wifi_config.json` vorhanden, startet der
   Pico einen eigenen **Access Point** namens `Pico-Setup` (Passwort `picosetup`).
   Verbinde dich mit einem Handy/Laptop mit diesem WLAN und rufe im Browser
   `http://192.168.4.1/` auf. Dort kannst du SSID und Passwort deines
   Heim-WLANs eingeben und speichern. Der Pico startet danach automatisch neu
   und versucht sich erneut zu verbinden.
3. Ist die Verbindung erfolgreich, startet der Pico zwei Server:
   - **TCP-Server (Port 5005):** Antwortet auf jede Anfrage mit `erreichbar`.
     Das SteamOS-Programm nutzt das fuer den periodischen "Ping".
   - **UDP-Discovery-Server (Port 5006):** Antwortet auf `DISCOVER_PICO` mit
     `PICO:<eigene-ip>`, damit SteamOS den Pico automatisch im Netzwerk finden
     kann, ohne die IP von Hand eintragen zu muessen.

## Dateien

| Datei | Zweck |
|---|---|
| `main.py` | Einstiegspunkt, wird beim Booten automatisch ausgefuehrt |
| `wifi_manager.py` | Verbindungsaufbau + Speichern der WLAN-Zugangsdaten |
| `captive_portal.py` | Webseite zur WLAN-Einrichtung im Access-Point-Modus |
| `ping_server.py` | TCP-"erreichbar"-Server + UDP-Discovery-Server |
| `wifi_config.json` | Wird automatisch erzeugt, sobald WLAN-Daten gespeichert wurden |

## Installation auf dem Pico

1. Flashe die aktuelle **MicroPython-Firmware fuer Pico W** (z. B. mit
   [Thonny](https://thonny.org) über *Run > Configure interpreter >
   Install or update firmware*).
2. Kopiere `main.py`, `wifi_manager.py`, `captive_portal.py` und
   `ping_server.py` auf den Pico (z. B. mit Thonny per "Speichern unter" ->
   "Raspberry Pi Pico", oder mit `mpremote`/`rshell`):

   ```
   mpremote cp main.py wifi_manager.py captive_portal.py ping_server.py :
   ```

3. Pico neu starten (Reset-Taste oder Strom trennen/wieder anschliessen).
4. Beim ersten Start ist noch kein WLAN gespeichert -> der Access Point
   `Pico-Setup` erscheint. Damit verbinden und unter `http://192.168.4.1/`
   das Heim-WLAN einrichten.

## Hinweise

- Die Zugangsdaten liegen unverschluesselt als `wifi_config.json` auf dem
  Pico. Das ist fuer ein privates Heimnetzwerk unkritisch, sollte bei
  sensibleren Umgebungen aber beruecksichtigt werden.
- Um das WLAN neu einzurichten, kann `wifi_config.json` einfach vom Pico
  geloescht werden (z. B. mit Thonny) - beim naechsten Start erscheint dann
  wieder der Einrichtungs-Access-Point.
