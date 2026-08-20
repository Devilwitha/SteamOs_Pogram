"""Erkennt laufende Steam-Downloads/-Updates und deren Fortschritt - fuer
das optionale Download-Puls-LED-Feature (siehe pico_client.py,
LED_SETTINGS.download_pulse) sowie den Fortschritts-Zeiger auf dem
Farbverlauf-Balken in GUI/Pico-Steuerseite.

Primaere Quelle ist Steams EIGENE, intern verwendete API: der
steamwebhelper-Prozess (rendert die Steam-UI als eingebettete
Chromium-Seite) exponiert unter 127.0.0.1:8080 das Chrome-DevTools-
Protokoll (CDP) - ueblicherweise fuer Steams eigenes UI-Debugging
gedacht, aber genauso von aussen nutzbar. Ueber die darin enthaltene
"SharedJSContext"-Seite laesst sich SteamClient.Downloads.
RegisterForDownloadOverview() aufrufen, exakt dieselbe JS-API, die auch
Steams eigene Downloads-Seite fuer ihre Prozentanzeige nutzt (inkl.
"overall_percent_complete", einem aus mehreren Phasen - Download,
Staging, Diskschreiben - gewichteten Wert). Das liefert also woertlich
dieselbe Zahl, die der Nutzer in Steam selbst sieht (siehe Chatverlauf:
die dateibasierte Schaetzung unten kam bei "ARC Raiders" auf 3%, waehrend
Steams eigene Anzeige 60-76% zeigte - beides stimmte fuer sich genommen
mit den jeweiligen Rohdaten ueberein, nur eben nicht mit dem, was der
Nutzer tatsaechlich sieht).

_get_download_progress_from_manifests() (dateibasiert, siehe unten)
dient nur noch als Fallback, falls das CDP-Protokoll nicht erreichbar
ist (Steam laeuft nicht, oder der Debug-Port ist in einer anderen
Konfiguration nicht offen) - fuer diesen Fall bleibt die urspruengliche
Herleitung ueber appmanifest_*.acf-Dateien (dieselben Steam-Bibliotheken
wie game_scanner.py, dessen find_steam_root()/find_library_paths() hier
wiederverwendet werden) erhalten.

Steam aktualisiert "BytesDownloaded"/"BytesToDownload" im Manifest eines
Spiels in Echtzeit waehrend ein Download/Update laeuft; beide Felder
fehlen komplett, sobald nichts (mehr) heruntergeladen wird (siehe
Chatverlauf: ein Manifest ohne laufenden Download hat weder das eine noch
das andere Feld). Damit laesst sich ein laufender Download deutlich
robuster erkennen als ueber die kaum dokumentierten StateFlags-Bits.

Wichtig fuer den zurueckgegebenen Fortschritts-Bruch: weder
"BytesDownloaded" noch "SizeOnDisk" ist fuer sich allein zuverlaessig.
"BytesDownloaded" zaehlt nur innerhalb des jeweils aktuellen internen
Segments und wird bei jeder Warteschlangen-Umpriorisierung/
Neuverifizierung wieder auf 0 zurueckgesetzt (haeufig bei Updates
bereits installierter Spiele, wenn mehrere Titel gleichzeitig in der
Warteschlange stehen, siehe Chatverlauf) - obwohl der Titel insgesamt
schon weit fortgeschritten sein kann. "SizeOnDisk" wird zwar nicht
zurueckgesetzt, bleibt bei einer FRISCHEN Installation (noch nichts auf
der Platte) aber bei 0 haengen, bis Steam bereits heruntergeladene Daten
tatsaechlich an ihren endgueltigen Ort "committet" (staged) - waehrend
BytesDownloaded dort korrekt mitzaehlt. Da keines der beiden Signale den
echten Fortschritt jemals UEBERSCHAETZT, sondern je nach Szenario nur
HINTERHERHINKT, wird hier bewusst der jeweils groessere der beiden
Bruchteile verwendet (BytesDownloaded/BytesToDownload vs.
SizeOnDisk/(SizeOnDisk+BytesToDownload)) - das deckt sowohl frische
Installationen als auch Updates bereits installierter Spiele robust ab,
ohne den jeweiligen Fall vorher erkennen zu muessen.

Achtung: "BytesToDownload > BytesDownloaded" allein reicht NICHT aus, um
den gerade aktiv transferierenden Titel zu finden - hat Steam mehrere
Titel in der Warteschlange (z. B. ein Spiel + dessen "Steamworks Common
Redistributables"), tragen auch die noch gar nicht gestarteten,
lediglich vorgemerkten Titel bereits ein befuelltes BytesToDownload bei
BytesDownloaded=0 - und blieben damit dauerhaft bei 0% haengen, wenn man
einfach den ersten Treffer nimmt (siehe Chatverlauf: Farbe aenderte sich
nicht, weil genau so ein wartender 19-MB-Redistributables-Eintrag vor dem
eigentlichen, tatsaechlich aktiven Mehrere-GB-Download gefunden wurde).
Steam legt fuer den gerade aktiv herunterladenden Titel zusaetzlich einen
Ordner steamapps/downloading/<appid>/ an, solange dessen Chunks wirklich
uebertragen werden - nur ein Manifest mit passendem, existierendem
downloading/<appid>/-Ordner gilt hier als aktiv.

is_actively_transferring() nutzt zusaetzlich Steams eigenes
logs/content_log.txt: deutlich feingranularer als appmanifest_*.acf
(schreibt bei jeder Warteschlangen-Umpriorisierung), ABER die darin
geloggten "download X/Y"-Zahlen sind nur ein Zwischenstand des jeweils
aktuellen internen Segments und setzen bei jeder Umpriorisierung auf 0
zurueck - als Quelle fuer den Gesamt-Fortschritt eines Titels also
unbrauchbar/irrefuehrend (siehe Chatverlauf). Nuetzlich ist das Log aber
als reines Aktiv/Pausiert-Signal: hat Steam mehrere Titel gleichzeitig in
der Warteschlange (z. B. mehrere parallel wartende Spiele-Updates),
priorisiert es staendig zwischen ihnen um - pico_client.py nutzt dieses
Signal, um die eigene Fortschritts-Extrapolation waehrend einer solchen
Pause einzufrieren, statt mit der zuletzt bekannten Rate blind
weiterzuschaetzen.
"""
import base64
import json
import os
import re
import socket
import struct
import urllib.error
import urllib.request

