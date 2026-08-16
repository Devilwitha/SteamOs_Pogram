"""Kommunikationslogik mit dem LilyGo-Statusdisplay (siehe ../lilygo) -
einem dritten, eigenstaendigen Geraet (LilyGo T-Display-S3), das die
aktuelle CPU-/GPU-Auslastung sowie eine Temperatur anzeigt (siehe
system_stats.py und stats_monitor.py).

Bewusst analog zu led_link.py aufgebaut, aber ein komplett eigenes Geraet
mit eigener Konfiguration/Discovery/Ports: RFID-Pico, Led-Pico und
LilyGo-Display laufen unabhaengig voneinander, der Ausfall eines Geraets
darf die anderen nicht beeintraechtigen.

Protokoll ueber TCP (Standard-Port 5009), zeilenbasiert:
    Anfrage                    Antwort
    -------------------------- -----------------
    PING                       erreichbar
    STATS:<cpu>:<gpu>:<temp>   OK:STATS

    <cpu>/<gpu> sind ganzzahlige Prozentwerte (0-100) oder "-" (nicht
    ermittelbar), <temp> ist eine Zahl in Grad Celsius (z. B. "55.0")
    oder ebenfalls "-".

Discovery ueber UDP (Standard-Port 5010):
    Anfrage              Antwort
    -------------------- -----------------
    DISCOVER_LILYGO      LILYGO:<ip-des-geraets>
"""
import json
import socket
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "lilygo_config.json"

DISCOVERY_MESSAGE = b"DISCOVER_LILYGO"

_DEFAULT_CONFIG = {"lilygo_ip": "", "tcp_port": 5009, "udp_port": 5010, "interval_seconds": 2}


def load_config():
    """Laedt lilygo_config.json; fehlt sie oder ist sie unvollstaendig,
    werden die Standardwerte ergaenzt, damit das Display optional bleibt
    (kein hartes Setup-Erfordernis wie bei config.json/dem RFID-Pico)."""
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def discover_lilygo(udp_port, timeout=2.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", udp_port))
        try:
            data, addr = s.recvfrom(64)
            text = data.decode(errors="ignore")
            if text.startswith("LILYGO:"):
                return text.split(":", 1)[1]
        except socket.timeout:
            return None
    return None


def _send_command(ip, tcp_port, command, timeout=2.0, max_len=256):
    """Sendet eine Zeile an das LilyGo-Display, liest eine Zeile Antwort
    zurueck. Gibt die getrimmte Antwort zurueck, oder None bei
    Verbindungsfehler."""
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


def ping_lilygo(ip, tcp_port, timeout=2.0):
    return _send_command(ip, tcp_port, "PING", timeout) == "erreichbar"


def _fmt(value):
    return "-" if value is None else str(value)


def send_stats(ip, tcp_port, cpu, gpu, temp, timeout=2.0):
    """Uebertraegt CPU-/GPU-Auslastung (Prozent, int oder None) sowie eine
    Temperatur (Grad Celsius, float/int oder None) an das Display."""
    command = f"STATS:{_fmt(cpu)}:{_fmt(gpu)}:{_fmt(temp)}"
    return _send_command(ip, tcp_port, command, timeout) == "OK:STATS"
