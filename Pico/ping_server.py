"""TCP-Steuer-Server + HTTP-Statuswebseite (status_server.py), sowie ein
UDP-Discovery-Server, damit SteamOS den Pico im Netzwerk automatisch
findet.

Der Pico hat nur einen einzigen zweiten Kern, den MicroPythons `_thread`
fuer genau einen zusaetzlichen Thread nutzen kann - ein zweiter eigener
Thread wuerde mit `OSError: core1 in use` fehlschlagen. Deshalb:
- TCP-Steuer-Server (Port 5005) und HTTP-Statusserver (Port 80) laufen
  ueber `select()` gemeinsam im Hauptthread (_serve).
- UDP-Discovery-Server und RFID-Polling (tag_manager.poll_once()) laufen
  zusammen im einen verfuegbaren Hintergrund-Thread (_background_loop).

Zeilenbasiertes Protokoll ueber TCP (Port 5005):
    PING                    -> "erreichbar"
    SELECT:<uid>[:<name>]   -> UID wird in SELECTED_GAME_FILE gespeichert
                          und zum Verknuepfen mit dem naechsten
                          aufgelegten Tag vorgemerkt (siehe
                          tag_manager.py); der optionale Anzeigename wird
                          fuers LCD mitgespeichert; Antwort "OK:<uid>"
                          bestaetigt den Empfang
    TAG?              -> "TAG:<uid>", falls ein Tag mit einer neuen/noch
                          nicht bestaetigten Spiel-UID aufliegt, sonst
                          "TAG:NONE"
    STARTED:<uid>     -> SteamOS bestaetigt, dass das Spiel mit dieser UID
                          gestartet wurde; Antwort "OK:STARTED:<uid>",
                          oder "ERROR:mismatch" falls der Tag inzwischen
                          gewechselt hat
    TAGS?             -> "TAGS:<json-liste>" aller bisher erkannten Tags
                          mit ihrer (ggf. fehlenden) Spiel-Verknuepfung
                          (inkl. Anzeigename) und eigenen Farbe
    LINK:<uid>:<game>[:<name>] -> verknuepft einen bereits bekannten Tag
                          direkt (ohne erneutes Auflegen) mit einer
                          Spiel-UID (game leer = Verknuepfung aufheben);
                          Antwort "OK:LINK:<uid>" oder "ERROR:unknown_tag"
    TAGCOLOR:<uid>:<f> -> setzt die eigene LED-Farbe eines bereits
                          bekannten Tags (f leer = Farbe loeschen);
                          Antwort "OK:TAGCOLOR:<uid>" oder
                          "ERROR:unknown_tag"
    CURRENT?          -> "CURRENT:<json>" mit dem gerade aufliegenden Tag
                          (uid/game_uid/game_name/color), unabhaengig vom
                          einmaligen TAG?-Meldezustand - oder
                          "CURRENT:NONE"; genutzt, um den Led_Pico
                          kontinuierlich mit der passenden Farbe zu
                          versorgen (siehe ../Led_Pico)

HTTP (Port 80): "/" liefert die Statusseite (dark/modern), "/status.json"
den aktuellen Status inkl. Tag-Liste als JSON.

Ist ein LCD angeschlossen (siehe main.py/i2c_lcd.py), zeigt es laufend den
aktuellen Tag-Zustand an (aktualisiert im Hintergrund-Thread direkt nach
jedem tag_manager.poll_once(), siehe _background_loop): verknuepftes Spiel
(Name falls bekannt, sonst die Spiel-UID), "Unbekannter Tag" bei einer
noch nicht verknuepften Karte, oder der Bereitschafts-Bildschirm
("Pico bereit" + IP), solange keine Karte aufliegt.
"""
import socket
import select
import time
import _thread
import machine
import network
import ujson as json

import tag_manager
import status_server

TCP_PORT = 5005
HTTP_PORT = 80
UDP_PORT = 5006
DISCOVERY_MESSAGE = b"DISCOVER_PICO"
SELECTED_GAME_FILE = "selected_game.txt"

