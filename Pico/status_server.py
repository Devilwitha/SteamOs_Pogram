"""Web-Statusseite des Pico (Port 80, nur im normalen WLAN-Betrieb aktiv -
nicht zu verwechseln mit captive_portal.py, das nur im Hotspot-Setup-Modus
laeuft, beide teilen sich also nie denselben Port gleichzeitig). Dunkles,
modernes Design (siehe status.html); zeigt Geraetestatus sowie den aktuell
erkannten RFID-Tag und alle bekannten Tags per periodischem JS-Polling von
/status.json an.

Zusaetzlich die Steuer-Seite /control (siehe control.html): anders als
status.html ist sie nicht read-only, sondern spiegelt die volle
SteamOS-GUI (steamOs/gui/gui_server.py) - Spielfarben, Tag-Verknuepfung,
Sound-Upload/-Wiedergabe. Der Pico selbst fuehrt dabei keine dieser
Aktionen aus und speichert auch keine Kopie der Spieledaten: er liefert nur
die Seite aus, deren JavaScript direkt (per fetch, mit Token, siehe
remote_config.py) im Browser des Nutzers mit gui_server.py spricht. Einzige
Ausnahme ist /control/settings (POST): das speichert nur die dafuer noetigen
Verbindungsdaten lokal auf dem Pico, ohne selbst mit dem PC zu sprechen."""
import ujson as json

import net_state
import remote_config
import tag_manager
import wlan

with open("status.html") as _f:
    PAGE = _f.read()

with open("control.html") as _f:
    CONTROL_PAGE = _f.read()


def render_status_json(my_ip, hostname):
    daten = {
        "ip": my_ip,
        "hostname": hostname,
        "modus": wlan.modus,
        "aktueller_tag": tag_manager.get_current(),
        "tags": tag_manager.list_tags(),
    }
    return json.dumps(daten)


def _escape_attr(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_js(text):
    """Fuers Einbetten in ein JS-String-Literal (siehe control.html: der
    gleiche Wert steckt sowohl in einem HTML-Attribut - dafuer reicht
    _escape_attr - als auch im <script>-Block, wo HTML-Entities wie
    '&quot;' nicht als Anfuehrungszeichen verstanden wuerden und ein
    unveraendertes Zeichen die Zeichenkette vorzeitig beenden koennte)."""
    text = (text or "")
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("</", "<\\/")  # verhindert vorzeitiges </script>
    return text.replace("\n", "\\n").replace("\r", "")


def render_control_page():
    cfg = remote_config.get()
    pc_ip = cfg["pc_ip"] or (net_state.get_last_pc_ip() or "")
    pc_port = str(cfg["pc_port"])
    token = cfg["token"]
    pc_mac = cfg["pc_mac"]

    page = CONTROL_PAGE.replace("__PC_IP__", _escape_attr(pc_ip))
    page = page.replace("__PC_PORT__", _escape_attr(pc_port))
    page = page.replace("__TOKEN__", _escape_attr(token))
    page = page.replace("__PC_MAC__", _escape_attr(pc_mac))
    page = page.replace("__PC_IP_JS__", _escape_js(pc_ip))
    page = page.replace("__PC_PORT_JS__", _escape_js(pc_port))
    page = page.replace("__TOKEN_JS__", _escape_js(token))
    return page


def _url_decode(s):
    s = s.replace("+", " ")
    result = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                result += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        result += s[i]
        i += 1
    return result


def _parse_form(body):
    data = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            data[_url_decode(k)] = _url_decode(v)
    return data


def _send_all(cl, data):
    sent = 0
    while sent < len(data):
        n = cl.send(data[sent:])
        if not n:
            break
        sent += n


def _send_response(cl, status_line, headers, body_bytes):
    header = status_line + "\r\n"
    for name, value in headers:
        header += "{}: {}\r\n".format(name, value)
    header += "Connection: close\r\n\r\n"
    _send_all(cl, header.encode() + body_bytes)


def handle(cl, request_line, my_ip, hostname, body=b""):
    """Bearbeitet eine einzelne HTTP-Anfrage auf dem uebergebenen (bereits
    akzeptierten) Client-Socket. `request_line` ist die erste Zeile der
    Anfrage, z. B. 'GET /status.json HTTP/1.1'; `body` der (fuer POST
    bereits vollstaendig eingelesene) Anfrage-Body, siehe
    ping_server._handle_http_client."""
    parts = request_line.split(" ")
    method = parts[0] if parts else "GET"
    path = parts[1] if len(parts) > 1 else "/"

    if method == "POST" and path == "/control/settings":
        # bytes.decode() nimmt auf diesem Board KEINE Keyword-Argumente
        # (siehe README.md, Abschnitt "Problembehandlung") - bewusst
        # argumentlos, kein decode(errors="replace").
        form = _parse_form(body.decode())
        remote_config.save(
            form.get("pc_ip", ""),
            form.get("pc_port", "8090"),
            form.get("token", ""),
            form.get("pc_mac", ""),
        )
        _send_response(cl, "HTTP/1.1 303 See Other", [("Location", "/control?saved=1"), ("Content-Length", "0")], b"")
        return

    if path == "/status.json":
        body_text = render_status_json(my_ip, hostname)
        content_type = "application/json"
    elif path == "/control":
        body_text = render_control_page()
        content_type = "text/html; charset=utf-8"
    else:
        body_text = PAGE
        content_type = "text/html; charset=utf-8"

    # Content-Length wird bewusst mitgeschickt (statt sich nur auf
    # 'Connection: close' + Verbindungsende zu verlassen): so weiss der
    # Browser sofort, wann die Antwort vollstaendig ist, auch falls das
    # tatsaechliche Schliessen der TCP-Verbindung verzoegert ankommt.
    body_bytes = body_text.encode()
    _send_response(cl, "HTTP/1.1 200 OK", [("Content-Type", content_type), ("Content-Length", len(body_bytes))], body_bytes)
