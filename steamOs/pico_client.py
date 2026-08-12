#!/usr/bin/env python3
"""Laeuft dauerhaft im Hintergrund auf SteamOS (auch im Game Mode, siehe
steamos-pico-monitor.service) und sendet alle paar Sekunden eine Anfrage
an den Pico. Der Pico antwortet mit 'erreichbar'.

Zusaetzlich wird bei jedem Durchlauf gefragt, ob am Pico ein RFID-Tag mit
einer (noch nicht bestaetigten) Spiel-UID aufliegt (siehe Pico/tag_manager.py).
Ist die UID in games.db bekannt, wird das Spiel gestartet und der Start dem
Pico bestaetigt - danach meldet der Pico dieselbe UID nicht erneut, bis ein
anderes oder kein Tag mehr erkannt wird.

Solange der Tag, mit dem das aktuell laufende Spiel gestartet wurde,
weiterhin aufliegt, passiert bei jedem Durchlauf nichts weiter (siehe
check_game_still_active()). Liegt er laenger nicht mehr auf oder liegt
inzwischen ein anderer Tag auf (jeweils per CURRENT? abgefragt - der Pico
haelt einen kurzzeitig nicht gelesenen Tag selbst schon fuer
tag_manager.TAG_GRACE_MS als weiterhin aufliegend, siehe
Pico/tag_manager.py), wird das Spiel automatisch beendet (stop_game()).

Kennt SteamOS die IP des Pico nicht (config.json -> pico_ip leer oder
Verbindung verloren), wird sie per UDP-Broadcast automatisch im lokalen
Netzwerk gesucht. Die eigentliche Netzwerklogik steckt in pico_link.py,
das sich auch die GUI (gui/gui_server.py) teilt.

Zusaetzlich wird bei jedem Durchlauf per update_led() die Farbe des
gerade aufliegenden Tags (bzw. des damit verknuepften Spiels) ermittelt
und an einen optionalen zweiten Pico weitergereicht (siehe ../Led_Pico),
der damit einen LED-Streifen ansteuert - unabhaengig vom Spielstart,
komplett eigenstaendiges Geraet (led_config.json/led_link.py).
"""
import csv
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import led_link
import pico_link

GAMES_DB_PATH = Path(__file__).resolve().parent / "games.db"

# Zuletzt an den Led_Pico gesendete Farbe (siehe update_led()) - eigenes
# Sentinel-Objekt statt None, da None selbst ein gueltiger Zustand ist
# (kein Tag/keine Farbe -> Streifen aus).
_UNSET = object()
_last_led_color = _UNSET
_led_pico_ip = None

# Per Tag gestartetes Spiel, das aktuell laeuft (siehe handle_tag()/
# check_game_still_active()) - None, wenn keins ueber RFID gestartet
# wurde bzw. es bereits wieder beendet ist.
_running_game = None


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
    """Startet ein Spiel, gibt das Popen-Objekt zurueck (oder None bei
    Fehler/nicht installiert). Der Rueckgabewert wird in _running_game
    gemerkt, damit stop_game() spaeter versuchen kann, genau diesen
    Prozess zu beenden."""
    if not game["installed"] or not game["launch_command"]:
        print(f"Spiel '{game['name']}' ist nicht installiert, kann nicht gestartet werden.", flush=True)
        return None

    args = shlex.split(game["launch_command"])
    if args and args[0].lower() == "steam" and _STEAM_EXECUTABLE:
        args[0] = _STEAM_EXECUTABLE

    try:
        return subprocess.Popen(args)
    except OSError as e:
        print(f"Start von '{game['name']}' fehlgeschlagen: {e}", flush=True)
        return None


def _find_pids_linux(target):
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return []

    pids = []
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if str((entry / "exe").resolve()).startswith(target):
                pids.append(pid)
                continue
        except OSError:
            pass
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
            if target in cmdline:
                pids.append(pid)
        except OSError:
            pass
    return pids