# Wie oft (ms) im Hintergrund-Thread geprueft wird, ob die WLAN-Verbindung
# noch steht. Ist sie weg, startet der Pico neu, um ueber die robuste
# Boot-Logik in wlan.py (mehrere Verbindungsversuche, danach
# Hotspot-Fallback) automatisch wieder eine Verbindung herzustellen -
# ohne diese Pruefung wuerde ein waehrend des Betriebs (nicht beim Booten)
# auftretender WLAN-Ausfall unbemerkt bleiben und der Pico unerreichbar
# haengen bleiben.
WLAN_CHECK_INTERVAL_MS = 30_000


def _handle_command(command):
    command = command.strip()

    if command == "PING":
        return "erreichbar"

    if command.startswith("SELECT:"):
        payload = command[len("SELECT:"):]
        parts = payload.split(":", 1)
        uid = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        if not uid:
            return "ERROR:empty_uid"
        try:
            with open(SELECTED_GAME_FILE, "w") as f:
                f.write(uid)
        except OSError:
            return "ERROR:write_failed"
        tag_manager.request_write(uid, name)
        return "OK:" + uid

    if command == "TAG?":
        uid = tag_manager.get_tag_status()
        return "TAG:" + uid if uid else "TAG:NONE"

    if command.startswith("STARTED:"):
        uid = command[len("STARTED:"):].strip()
        if tag_manager.confirm_started(uid):
            return "OK:STARTED:" + uid
        return "ERROR:mismatch"

    if command == "TAGS?":
        return "TAGS:" + json.dumps(tag_manager.list_tags())

    if command.startswith("LINK:"):
        rest = command[len("LINK:"):]
        if ":" not in rest:
            return "ERROR:bad_format"
        parts = rest.split(":", 2)
        uid_hex = parts[0].strip()
        game_uid = parts[1].strip() if len(parts) > 1 else ""
        name = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
        if tag_manager.link_existing(uid_hex, game_uid, name):
            return "OK:LINK:" + uid_hex
        return "ERROR:unknown_tag"

    if command.startswith("TAGCOLOR:"):
        rest = command[len("TAGCOLOR:"):]
        if ":" not in rest:
            return "ERROR:bad_format"
        uid_hex, color = rest.split(":", 1)
        uid_hex = uid_hex.strip()
        color = color.strip()
        if tag_manager.set_color(uid_hex, color):
            return "OK:TAGCOLOR:" + uid_hex
        return "ERROR:unknown_tag"

    if command == "CURRENT?":
        current = tag_manager.get_current()
        return "CURRENT:" + json.dumps(current) if current else "CURRENT:NONE"

    return "ERROR:unknown_command"


def _lcd_write(lcd, zeile1, zeile2=""):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.putstr(zeile1[:16])
        if zeile2:
            lcd.move_to(0, 1)
            lcd.putstr(zeile2[:16])
    except Exception as e:
        print("LCD-Fehler:", e)


def _lcd_status_text(current, my_ip):
    """Ermittelt (zeile1, zeile2) fuers LCD aus dem aktuell aufliegenden
    Tag (siehe tag_manager.get_current()). Liegt keine Karte auf, wird
    der Bereitschafts-Bildschirm angezeigt - so bleibt das LCD auch im
    Leerlauf sinnvoll belegt statt beim letzten Zufallszustand zu bleiben."""
    if current is None:
        return "Pico bereit", my_ip

    game_uid = current.get("game_uid")
    game_name = current.get("game_name")

    if not game_uid:
        return "Unbekannter Tag", "UID:" + (current.get("uid") or "")

    if game_name:
        return game_name, "Tag erkannt"

    return "Spiel verknuepft", "UID:" + game_uid


def _read_line(cl, max_len=256):
    data = b""
    while not data.endswith(b"\n") and len(data) < max_len:
        chunk = cl.recv(64)
        if not chunk:
            break
        data += chunk
    return data.decode().strip()


def _handle_tcp_client(cl):
    try:
        cl.settimeout(3)
        command = _read_line(cl)
        if command:
            response = _handle_command(command)
            print("Befehl:", command, "-> Antwort:", response)
            cl.send((response + "\n").encode())
    except Exception as e:
        print("TCP-Fehler:", e)
    finally:
        cl.close()


