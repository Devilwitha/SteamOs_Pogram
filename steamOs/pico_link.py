"""Gemeinsame Kommunikationslogik mit dem Pico.

Wird sowohl vom Hintergrund-Monitor (pico_client.py, Erreichbarkeits-Check
alle paar Sekunden) als auch von der GUI (gui/gui_server.py, Spielauswahl
senden) verwendet.

Protokoll ueber TCP (Standard-Port 5005), zeilenbasiert:
    Anfrage           Antwort
    ----------------- -----------------
    PING              erreichbar
    SELECT:<uid>      OK:<uid>
    TAG?              TAG:<uid>  oder  TAG:NONE
    STARTED:<uid>     OK:STARTED:<uid>  oder  ERROR:mismatch
    TAGS?             TAGS:<json-liste aller bekannten Tags>
    LINK:<uid>:<uid2> OK:LINK:<uid>  oder  ERROR:unknown_tag
    TAGCOLOR:<uid>:<f> OK:TAGCOLOR:<uid>  oder  ERROR:unknown_tag
    CURRENT?          CURRENT:<json des aktuellen Tags>  oder  CURRENT:NONE

Discovery ueber UDP (Standard-Port 5006):
    Anfrage           Antwort
    ----------------- -----------------
    DISCOVER_PICO     PICO:<ip-des-pico>
"""
import json
import socket
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
STATE_PATH = SCRIPT_DIR / "state.json"

DISCOVERY_MESSAGE = b"DISCOVER_PICO"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def write_state(status, ip):
    state = {
        "status": status,
        "pico_ip": ip,
        "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except OSError as e:
        print(f"Konnte Statusdatei nicht schreiben: {e}", file=sys.stderr)


def discover_pico(udp_port, timeout=2.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", udp_port))
        try:
            data, addr = s.recvfrom(64)
            text = data.decode(errors="ignore")
            if text.startswith("PICO:"):
                return text.split(":", 1)[1]
        except socket.timeout:
            return None
    return None


def _send_command(ip, tcp_port, command, timeout=2.0, max_len=256):
    """Sendet eine Zeile an den Pico, liest eine Zeile Antwort zurueck.
    Gibt die getrimmte Antwort zurueck, oder None bei Verbindungsfehler."""
    try:
        with socket.create_connection((ip, tcp_port), timeout=timeout) as s:
            s.sendall((command.strip() + "\n").encode())
            s.settimeout(timeout)
            data = b""
            while not data.endswith(b"\n") and len(data) < max_len:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            return data.decode(errors="ignore").strip()
    except OSError:
        return None


def ping_pico(ip, tcp_port, timeout=2.0):
    return _send_command(ip, tcp_port, "PING", timeout) == "erreichbar"


def select_game(ip, tcp_port, uid, timeout=3.0):
    """Sendet die UID des ausgewaehlten Spiels an den Pico.
    Gibt (True, bestaetigte_uid) zurueck, wenn der Pico exakt diese UID
    bestaetigt hat, sonst (False, Antwort-oder-None)."""
    response = _send_command(ip, tcp_port, f"SELECT:{uid}", timeout)
    if response and response.startswith("OK:"):
        confirmed_uid = response[len("OK:"):]
        return confirmed_uid == uid, confirmed_uid
    return False, response


def check_tag(ip, tcp_port, timeout=2.0):
    """Fragt den Pico, ob ein Tag mit einer neuen/unbestaetigten Spiel-UID
    aufliegt. Gibt die UID zurueck, oder None."""
    response = _send_command(ip, tcp_port, "TAG?", timeout)
    if response and response.startswith("TAG:") and response != "TAG:NONE":
        return response[len("TAG:"):]
    return None


def confirm_started(ip, tcp_port, uid, timeout=2.0):
    """Bestaetigt dem Pico, dass das Spiel mit dieser UID gestartet wurde,
    damit er aufhoert, sie erneut zu melden."""
    response = _send_command(ip, tcp_port, f"STARTED:{uid}", timeout)
    return response == f"OK:STARTED:{uid}"


def fetch_tags(ip, tcp_port, timeout=3.0):
    """Fragt die dem Pico bekannte Liste erkannter RFID-Tags ab. Gibt eine
    Liste von {'uid': ..., 'game_uid': ...-oder-None} zurueck, oder None
    bei Verbindungsfehler bzw. ungueltiger Antwort."""
    response = _send_command(ip, tcp_port, "TAGS?", timeout, max_len=65536)
    if response and response.startswith("TAGS:"):
        try:
            return json.loads(response[len("TAGS:"):])
        except ValueError:
            return None
    return None


def link_tag(ip, tcp_port, uid_hex, game_uid, timeout=3.0):
    """Verknuepft (game_uid gesetzt) oder loest (game_uid leer) einen dem
    Pico bereits bekannten Tag mit einem Spiel - ohne dass der Tag dafuer
    erneut an den Leser gehalten werden muss."""
    response = _send_command(ip, tcp_port, f"LINK:{uid_hex}:{game_uid or ''}", timeout)
    return response == f"OK:LINK:{uid_hex}"


def set_tag_color(ip, tcp_port, uid_hex, color, timeout=3.0):
    """Setzt (color leer = loescht) die eigene LED-Farbe eines dem Pico
    bereits bekannten Tags - fuer den Led_Pico (siehe ../Led_Pico), hat
    Vorrang vor der Farbe des verknuepften Spiels."""
    response = _send_command(ip, tcp_port, f"TAGCOLOR:{uid_hex}:{color or ''}", timeout)
    return response == f"OK:TAGCOLOR:{uid_hex}"


def fetch_current(ip, tcp_port, timeout=2.0):
    """Fragt den aktuell aufliegenden Tag ab (UID, verknuepfte Spiel-UID
    und eigene Farbe), unabhaengig vom einmaligen TAG?-Meldezustand.
    Gibt ein dict zurueck, oder None wenn kein Tag aufliegt bzw. bei
    Verbindungsfehler."""
    response = _send_command(ip, tcp_port, "CURRENT?", timeout)
    if not response or response == "CURRENT:NONE":
        return None
    if response.startswith("CURRENT:"):
        try:
            return json.loads(response[len("CURRENT:"):])
        except ValueError:
            return None
    return None