import game_scanner
import vdf_parser

_CONTENT_LOG_TAIL_BYTES = 65536
_APPID_EVENT_RE = re.compile(r"AppID (\d+) update (started|canceled)")

# steamwebhelper's CDP-Port - siehe Moduldocstring. Fest auf 8080 (der
# Standard auf SteamOS/Bazzite, siehe Chatverlauf) statt dynamisch
# ermittelt, da das nur der bequeme, nicht der einzig moegliche Weg an
# die Daten ist - schlaegt die Verbindung fehl, greift der dateibasierte
# Fallback ohnehin.
_CDP_HOST = "127.0.0.1"
_CDP_PORT = 8080
_CDP_CONNECT_TIMEOUT = 1.0
_CDP_CALLBACK_TIMEOUT_MS = 1500


def _cdp_find_shared_js_context():
    try:
        with urllib.request.urlopen(
            f"http://{_CDP_HOST}:{_CDP_PORT}/json", timeout=_CDP_CONNECT_TIMEOUT
        ) as resp:
            targets = json.loads(resp.read())
    except (OSError, urllib.error.URLError, ValueError):
        return None

    for target in targets:
        if target.get("title") == "SharedJSContext":
            return target.get("webSocketDebuggerUrl")
    return None


def _cdp_ws_connect(ws_url):
    # ws://127.0.0.1:8080/devtools/page/<id> - Host/Port sind hier immer
    # _CDP_HOST/_CDP_PORT (kommen aus derselben /json-Antwort), nur der Pfad
    # wird gebraucht.
    path = ws_url.split(_CDP_HOST, 1)[1].split(":", 1)[1].split("/", 1)[1]
    path = "/" + path

    sock = socket.create_connection((_CDP_HOST, _CDP_PORT), timeout=_CDP_CONNECT_TIMEOUT)
    sock.settimeout(_CDP_CALLBACK_TIMEOUT_MS / 1000 + 1.0)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {_CDP_HOST}:{_CDP_PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("CDP-Handshake abgebrochen")
        response += chunk
    if b"101" not in response.split(b"\r\n", 1)[0]:
        raise OSError("CDP-Handshake fehlgeschlagen")
    return sock


def _cdp_ws_send_json(sock, payload):
    data = json.dumps(payload).encode()
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    mask_key = os.urandom(4)
    header += mask_key
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + masked)


def _cdp_evaluate(sock, expression):
    """Sendet Runtime.evaluate an die CDP-Websocket-Verbindung und liest
    Frames, bis die Antwort mit passender id ankommt (andere,
    zwischendurch eintreffende CDP-Events werden ignoriert)."""
    request_id = 1
    _cdp_ws_send_json(
        sock,
        {
            "id": request_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        },
    )

    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buf += chunk
        while True:
            frame, buf = _cdp_ws_extract_frame(buf)
            if frame is None:
                break
            try:
                data = json.loads(frame)
            except ValueError:
                continue
            if data.get("id") == request_id:
                result = data.get("result", {}).get("result", {})
                return result.get("value")


