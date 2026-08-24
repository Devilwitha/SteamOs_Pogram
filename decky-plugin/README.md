# SteamOS Konsole - Decky-Plugin

Zeigt dieselben Einstellungen wie `native_console.py`/`dashboard.html`
(LEDs, Sound, Spiele, Tags, Werkzeuge, Info) direkt im
Quick-Access-Menu (der "..."-Button) von Big Picture bzw. im Steam-Client
allgemein an - jederzeit erreichbar, auch waehrend ein Spiel laeuft, ohne
einen eigenen Bibliothekseintrag zu starten.

Steams eigene Settings-Panels selbst (Account/Controller/Interface/...)
lassen sich nicht erweitern - dafuer gibt es keine offizielle
Plugin-Schnittstelle. Das Quick-Access-Menu ist der naechstbeste,
tatsaechlich unterstuetzte Weg, eigene UI "in" Steams Oberflaeche
einzubinden (via [Decky Loader](https://decky.xyz/)).

## Architektur

Reiner zusaetzlicher Client fuer das bereits laufende Backend - **kein
Server-seitiger Code wird dafuer veraendert**:

```
Quick-Access-Menu (React/TSX, src/index.tsx)
        |  callPluginMethod("api_get" / "api_post")
        v
Decky-Plugin-Backend (Python, main.py)
        |  HTTP zu 127.0.0.1:8090
        v
steamOs/gui/gui_server.py  (steamos-gui.service, unveraendert)
```

`main.py` ist ein reiner Proxy (siehe `GUI_PORT`/`BASE_URL` darin - Standard
`8090`, wie `steamOs/config.json`s `gui_port`; bei einem abweichenden Port
dort anpassen). Die eigentliche Menue-Logik in `src/index.tsx` ist ein
1:1-Port von `steamOs/gui/native_console.py` (gleiche Kategorien, gleiche
Zeilen-Typen, gleiche `/api/*`-Routen aus `gui_server.py::API_ROUTES`).

## Voraussetzungen zum Bauen

- [Decky Loader](https://decky.xyz/) muss auf dem Geraet installiert sein
  (bereits der Fall, erkennbar an `~/homebrew/`).
- Node.js (>=18) und [pnpm](https://pnpm.io/) - auf diesem Geraet noch
  nicht installiert, z. B. via:
  ```bash
  # Node ueber die offizielle nvm-Installation, dann:
  corepack enable
  corepack prepare pnpm@latest --activate
  ```
- `steamos-gui.service` muss laufen (liefert die eigentlichen Daten unter
  `127.0.0.1:8090`), sonst zeigt das Plugin dauerhaft "Verbinde mit
  steamos-gui.service...".

## Bauen

```bash
cd decky-plugin
pnpm install
pnpm run build
```

Erzeugt `dist/index.js`.

## Installieren

Decky-Plugins liegen unter `~/homebrew/plugins/<Name>/` (root-Besitz,
von Decky Loader selbst verwaltet). Drei Wege:

**A) Als ZIP (empfohlen):**
```bash
./build_zip.sh
```
Baut bei Bedarf zuerst `pnpm run build` und erzeugt danach
`release/SteamOS-Konsole-<Version>.zip` - fertig zum Installieren ueber
das Decky-Loader-Menu (Quick-Access-Menu -> Decky-Icon -> Einstellungen
-> Entwickler -> "Install Plugin from ZIP" bzw. je nach Version direkt
per Datei-Auswahl-Dialog dort). Alternativ die ZIP manuell nach
`~/homebrew/plugins/` entpacken (siehe Ausgabe des Skripts).

Zum Bauen auf einem Windows-PC (z. B. weil Node.js/pnpm nicht auf dem
Steam Deck installiert werden sollen) gibt es `build_zip.bat` - installiert
bei Bedarf zusaetzlich Node.js (ueber `winget`) und pnpm (ueber `corepack`,
kommt mit Node.js) und baut danach dieselbe ZIP. Installiert wird das
Plugin trotzdem nur auf dem Steam Deck (ZIP rueberkopieren, siehe oben).

**B) Ueber den Decky-Loader-Entwicklermodus (zum Testen mit Live-Reload):**
Im Decky-Loader-Menu unter "Einstellungen -> Entwickler" den
Entwicklermodus aktivieren, dort laesst sich ein Plugin direkt aus einem
lokalen Ordner laden/neu laden, ohne manuell nach `~/homebrew/plugins/`
kopieren zu muessen.

**C) Manuell, ohne ZIP:**
```bash
sudo mkdir -p ~/homebrew/plugins/SteamOS-Konsole
sudo cp -r plugin.json main.py dist ~/homebrew/plugins/SteamOS-Konsole/
```
Nach A oder C: Decky Loader neu laden (oder Steam neu starten) - das
Plugin erscheint im Quick-Access-Menu.

## Warum ein Python-Backend-Proxy statt direktem `fetch()` aus dem Frontend?

Das Frontend laeuft im CEF-Kontext des Steam-Clients selbst, nicht in
einer normalen Sandbox-Webseite - `fetch()` zu `127.0.0.1` waere hier
vermutlich auch direkt moeglich. Der von Decky Loader dokumentierte,
zuverlaessige Weg, mit einem lokalen Dienst zu sprechen, ist aber der
Umweg ueber eine Backend-Methode (`callPluginMethod`) - das vermeidet
jedes Risiko von CORS/CSP-Einschraenkungen und ist das Muster, das auch
andere Decky-Plugins fuer aehnliche Faelle verwenden.

## Verhaeltnis zu den anderen beiden Oberflaechen

Alle drei sprechen dieselbe `/api/*`-JSON-API von `gui_server.py` und
bleiben unabhaengig nutzbar:

- `dashboard.html` (`/`, `/admin`) - Browser-/Maus-Zugriff, z. B. vom
  Handy im selben Netz.
- `native_console.py` (`launch_dashboard.py`) - eigener
  Nicht-Steam-Bibliothekseintrag "SteamOS Konsole", volle
  Controller-Navigation ueber SDL2, nuetzlich wenn man die Einstellungen
  als eigenstaendige "App" oeffnen will.
- Dieses Decky-Plugin - dieselben Einstellungen direkt im
  Quick-Access-Menu, ohne die Bibliothek zu verlassen oder ein laufendes
  Spiel zu unterbrechen.