def _find_pids_windows_by_path(target):
    """Ueber WMI (Win32_Process) per PowerShell abgefragt, um ohne
    Zusatzpaket (z. B. psutil) auszukommen. WICHTIG: ExecutablePath/
    CommandLine bleiben bei Win32_Process aus Berechtigungsgruenden fuer
    etliche Prozesse leer (bekannte WMI-Einschraenkung, unabhaengig davon
    ob dieses Skript erhoeht laeuft) - diese Methode ist deshalb nur ein
    Zusatz zu _find_pids_windows_by_name() (siehe dort), nicht die primaere
    Erkennung."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,ExecutablePath,CommandLine | "
                "ConvertTo-Csv -NoTypeInformation",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Prozessliste (PowerShell) konnte nicht abgefragt werden: {e}", flush=True)
        return []

    target_lower = target.lower()
    pids = []
    reader = csv.reader(result.stdout.splitlines())
    next(reader, None)  # Kopfzeile ueberspringen
    for row in reader:
        if len(row) < 3:
            continue
        pid_str, exe_path, cmdline = row[0], row[1], row[2]
        if target_lower in exe_path.lower() or target_lower in cmdline.lower():
            try:
                pids.append(int(pid_str))
            except ValueError:
                pass
    return pids


def _candidate_exe_names(install_path):
    """Basisnamen aller .exe-Dateien unterhalb von install_path (klein
    geschrieben) - Grundlage fuer _find_pids_windows_by_name(). Reine
    Dateisystem-Suche, unabhaengig von Prozess-Berechtigungen."""
    try:
        return {p.name.lower() for p in Path(install_path).rglob("*.exe")}
    except OSError:
        return set()


def _find_pids_windows_by_name(names):
    """Primaere Windows-Erkennung: nutzt 'tasklist' (kein PowerShell/WMI
    noetig) um laufende Prozesse anhand ihres Datei-Basisnamens zu finden.
    Anders als Win32_Process.ExecutablePath/CommandLine (siehe
    _find_pids_windows_by_path) liefert tasklist den Image-Namen
    zuverlaessig fuer praktisch alle sichtbaren Prozesse, unabhaengig von
    Berechtigungen - deutlich robuster fuer diesen Zweck."""
    if not names:
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Prozessliste (tasklist) konnte nicht abgefragt werden: {e}", flush=True)
        return []

    pids = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2:
            continue
        image_name, pid_str = row[0], row[1]
        if image_name.lower() in names:
            try:
                pids.append(int(pid_str))
            except ValueError:
                pass
    return pids


def _find_pids_under_install_path(install_path):
    """Sucht laufende Prozesse, die zu install_path gehoeren (Linux ueber
    /proc, Windows ueber tasklist-Namensabgleich + WMI-Pfadabgleich als
    Zusatz - siehe die einzelnen _find_pids_*-Funktionen). Noetig, weil
    'steam -applaunch <appid>' (siehe game_scanner.py) nur den bereits
    laufenden Steam-Client benachrichtigt und sich selbst i. d. R. sofort
    wieder beendet - das eigentliche Spiel laeuft als eigener, von Steam
    gestarteter Prozess. Ohne install_path oder auf einer nicht
    unterstuetzten Plattform liefert das eine leere Liste; dann bleibt fuer
    stop_game() nur proc.terminate()."""
    if not install_path:
        return []

    try:
        target = str(Path(install_path).resolve())
    except OSError:
        return []

    if sys.platform == "win32":
        pids = set(_find_pids_windows_by_name(_candidate_exe_names(target)))
        pids.update(_find_pids_windows_by_path(target))
        return list(pids)
    return _find_pids_linux(target)


def stop_game(game, proc):
    """Beendet ein per Tag gestartetes Spiel. Siehe
    _find_pids_under_install_path() dazu, warum proc.terminate() allein
    bei ueber Steam gestarteten Spielen meist nicht reicht. Gibt True
    zurueck, wenn mindestens ein Prozess ein Beenden-Signal erhalten hat
    (keine Garantie, dass er sich auch tatsaechlich beendet)."""
    pids = _find_pids_under_install_path(game["install_path"])
    print(f"Beende '{game['name']}': gefundene Prozesse unter install_path: {pids or 'keine'}", flush=True)

    stopped = False
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except OSError as e:
            print(f"  Konnte PID {pid} nicht beenden: {e}", flush=True)

    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            stopped = True
        except OSError as e:
            print(f"  Konnte Start-Prozess nicht beenden: {e}", flush=True)

    if not stopped:
        print(
            f"  Warnung: kein Prozess von '{game['name']}' konnte beendet werden "
            "(install_path falsch/leer, oder das Spiel laeuft unter einem anderen Pfad?).",
            flush=True,
        )

    return stopped


def handle_tag(pico_ip, tcp_port, timestamp):
    global _running_game

    tag_uid = pico_link.check_tag(pico_ip, tcp_port)
    if not tag_uid:
        return

    game = find_game_by_uid(tag_uid)
    if game is None:
        print(f"[{timestamp}] Unbekannte UID auf Tag: {tag_uid}", flush=True)
        return

    print(f"[{timestamp}] Tag erkannt: {game['name']} ({tag_uid})", flush=True)
    proc = launch_game(game)
    if proc is None:
        return

    if pico_link.confirm_started(pico_ip, tcp_port, tag_uid):
        print(f"[{timestamp}] Start bestaetigt an Pico: {game['name']}", flush=True)
    else:
        print(f"[{timestamp}] Konnte Start nicht an Pico bestaetigen (Tag ggf. gewechselt).", flush=True)

    _running_game = {"game_uid": tag_uid, "game": game, "proc": proc}


def check_game_still_active(current):
    """Beendet das aktuell per Tag laufende Spiel, sobald der zugehoerige
    Tag nicht mehr aufliegt oder durch einen anderen ersetzt wurde (siehe
    CURRENT? / pico_link.fetch_current). Liegt derselbe Tag weiterhin auf,
    passiert nichts. Ohne ueber RFID gestartetes Spiel ein No-Op."""
    global _running_game

    if _running_game is None:
        return

    current_game_uid = current.get("game_uid") if current else None
    if current_game_uid == _running_game["game_uid"]:
        return

    game = _running_game["game"]
    print(f"Tag fuer '{game['name']}' nicht mehr aufliegend oder gewechselt - beende Spiel.", flush=True)
    stop_game(game, _running_game["proc"])
    _running_game = None


def resolve_led_color(current):
    """Ermittelt die fuer den Led_Pico anzuzeigende Farbe aus dem
    aktuellen Tag-Status (siehe pico_link.fetch_current): eine direkt am
    Tag gesetzte Farbe hat Vorrang vor der Farbe des verknuepften Spiels.
    Gibt None zurueck, wenn kein Tag aufliegt bzw. weder Tag noch Spiel
    eine Farbe haben (Streifen soll dann aus sein)."""
    if not current:
        return None
    if current.get("color"):
        return current["color"]
    game_uid = current.get("game_uid")
    if game_uid:
        game = find_game_by_uid(game_uid)
        if game is not None:
            return game["color"]
    return None


def update_led(current):
    """Haelt den Led_Pico auf dem Laufenden: ermittelt aus dem (von main()
    bereits per CURRENT? abgefragten) aktuellen Tag-Status die passende
    Farbe und schickt sie weiter - aber nur, wenn sie sich seit dem
    letzten Durchlauf geaendert hat, um nicht bei jedem Takt unnoetig
    Netzwerkverkehr zum Led_Pico zu erzeugen. Ist kein Led_Pico im Netzwerk
    konfiguriert/erreichbar, wird das stillschweigend uebersprungen - er
    ist optional."""
    global _last_led_color, _led_pico_ip

    color = resolve_led_color(current)
    if color == _last_led_color:
        return

    led_config = led_link.load_config()
    led_tcp_port = led_config.get("tcp_port", 5007)
    led_udp_port = led_config.get("udp_port", 5008)
    led_ip = led_config.get("led_pico_ip") or _led_pico_ip or led_link.discover_led_pico(led_udp_port)
    if not led_ip:
        return

    ok = led_link.set_color(led_ip, led_tcp_port, color) if color else led_link.turn_off(led_ip, led_tcp_port)
    if ok:
        _led_pico_ip = led_ip
        _last_led_color = color
    else:
        # IP war offenbar nicht (mehr) erreichbar - naechstes Mal neu
        # ermitteln statt dauerhaft gegen eine tote IP zu senden.
        _led_pico_ip = None


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
                # Erst pruefen/beenden, dann ggf. neu starten: so wird ein
                # bereits laufendes Spiel zuverlaessig gestoppt, auch wenn
                # im selben Durchlauf sofort ein neuer Tag mit einem
                # anderen Spiel erkannt wird (siehe check_game_still_active).
                current = pico_link.fetch_current(pico_ip, tcp_port)
                check_game_still_active(current)
                handle_tag(pico_ip, tcp_port, timestamp)
                update_led(current)
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
