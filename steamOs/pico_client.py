#!/usr/bin/env python3
"""Laeuft dauerhaft im Hintergrund auf SteamOS (auch im Game Mode, siehe
steamos-pico-monitor.service) und sendet alle paar Sekunden eine Anfrage
an den Pico. Der Pico antwortet mit 'erreichbar'.

Kennt SteamOS die IP des Pico nicht (config.json -> pico_ip leer oder
Verbindung verloren), wird sie per UDP-Broadcast automatisch im lokalen
Netzwerk gesucht.
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
PING_MESSAGE = b"ping"


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


def ping_pico(ip, tcp_port, timeout=2.0):
    try:
        with socket.create_connection((ip, tcp_port), timeout=timeout) as s:
            s.sendall(PING_MESSAGE)
            s.settimeout(timeout)
            response = s.recv(64)
            return response.decode(errors="ignore").strip() == "erreichbar"
    except OSError:
        return False


def main():
    config = load_config()
    interval = config.get("interval_seconds", 3)
    tcp_port = config.get("tcp_port", 5005)
    udp_port = config.get("udp_port", 5006)
    pico_ip = config.get("pico_ip") or None

    print("SteamOS <-> Pico Monitor gestartet", flush=True)

    while True:
        if not pico_ip:
            print("Suche Pico im Netzwerk...", flush=True)
            pico_ip = discover_pico(udp_port)
            if pico_ip:
                print(f"Pico gefunden unter {pico_ip}", flush=True)

        if pico_ip:
            reachable = ping_pico(pico_ip, tcp_port)
            timestamp = time.strftime("%H:%M:%S")
            if reachable:
                print(f"[{timestamp}] Pico erreichbar ({pico_ip})", flush=True)
                write_state("erreichbar", pico_ip)
            else:
                print(f"[{timestamp}] Pico NICHT erreichbar, suche erneut...", flush=True)
                write_state("nicht_erreichbar", pico_ip)
                pico_ip = None
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Pico nicht gefunden", flush=True)
            write_state("nicht_gefunden", None)

        time.sleep(interval)


if __name__ == "__main__":
    main()