def _cdp_ws_extract_frame(buf):
    """Extrahiert genau einen unmaskierten WebSocket-Textframe vom Anfang
    von buf. Gibt (payload_str, rest) zurueck, oder (None, buf), wenn noch
    nicht genug Daten fuer einen vollstaendigen Frame da sind."""
    if len(buf) < 2:
        return None, buf
    b2 = buf[1]
    masked = b2 & 0x80
    length = b2 & 0x7F
    idx = 2
    if length == 126:
        if len(buf) < 4:
            return None, buf
        length = struct.unpack(">H", buf[2:4])[0]
        idx = 4
    elif length == 127:
        if len(buf) < 10:
            return None, buf
        length = struct.unpack(">Q", buf[2:10])[0]
        idx = 10
    if masked:
        idx += 4
    if len(buf) < idx + length:
        return None, buf
    payload = buf[idx: idx + length]
    if masked:
        mask_key = buf[idx - 4: idx]
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return payload.decode(errors="replace"), buf[idx + length:]


def _steamapps_dirs():
    """Alle steamapps/-Ordner ueber saemtliche Steam-Bibliotheken hinweg
    (siehe game_scanner.find_library_paths()) - Basis fuer
    _has_downloading_dir() unten, von beiden Erkennungspfaden
    (CDP/Steam-UI und dateibasierter Fallback) gemeinsam genutzt."""
    steam_root = game_scanner.find_steam_root()
    if steam_root is None:
        return []
    return [
        lp / "steamapps"
        for lp in game_scanner.find_library_paths(steam_root)
        if (lp / "steamapps").is_dir()
    ]


def _has_downloading_dir(steamapps_dirs, appid):
    """True, solange Steam fuer appid noch tatsaechlich einen
    steamapps/downloading/<appid>/-Ordner offen haelt - existiert laut
    Steam nur genau so lange, wie fuer diesen Titel noch etwas zu tun ist
    (Download/Staging/Commit), siehe Moduldocstring."""
    return any((d / "downloading" / str(appid)).is_dir() for d in steamapps_dirs)


def _get_download_progress_from_steam_ui():
    """Fragt SteamClient.Downloads.RegisterForDownloadOverview() live ueber
    steamwebhelpers CDP-Port ab (siehe Moduldocstring) - liefert (appid,
    fortschritt) mit fortschritt = overall_percent_complete/100, exakt wie
    in Steams eigener Downloads-Seite. None, wenn Steam/der Debug-Port
    nicht erreichbar ist, kein Download laeuft, oder irgendein Schritt
    fehlschlaegt (robust gegenueber allen Netzwerk-/Protokollfehlern, da
    dies nur ein optionaler, bevorzugter Pfad vor dem dateibasierten
    Fallback ist).

    Zusaetzlich gegen Steams eigenen steamapps/downloading/<appid>/-Ordner
    abgesichert (siehe _has_downloading_dir()): Steams "Download-Overview"
    im CDP haelt die zuletzt bekannten Werte teils noch eine Weile fest,
    NACHDEM ein Download bereits fertig ist (kein neues Event, also kein
    Grund fuer Steam, den alten Stand zu verwerfen) - ohne diesen Check
    wuerde das Download-Pulsieren (siehe pico_client.py) dauerhaft auf der
    100%-Verlauffarbe haengen bleiben, statt zur Leerlauf-Farbe
    zurueckzukehren, sobald tatsaechlich nichts mehr laeuft."""
    ws_url = _cdp_find_shared_js_context()
    if ws_url is None:
        return None

    expression = (
        "new Promise(resolve => {"
        "  let done = false;"
        "  const reg = SteamClient.Downloads.RegisterForDownloadOverview(d => {"
        "    if (!done) { done = true; reg.unregister(); resolve(d); }"
        "  });"
        f"  setTimeout(() => {{ if (!done) {{ done = true; reg.unregister(); resolve(null); }} }}, {_CDP_CALLBACK_TIMEOUT_MS});"
        "})"
    )

    try:
        sock = _cdp_ws_connect(ws_url)
    except (OSError, socket.timeout, ValueError, IndexError):
        return None

    try:
        result = _cdp_evaluate(sock, expression)
    except (OSError, socket.timeout):
        return None
    finally:
        sock.close()

    if not result:
        return None

    appid = result.get("update_appid")
    percent = result.get("overall_percent_complete")
    if not appid or percent is None:
        return None
    appid = int(appid)

    if not _has_downloading_dir(_steamapps_dirs(), appid):
        return None

    return appid, max(0.0, min(1.0, percent / 100.0))


def get_download_progress():
    """Oeffentlicher Einstiegspunkt: bevorzugt die live von Steams eigener
    UI-API abgefragten Werte (_get_download_progress_from_steam_ui(), siehe
    Moduldocstring) und faellt nur zurueck auf die dateibasierte Schaetzung
    (_get_download_progress_from_manifests()), wenn Steams CDP-Port nicht
    erreichbar ist."""
    result = _get_download_progress_from_steam_ui()
    if result is not None:
        return result
    return _get_download_progress_from_manifests()


