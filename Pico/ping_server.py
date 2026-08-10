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
    PING              -> "erreichbar"
    SELECT:<uid>      -> UID wird in SELECTED_GAME_FILE gespeichert und
                          zum Verknuepfen mit dem naechsten aufgelegten
                          Tag vorgemerkt (siehe tag_manager.py);
                          Antwort "OK:<uid>" bestaetigt den Empfang
    TAG?              -> "TAG:<uid>", falls ein Tag mit einer neuen/noch
                          nicht bestaetigten Spiel-UID aufliegt, sonst
                          "TAG:NONE"
    STARTED:<uid>     -> SteamOS bestaetigt, dass das Spiel mit dieser UID
                          gestartet wurde; Antwort "OK:STARTED:<uid>",
                          oder "ERROR:mismatch" falls der Tag inzwischen
                          gewechselt hat
    TAGS?             -> "TAGS:<json-liste>" aller bisher erkannten Tags
                          mit ihrer (ggf. fehlenden) Spiel-Verknuepfung
    LINK:<uid>:<game>  -> verknuepft einen bereits bekannten Tag direkt
                          (ohne erneutes Auflegen) mit einer Spiel-UID
                          (game leer = Verknuepfung aufheben); Antwort
                          "OK:LINK:<uid>" oder "ERROR:unknown_tag"

HTTP (Port 80): "/" liefert die Statusseite (dark/modern), "/status.json"
den aktuellen Status inkl. Tag-Liste als JSON.
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
        uid = command[len("SELECT:"):].strip()
        if not uid:
            return "ERROR:empty_uid"
        try:
            with open(SELECTED_GAME_FILE, "w") as f:
                f.write(uid)
        except OSError:
            return "ERROR:write_failed"
        tag_manager.request_write(uid)
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
        uid_hex, game_uid = rest.split(":", 1)
        uid_hex = uid_hex.strip()
        game_uid = game_uid.strip()
        if tag_manager.link_existing(uid_hex, game_uid):
            return "OK:LINK:" + uid_hex
        return "ERROR:unknown_tag"

    return "ERROR:unknown_command"


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


def _background_loop(my_ip):
    """Laeuft im einzigen verfuegbaren Hintergrund-Thread: beantwortet
    UDP-Discovery-Anfragen, ruft dazwischen regelmaessig
    tag_manager.poll_once() auf und prueft von Zeit zu Zeit, ob die
    WLAN-Verbindung noch steht (siehe WLAN_CHECK_INTERVAL_MS)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", UDP_PORT))
    s.settimeout(0.05)
    print("Discovery-Server laeuft auf Port", UDP_PORT)

    sta = network.WLAN(network.STA_IF)
    last_poll = time.ticks_ms()
    last_wlan_check = time.ticks_ms()
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

        if time.ticks_diff(now, last_wlan_check) >= WLAN_CHECK_INTERVAL_MS:
            last_wlan_check = now
            if not sta.isconnected():
                print("WLAN-Verbindung verloren - starte neu, um erneut zu verbinden...")
                machine.reset()


def start(my_ip, hostname=""):
    """Startet den kombinierten Discovery-/RFID-Hintergrund-Thread und
    danach TCP-Steuer-Server + HTTP-Statusserver (blockierend im
    aufrufenden Thread)."""
    _thread.start_new_thread(_background_loop, (my_ip,))
    _serve(my_ip, hostname)
