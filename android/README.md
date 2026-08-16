# BolliSoft Game Station Link (Android)

Native Android-App (Kotlin + Jetpack Compose) fuer die Steuerung von
[`steamOs/gui/gui_server.py`](../steamOs/gui/gui_server.py) - dasselbe, was im Browser unter
`http://<pc-ip>:8090/` (Controller-Menue) bzw. `/admin` (Verwaltungs-GUI) laeuft. Die App
spricht dabei genau dieselben JSON-Routen (`/api/state`, `/api/...`) an wie
[`Pico/control.html`](../Pico/control.html), das den Server ebenfalls fernsteuert - keine
eigene Logik, kein WebView, nur ein weiterer Client derselben API.

## Aufbau

Drei Bereiche (unten in der App per Navigationsleiste erreichbar):

- **Konsole** - 1:1-Pendant zu `steamOs/gui/dashboard.html`: LEDs, Sound, Spiele, Tags,
  Werkzeuge, Info als Kategorien.
- **Verwaltung** - 1:1-Pendant zu `steamOs/gui/index.html` (`/admin`) bzw.
  `Pico/control.html`: volle Spiele-/Tag-Tabelle inkl. Sound-Uploads je Spiel sowie
  Boot-Sound-/Video-Upload - die Konsole bietet bewusst keine Uploads an, genau wie im
  Web-Original.
- **Verbindung** - PC-IP, Port (Standard `8090`) und Token, analog zur
  "Verbindung zum PC"-Karte in `Pico/control.html`. Wird lokal auf dem Geraet gespeichert
  (Jetpack DataStore).

## Voraussetzungen auf dem PC

Damit die App zugreifen darf, muss `steamOs/config.json` (siehe
[steamOs/README.md](../steamOs/README.md)) Folgendes enthalten:

```json
{
  "gui_bind": "0.0.0.0",
  "remote_control_token": "<ein-langes-zufaelliges-token>"
}
```

`gui_bind` oeffnet `gui_server.py` fuers LAN (Standard ist nur `127.0.0.1`), das Token ist
Pflicht fuer jede Anfrage, die nicht von `127.0.0.1` kommt - siehe
`Handler._is_authorized` in `gui_server.py`. Ohne Token bleibt Fernzugriff komplett gesperrt.

> **Hinweis:** Die im Repo eingecheckte `steamOs/config.json` enthaelt aktuell bereits ein
> Token. Da diese Datei mit ins Git-Repository eingecheckt wird, sollte dieses Token als
> kompromittiert gelten - vor dem produktiven Einsatz ein neues, zufaelliges Token setzen
> und `steamOs/config.json` idealerweise aus der Versionskontrolle nehmen (`.gitignore`).

## Bauen

Das Projekt ist ein normales Gradle/Android-Projekt (Kotlin 1.9.24, AGP 8.4.2,
Compose BOM 2024.06.00, `minSdk 26`, `compileSdk`/`targetSdk 34`).

1. In Android Studio: **File > Open** und diesen `android/`-Ordner auswaehlen.
2. Der Gradle-Wrapper-JAR ist bewusst nicht mit eingecheckt (Binärdatei). Android Studio
   bietet beim ersten Sync an, ihn automatisch zu ergaenzen ("Gradle wrapper is not fully
   set up" -> "OK"). Alternativ lokal einmalig
   ```
   gradle wrapper --gradle-version 8.7
   ```
   im `android/`-Ordner ausfuehren (braucht eine lokale Gradle-Installation).
3. Sync + Run auf einem Geraet/Emulator im selben WLAN wie der PC.

## Warum Klartext-HTTP?

`gui_server.py` spricht bewusst nur HTTP im lokalen Netz (kein TLS-Zertifikat fuer eine
LAN-IP sinnvoll verwaltbar) - die App erlaubt deshalb `usesCleartextTraffic="true"` im
Manifest, genau wie `Pico/control.html` das im Browser ebenfalls nur per Klartext-`fetch()`
tut.
