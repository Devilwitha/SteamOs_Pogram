"""Kommunikationslogik mit dem Led_Pico (siehe ../Led_Pico) - einem
zweiten, eigenstaendigen Pico, der einen LED-Streifen in der Farbe des
aktuell erkannten Spiels/Tags setzt.

Bewusst analog zu pico_link.py aufgebaut, aber ein komplett eigenes
Geraet mit eigener Konfiguration/Discovery/Ports: RFID-Pico und Led-Pico
laufen unabhaengig voneinander, der Ausfall eines Geraets darf den
anderen nicht beeintraechtigen.

Protokoll ueber TCP (Standard-Port 5007), zeilenbasiert:
    Anfrage           Antwort
    ----------------- -----------------
    PING              erreichbar
    COLOR:<hex>       OK:COLOR:<hex>
    OFF               OK:OFF

Discovery ueber UDP (Standard-Port 5008):
    Anfrage              Antwort
    -------------------- -----------------
    DISCOVER_LED_PICO    LEDPICO:<ip-des-led-pico>
"""
import json
import socket
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "led_config.json"

DISCOVERY_MESSAGE = b"DISCOVER_LED_PICO"

_DEFAULT_CONFIG = {"led_pico_ip": "", "tcp_port": 5007, "udp_port": 5008}


def load_config():
    """Laedt led_config.json; fehlt sie oder ist sie unvollstaendig,
    werden die Standardwerte ergaenzt, damit der Led_Pico optional bleibt
    (kein hartes Setup-Erfordernis wie bei config.json/dem RFID-Pico)."""
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def discover_led_pico(udp_port, timeout=2.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", udp_port))
        try:
            data, addr = s.recvfrom(64)
            text = data.decode(errors="ignore")
            if text.startswith("LEDPICO:"):
                return text.split(":", 1)[1]
        except socket.timeout:
            return None
    return None


def _send_command(ip, tcp_port, command, timeout=2.0, max_len=256):
    """Sendet eine Zeile an den Led_Pico, liest eine Zeile Antwort zurueck.
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


def ping_led_pico(ip, tcp_port, timeout=2.0):
    return _send_command(ip, tcp_port, "PING", timeout) == "erreichbar"


def set_color(ip, tcp_port, color, timeout=2.0):
    """Setzt den LED-Streifen auf die angegebene Farbe (z. B. '#ff8800')."""
    response = _send_command(ip, tcp_port, f"COLOR:{color}", timeout)
    return response == f"OK:COLOR:{color}"


def turn_off(ip, tcp_port, timeout=2.0):
    """Schaltet den LED-Streifen aus (kein Tag aufgelegt bzw. weder Tag
    noch verknuepftes Spiel hat eine Farbe)."""
    return _send_command(ip, tcp_port, "OFF", timeout) == "OK:OFF"