def _handle_http_client(cl, my_ip, hostname):
    try:
        cl.settimeout(3)
        # Bis zum Ende der Header (\r\n\r\n) lesen und damit verwerfen, nicht
        # nur bis zur ersten Zeile - echte Browser schicken deutlich mehr
        # Header (User-Agent, Accept-*, Sec-Fetch-*, ...) als z.B. urllib.
        # Bleiben ungelesene Daten im Socket-Puffer, wenn cl.close() unten
        # aufgerufen wird, schickt der TCP-Stack oft ein RST statt eines
        # sauberen FIN - der Browser verwirft dann die bereits gesendete
        # Antwort komplett (Symptom: leere/graue Seite trotz "erfolgreichem"
        # Senden auf Pico-Seite).
        request = b""
        while b"\r\n\r\n" not in request and len(request) < 4096:
            chunk = cl.recv(512)
            if not chunk:
                break
            request += chunk
        request_line = request.split(b"\r\n", 1)[0].decode()
        print("HTTP-Anfrage:", request_line)
        status_server.handle(cl, request_line, my_ip, hostname)
        print("HTTP-Antwort gesendet")
    except Exception as e:
        print("HTTP-Fehler:", e)
    finally:
        cl.close()


def _serve(my_ip, hostname):
    tcp = socket.socket()
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(socket.getaddrinfo("0.0.0.0", TCP_PORT)[0][-1])
    tcp.listen(4)

    http = socket.socket()
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(socket.getaddrinfo("0.0.0.0", HTTP_PORT)[0][-1])
    http.listen(4)

    print("Steuer-Server (TCP", TCP_PORT, ") und Status-Webseite (HTTP", HTTP_PORT, ") laufen")

    while True:
        readable, _w, _e = select.select([tcp, http], [], [], 1.0)
        for s in readable:
            if s is tcp:
                cl, _addr = tcp.accept()
                _handle_tcp_client(cl)
            else:
                cl, _addr = http.accept()
                _handle_http_client(cl, my_ip, hostname)


def _background_loop(my_ip, lcd=None):
    """Laeuft im einzigen verfuegbaren Hintergrund-Thread: beantwortet
    UDP-Discovery-Anfragen, ruft dazwischen regelmaessig
    tag_manager.poll_once() auf, aktualisiert danach bei Bedarf das LCD
    (siehe _lcd_status_text) und prueft von Zeit zu Zeit, ob die
    WLAN-Verbindung noch steht (siehe WLAN_CHECK_INTERVAL_MS)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", UDP_PORT))
    s.settimeout(0.05)
    print("Discovery-Server laeuft auf Port", UDP_PORT)

    sta = network.WLAN(network.STA_IF)
    last_poll = time.ticks_ms()
    last_wlan_check = time.ticks_ms()
    last_lcd_state = "unset"
    while True:
        try:
            data, addr = s.recvfrom(64)
            if data == DISCOVERY_MESSAGE:
                s.sendto(("PICO:" + my_ip).encode(), addr)
        except OSError:
            pass

        now = time.ticks_ms()
        if time.ticks_diff(now, last_poll) >= tag_manager.POLL_INTERVAL_MS:
            tag_manager.poll_once()
            last_poll = now

            if lcd is not None:
                current = tag_manager.get_current()
                state = (
                    (current.get("uid"), current.get("game_uid"), current.get("game_name"))
                    if current
                    else None
                )
                if state != last_lcd_state:
                    zeile1, zeile2 = _lcd_status_text(current, my_ip)
                    _lcd_write(lcd, zeile1, zeile2)
                    last_lcd_state = state

        if time.ticks_diff(now, last_wlan_check) >= WLAN_CHECK_INTERVAL_MS:
            last_wlan_check = now
            if not sta.isconnected():
                print("WLAN-Verbindung verloren - starte neu, um erneut zu verbinden...")
                machine.reset()


def start(my_ip, hostname="", lcd=None):
    """Startet den kombinierten Discovery-/RFID-Hintergrund-Thread (der bei
    vorhandenem LCD auch dessen Anzeige aktuell haelt) und danach
    TCP-Steuer-Server + HTTP-Statusserver (blockierend im aufrufenden
    Thread)."""
    _thread.start_new_thread(_background_loop, (my_ip, lcd))
    _serve(my_ip, hostname)