def _get_download_progress_from_manifests():
    """Durchsucht alle Steam-Bibliotheken nach Titeln mit einem gerade
    vorgemerkten Download/Update (BytesToDownload>0 und ein passender
    downloading/<appid>/-Ordner, siehe Moduldocstring). Gibt (appid,
    fortschritt) zurueck, wobei fortschritt ein float zwischen 0.0 und 1.0
    ist - oder None, wenn Steam aktuell nichts herunterlaedt (bzw. keine
    Steam-Installation gefunden wurde).

    Stehen mehrere Titel gleichzeitig in der Warteschlange (siehe
    Chatverlauf - keine Seltenheit, wenn mehrere Spiele-Updates
    zusammenkommen), erfuellen oft mehrere davon gleichzeitig obiges
    Kriterium, obwohl Steam intern immer nur einen davon wirklich aktiv
    ueberbertraegt. Unter den Kandidaten wird deshalb bevorzugt der von
    is_actively_transferring() bestaetigt aktive zurueckgegeben - sonst
    (kein eindeutiger Befund moeglich, z. B. Log noch leer) faellt es auf
    den ersten gefundenen Kandidaten zurueck.

    Der downloading/<appid>/-Ordner wird bewusst ueber ALLE Bibliotheken
    gesucht, nicht nur in der Bibliothek des jeweiligen Manifests - Steam
    kann ihn (z. B. nach einem "Installationsordner verschieben" oder als
    Zwischenstand beim Umverteilen ueber mehrere Laufwerke) auf einer
    anderen Bibliothek als der eigentlichen Installation liegen lassen
    (siehe Chatverlauf: Halos Ordner lag auf der SSD-Bibliothek, obwohl
    das Manifest/die Installation auf dem internen Laufwerk liegt - ohne
    diesen bibliotheksuebergreifenden Check waere Halo faelschlich nie als
    Kandidat erkannt worden)."""
    steamapps_dirs = _steamapps_dirs()
    if not steamapps_dirs:
        return None

    candidates = []
    for steamapps_dir in steamapps_dirs:
        for manifest_path in steamapps_dir.glob("appmanifest_*.acf"):
            try:
                data = vdf_parser.load(manifest_path)
            except (OSError, ValueError):
                continue

            app_state = data.get("AppState")
            if not app_state:
                continue

            try:
                to_download = int(app_state.get("BytesToDownload", 0))
                downloaded = int(app_state.get("BytesDownloaded", 0))
                size_on_disk = int(app_state.get("SizeOnDisk", 0))
                appid = int(app_state.get("appid", 0))
            except (TypeError, ValueError):
                continue

            if to_download <= 0:
                continue
            if not _has_downloading_dir(steamapps_dirs, appid):
                continue

            # downloaded kann >= to_download sein, wenn der Netzwerk-Download
            # bereits fertig ist, Steam aber noch dabei ist, die Dateien aus
            # dem downloading/<appid>/-Ordner an ihren endgueltigen Ort zu
            # "committen" (siehe Chatverlauf: Nutzer beobachtete "Halo
            # installiert noch", waehrend BytesDownloaded==BytesToDownload
            # war) - der downloading/-Ordner existiert genau so lange, wie
            # noch etwas zu tun ist, also hier auf 1.0 deckeln statt
            # komplett auszuschliessen.
            downloaded_fraction = min(1.0, downloaded / to_download)
            disk_fraction = size_on_disk / (size_on_disk + to_download) if size_on_disk > 0 else 0.0
            candidates.append((appid, max(downloaded_fraction, disk_fraction)))

    if not candidates:
        return None

    for appid, fraction in candidates:
        if is_actively_transferring(appid):
            return appid, fraction

    return candidates[0]


def is_actively_transferring(appid):
    """Prueft anhand der juengsten "AppID <appid> update started/canceled"-
    Zeile in logs/content_log.txt, ob Steam appid gerade tatsaechlich
    bearbeitet oder zugunsten eines anderen wartenden Downloads pausiert
    hat (siehe Moduldocstring). True/False bei eindeutigem Befund, None
    wenn das Log nicht lesbar ist oder appid darin (noch) nicht auftaucht
    - dann wird von "aktiv" ausgegangen, um das bisherige Verhalten nicht
    zu veraendern."""
    steam_root = game_scanner.find_steam_root()
    if steam_root is None:
        return None

    log_path = steam_root / "logs" / "content_log.txt"
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            f.seek(max(0, size - _CONTENT_LOG_TAIL_BYTES))
            data = f.read()
    except OSError:
        return None

    lines = data.decode("utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        match = _APPID_EVENT_RE.search(line)
        if not match or int(match.group(1)) != appid:
            continue
        return match.group(2) == "started"

    return None
