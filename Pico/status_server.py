"""Web-Statusseite des Pico (Port 80, nur im normalen WLAN-Betrieb aktiv -
nicht zu verwechseln mit captive_portal.py, das nur im Hotspot-Setup-Modus
laeuft, beide teilen sich also nie denselben Port gleichzeitig). Dunkles,
modernes Design (siehe status.html); zeigt Geraetestatus sowie den aktuell
erkannten RFID-Tag und alle bekannten Tags per periodischem JS-Polling von
/status.json an."""
import ujson as json

import tag_manager
import wlan

with open("status.html") as _f:
    PAGE = _f.read()


def render_status_json(my_ip, hostname):
    daten = {
        "ip": my_ip,
        "hostname": hostname,
        "modus": wlan.modus,
        "aktueller_tag": tag_manager.get_current(),
        "tags": tag_manager.list_tags(),
    }
    return json.dumps(daten)


def _send_all(cl, data):
    sent = 0
    while sent < len(data):
        n = cl.send(data[sent:])
        if not n:
            break
        sent += n


def handle(cl, request_line, my_ip, hostname):
    """Bearbeitet eine einzelne HTTP-Anfrage auf dem uebergebenen (bereits
    akzeptierten) Client-Socket. `request_line` ist die erste Zeile der
    Anfrage, z. B. 'GET /status.json HTTP/1.1'."""
    parts = request_line.split(" ")
    path = parts[1] if len(parts) > 1 else "/"

    if path == "/status.json":
        body = render_status_json(my_ip, hostname)
        content_type = "application/json"
    else:
        body = PAGE
        content_type = "text/html; charset=utf-8"

    # Content-Length wird bewusst mitgeschickt (statt sich nur auf
    # 'Connection: close' + Verbindungsende zu verlassen): so weiss der
    # Browser sofort, wann die Antwort vollstaendig ist, auch falls das
    # tatsaechliche Schliessen der TCP-Verbindung verzoegert ankommt.
    body_bytes = body.encode()
    header = "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n".format(
        content_type, len(body_bytes)
    )
    _send_all(cl, header.encode() + body_bytes)
