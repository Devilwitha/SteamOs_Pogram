#!/usr/bin/env python3
"""Laeuft dauerhaft im Hintergrund auf SteamOS (auch im Game Mode, siehe
steamos-pico-monitor.service) und sendet alle paar Sekunden eine Anfrage
an den Pico. Der Pico antwortet mit 'erreichbar'.

Zusaetzlich wird bei jedem Durchlauf gefragt, ob am Pico ein RFID-Tag mit
einer (noch nicht bestaetigten) Spiel-UID aufliegt (siehe Pico/tag_manager.py).
Ist die UID in games.db bekannt, wird das Spiel gestartet und der Start dem
Pico bestaetigt - danach meldet der Pico dieselbe UID nicht erneut, bis ein
anderes oder kein Tag mehr erkannt wird.

Kennt SteamOS die IP des Pico nicht (config.json -> pico_ip leer oder
Verbindung verloren), wird sie per UDP-Broadcast automatisch im lokalen
Netzwerk gesucht. Die eigentliche Netzwerklogik steckt in pico_link.py,
das sich auch die GUI (gui/gui_server.py) teilt.
"""
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pico_link

GAMES_DB_PATH = Path(__file__).resolve().parent / "games.db"


def _resolve_steam_executable():
    """Unter Windows steckt 'steam' anders als auf SteamOS/Linux i.d.R.
    nicht im PATH - subprocess.Popen(['steam', ...]) faende die Datei
    sonst nicht. Ermittelt den vollen Pfad zu steam.exe ueber die
    Windows-Registry (HKCU\\Software\\Valve\\Steam -> SteamExe). Nur fuer
    lokale Tests auf Windows relevant, auf SteamOS greift dieser Zweig
    nicht (sys.platform != 'win32')."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path, _ = winreg.QueryValueEx(key, "SteamExe")
            return path if Path(path).is_file() else None
    except OSError:
        return None


_STEAM_EXECUTABLE = _resolve_steam_executable()


def find_game_by_uid(uid):
    if not GAMES_DB_PATH.is_file():
        return None
    conn = sqlite3.connect(GAMES_DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM games WHERE uid = ?", (uid,)).fetchone()
    finally:
        conn.close()


def launch_game(game):
    if not game["installed"] or not game["launch_command"]:
        print(f"Spiel '{game['name']}' ist nicht installiert, kann nicht gestartet werden.", flush=True)
        return False

    args = shlex.split(game["launch_command"])
    if args and args[0].lower() == "steam" and _STEAM_EXECUTABLE:
        args[0] = _STEAM_EXECUTABLE

    try:
        subprocess.Popen(args)
        return True
    except OSError as e:
        print(f"Start von '{game['name']}' fehlgeschlagen: {e}", flush=True)
        return False


def handle_tag(pico_ip, tcp_port, timestamp):
    tag_uid = pico_link.check_tag(pico_ip, tcp_port)
    if not tag_uid:
        return

    game = find_game_by_uid(tag_uid)
    if game is None:
        print(f"[{timestamp}] Unbekannte UID auf Tag: {tag_uid}", flush=True)
        return

    print(f"[{timestamp}] Tag erkannt: {game['name']} ({tag_uid})", flush=True)
    if not launch_game(game):
        return

    if pico_link.confirm_started(pico_ip, tcp_port, tag_uid):
        print(f"[{timestamp}] Start bestaetigt an Pico: {game['name']}", flush=True)
    else:
        print(f"[{timestamp}] Konnte Start nicht an Pico bestaetigen (Tag ggf. gewechselt).", flush=True)


def main():
    config = pico_link.load_config()
    interval = config.get("interval_seconds", 3)
    tcp_port = config.get("tcp_port", 5005)
    udp_port = config.get("udp_port", 5006)
    # Fest in config.json eingetragene IP bleibt die ganze Laufzeit ueber
    # massgeblich (siehe unten) - nur ohne konfigurierte IP wird bei
    # Verbindungsverlust per Broadcast neu gesucht.
    configured_ip = config.get("pico_ip") or None
    pico_ip = configured_ip

    print("SteamOS <-> Pico Monitor gestartet", flush=True)

    while True:
        if not pico_ip:
            print("Suche Pico im Netzwerk...", flush=True)
            pico_ip = pico_link.discover_pico(udp_port)
            if pico_ip:
                print(f"Pico gefunden unter {pico_ip}", flush=True)

        if pico_ip:
            reachable = pico_link.ping_pico(pico_ip, tcp_port)
            timestamp = time.strftime("%H:%M:%S")
            if reachable:
                print(f"[{timestamp}] Pico erreichbar ({pico_ip})", flush=True)
                pico_link.write_state("erreichbar", pico_ip)
                handle_tag(pico_ip, tcp_port, timestamp)
            else:
                print(f"[{timestamp}] Pico NICHT erreichbar, versuche erneut...", flush=True)
                pico_link.write_state("nicht_erreichbar", pico_ip)
                # Ist die IP fest konfiguriert, wird sie weiter direkt
                # angepingt (self-healing nach z.B. einem Neustart des
                # Pico) statt auf die u.U. unzuverlaessige Broadcast-Suche
                # auszuweichen - nur eine automatisch gefundene IP wird
                # verworfen und neu gesucht.
                if not configured_ip:
                    pico_ip = None
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Pico nicht gefunden", flush=True)
            pico_link.write_state("nicht_gefunden", None)

        time.sleep(interval)


if __name__ == "__main__":
    main()
