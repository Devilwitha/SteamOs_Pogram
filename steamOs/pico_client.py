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
und weitergereicht an: einen optionalen zweiten Pico (siehe ../Led_Pico),
der damit einen LED-Streifen ansteuert (led_config.json/led_link.py), und
optional lokal per USB angeschlossene RGB-Geraete ueber OpenRGB - Standard
sind Corsair-Geraete (siehe openrgb_config.json/openrgb_link.py,
target_names) - beide unabhaengig vom Spielstart und voneinander,
komplett eigenstaendig. Alle uebrigen von OpenRGB gemeldeten Geraete
(Grafikkarte, Mainboard, Maus, ...) werden einmalig beim Start komplett
ausgeschaltet (siehe main()/openrgb_link.turn_off_others()), statt mit
eigenen Werkseffekten weiterzulaufen.
"""
import colorsys
import csv
import math
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import audio_config
import audio_player
import download_monitor
import game_scanner
import led_link
import led_settings
import openrgb_link
import pico_link
import video_player

GAMES_DB_PATH = Path(__file__).resolve().parent / "games.db"

# Zuletzt an den Led_Pico gesendete Farbe (siehe update_led()) - eigenes
# Sentinel-Objekt statt None, da None selbst ein gueltiger Zustand ist
# (kein Tag/keine Farbe -> Streifen aus).
_UNSET = object()
_last_led_color = _UNSET
_led_pico_ip = None

# Siehe _download_monitor_loop(): True, waehrend dieser Hintergrund-Thread
# gerade wegen eines laufenden Steam-Downloads pulsiert - update_led() in
# der Hauptschleife ueberspringt in dieser Zeit bewusst jedes eigene
# Senden, um nicht gegen das Pulsieren anzusenden (siehe dort).
_download_pulse_active = False

# Per Tag gestartetes Spiel, das aktuell laeuft (siehe handle_tag()/
# check_game_still_active()) - None, wenn keins ueber RFID gestartet
# wurde bzw. es bereits wieder beendet ist.
_running_game = None

# Von main() bei jedem Durchlauf aktualisiert (Ergebnis von
# pico_link.fetch_current(), siehe dort) - dem Download-Puls-Thread
# (_download_monitor_loop(), laeuft separat) zugaenglich, damit dieser
# waehrend eines laufenden Spiels in dessen tatsaechlicher aktueller Farbe
# pulsieren kann (siehe resolve_led_color()), statt in _last_led_color
# nachzuschauen - das wuerde veraltet bleiben, weil update_led() waehrend
# des Pulsierens bewusst nichts sendet/aktualisiert (siehe dort).
_current_tag = None

# Farbe eines gerade laufenden, installierten Spiels, per Prozess-Scan
# erkannt (siehe _scan_for_process_color()) - unabhaengig von Tag/Pico,
# damit die LED-Farbe auch OHNE Pico (oder ohne aufliegenden Tag) das
# tatsaechlich laufende Spiel zeigt, sobald es z. B. direkt ueber Steam
# Big Picture gestartet wurde. None, wenn kein bekanntes installiertes
# Spiel gerade laeuft bzw. es keine eigene Farbe hat. Von main() bei jedem
# Durchlauf aktualisiert (ein Scan pro Takt statt einem pro
# resolve_led_color()-Aufruf, siehe dort - relevant, weil der
# Download-Puls-Thread resolve_led_color() bis zu 10x/Sekunde aufruft).
_process_detected_color = None


def _resolve_steam_executable():
    """'steam' steckt nicht immer im PATH des Prozesses, der pico_client.py
    startet (z.B. systemd-Service mit minimalem PATH, oder eine Shell ohne
    vollstaendiges Profil) - subprocess.Popen(['steam', ...]) faende die
    Datei dann nicht. Ermittelt daher den vollen Pfad: unter Windows ueber
    die Registry (HKCU\\Software\\Valve\\Steam -> SteamExe), sonst per
    shutil.which() bzw. den ueblichen SteamOS/Linux-Installationspfaden."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                path, _ = winreg.QueryValueEx(key, "SteamExe")
                return path if Path(path).is_file() else None
        except OSError:
            return None

    which = shutil.which("steam")
    if which:
        return which
    for candidate in (Path.home() / ".local/share/Steam/steam.sh", Path("/usr/bin/steam")):
        if candidate.is_file():
            return str(candidate)
    return None


_STEAM_EXECUTABLE = _resolve_steam_executable()


def find_game_by_uid(uid):
    if not GAMES_DB_PATH.is_file():
        return None
    conn = sqlite3.connect(GAMES_DB_PATH)
    try:
        game_scanner.ensure_db(conn)
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


def _fetch_installed_games():
    """Alle installierten Spiele mit Farbe/install_path/appid - Grundlage
    fuer _find_running_installed_game() unten. Eigene, schlanke Abfrage
    statt find_game_by_uid() fuer jedes Spiel einzeln, da hier ohnehin die
    ganze Liste gebraucht wird."""
    if not GAMES_DB_PATH.is_file():
        return []
    conn = sqlite3.connect(GAMES_DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT uid, name, color, install_path, appid FROM games "
            "WHERE installed = 1 AND install_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()


# Steams eigener "reaper"-Prozess startet jedes ueber Steam gestartete
# Spiel als "reaper SteamLaunch AppId=<id> -- ...") und bleibt fuer die
# GESAMTE Spielsitzung am Leben (das ist sein einziger Zweck: das Spiel
# ueberwachen und beim Beenden aufraeumen) - ein viel zuverlaessigeres
# Signal als ein Abgleich gegen install_path (siehe
# _scan_running_game_linux()).
_APPID_RE = re.compile(r"AppId=(\d+)")


def _scan_running_game_linux(games):
    """EIN Durchlauf ueber /proc fuer ALLE installierten Spiele auf einmal
    (statt _find_pids_linux() einzeln pro Spiel aufzurufen) - sonst waere
    das bei z. B. 50 installierten Spielen 50 volle /proc-Durchlaeufe pro
    Tick, viel zu teuer fuer periodisches Polling. Liefert das erste
    passende Spiel (sqlite3.Row) oder None.

    Bevorzugt den reaper/AppId-Abgleich (siehe _APPID_RE) vor dem
    install_path-Abgleich: Bei per Proton gestarteten Spielen laeuft der
    eigentliche Spielprozess innerhalb des Wine-Prefix unter einem
    virtuellen Windows-Laufwerksbuchstaben (z. B. "S:\\steamapps\\...")
    statt dem echten Linux-Pfad - ein install_path-Abgleich faende dort
    nur die Proton/Wine-Bootstrap-Zwischenprozesse, die nach dem
    Spielstart wieder verschwinden, waehrend das Spiel selbst
    weiterlaeuft (beobachtet: LED sprang nach kurzer Zeit faelschlich auf
    die Leerlauf-Farbe, siehe Chatverlauf). reaper bleibt dagegen
    zuverlaessig fuer die komplette Sitzung bestehen."""
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return None

    by_appid = {str(g["appid"]): g for g in games if g["appid"]}
    targets = []
    for game in games:
        try:
            targets.append((game, str(Path(game["install_path"]).resolve())))
        except OSError:
            continue
    if not by_appid and not targets:
        return None

    path_match = None
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            cmdline = ""

        if cmdline and by_appid:
            match = _APPID_RE.search(cmdline)
            if match and match.group(1) in by_appid:
                return by_appid[match.group(1)]

        if path_match is None:
            try:
                exe = str((entry / "exe").resolve())
            except OSError:
                exe = ""
            for game, target in targets:
                if (exe and exe.startswith(target)) or (cmdline and target in cmdline):
                    path_match = game
                    break

    return path_match


def _scan_running_game_windows(games):
    """Windows-Pendant zu _scan_running_game_linux() - EIN tasklist-Aufruf
    fuer alle Spiele statt einem pro Spiel (siehe dort fuer den Grund)."""
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    running_names = {row[0].lower() for row in csv.reader(result.stdout.splitlines()) if row}
    for game in games:
        if _candidate_exe_names(game["install_path"]) & running_names:
            return game
    return None


def _find_running_installed_game(games):
    if sys.platform == "win32":
        return _scan_running_game_windows(games)
    return _scan_running_game_linux(games)


def _scan_for_process_color():
    """Fuellt _process_detected_color (siehe dort) - fuer main(), einmal
    pro Takt aufgerufen."""
    game = _find_running_installed_game(_fetch_installed_games())
    if game is not None and game["color"]:
        return game["color"]
    return None


def _find_reaper_pid(appid):
    """Sucht Steams eigenen "reaper"-Prozess fuer appid (derselbe
    AppId=<id>-Abgleich wie in _scan_running_game_linux(), siehe dort fuer
    den Hintergrund) - SIGTERM an reaper beendet zuverlaessig auch das von
    ihm ueberwachte Spiel selbst (das ist reapers Zweck: das Spiel starten,
    ueberwachen und bei einem eigenen Beenden-Signal sauber mit beenden),
    selbst wenn der eigentliche Spielprozess sich (z. B. unter Proton mit
    einem virtuellen Windows-Laufwerksbuchstaben statt echtem Linux-Pfad)
    nicht ueber install_path finden liesse - siehe stop_game()."""
    if sys.platform == "win32" or not appid:
        return None
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return None
    target = f"AppId={appid}"
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if target in cmdline:
            return int(entry.name)
    return None


def stop_game(game, proc):
    """Beendet ein per Tag gestartetes Spiel. Siehe
    _find_pids_under_install_path() dazu, warum proc.terminate() allein
    bei ueber Steam gestarteten Spielen meist nicht reicht - zusaetzlich
    wird (falls gefunden) reapers PID mitbeendet (siehe _find_reaper_pid()),
    da install_path bei Proton-Spielen nur die Bootstrap-Zwischenprozesse
    findet, nicht den eigentlichen (unter einem virtuellen Windows-Pfad
    laufenden) Spielprozess. Gibt True zurueck, wenn mindestens ein Prozess
    ein Beenden-Signal erhalten hat (keine Garantie, dass er sich auch
    tatsaechlich beendet)."""
    pids = _find_pids_under_install_path(game["install_path"])
    reaper_pid = _find_reaper_pid(game["appid"])
    if reaper_pid is not None and reaper_pid not in pids:
        pids.append(reaper_pid)
    print(f"Beende '{game['name']}': gefundene Prozesse: {pids or 'keine'}", flush=True)

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
    # Sound/Video und Spielstart laufen bewusst nebeneinander her:
    # audio_player.play()/video_player.play() sind selbst nicht blockierend
    # (Windows: MCI async, Linux: eigener Player-Prozess), halten
    # launch_game() also nicht auf. Was (falls ueberhaupt etwas) laeuft,
    # haengt vom globalen Modus ab (siehe audio_config.py, per
    # GUI/Steuer-Seite umschaltbar): im Boot-Sound-/Video-Modus immer
    # derselbe Sound/dasselbe Video fuer jedes Spiel, sonst wie bisher der
    # individuelle Spiel-Sound (nur falls audio_enabled) - der manuelle
    # Test-Play-Button in der GUI bleibt davon unabhaengig.
    mode = audio_config.get_mode()
    if mode == audio_config.MODE_BOOT_SOUND:
        boot_sound_path = audio_config.get_boot_sound_path()
        if boot_sound_path:
            audio_player.play(boot_sound_path)
    elif mode == audio_config.MODE_VIDEO:
        video_path = audio_config.get_video_path()
        if video_path:
            video_player.play(video_path)
    elif game["audio_enabled"]:
        audio_player.play(game["audio_path"])
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
    audio_player.stop()
    video_player.stop()
    _running_game = None


# Sentinel fuer update_led()/_last_led_color, wenn die LED-Synchronisation
# per led_settings.is_enabled() abgeschaltet ist - kann nie mit einer
# echten Farbe (immer "#......") kollidieren.
_LED_DISABLED = "disabled"


def _resolve_active_color(current):
    """Wie resolve_led_color() unten, aber OHNE Leerlauf-Fallback - liefert
    None, wenn weder Tag/Spiel (current) noch ein per Prozess-Scan
    erkanntes laufendes Spiel (_process_detected_color, siehe dort) eine
    eigene Farbe haben. Eigene Funktion, damit Aufrufer (siehe
    _download_monitor_loop()) zwischen "wirklich kein Spiel aktiv" und
    "aktiv, aber zufaellig in Leerlauf-Farbe" unterscheiden koennen.

    Bewusst NUR die Farbe des verknuepften Spiels, keine eigene Tag-Farbe
    mehr (fruehers TAGCOLOR-Protokoll/current.get('color') wird hier
    absichtlich nicht mehr gelesen) - genau eine Farbe pro Spiel statt
    zweier separater, potenziell widerspruechlicher Farben (Tag vs.
    Spiel). Die GUIs setzen dementsprechend auch keine Tag-Farbe mehr,
    siehe gui_server.py/dashboard.html/native_console.py."""
    if current:
        game_uid = current.get("game_uid")
        if game_uid:
            game = find_game_by_uid(game_uid)
            if game is not None and game["color"]:
                return game["color"]
    return _process_detected_color


def resolve_led_color(current):
    """Ermittelt die fuer Led_Pico/Corsair-LEDs anzuzeigende Farbe: die
    Farbe des per Tag verknuepften Spiels (siehe pico_link.fetch_current),
    sonst die Farbe eines per Prozess-Scan erkannten laufenden Spiels
    (siehe _scan_for_process_color() - funktioniert dadurch auch ganz ohne
    Pico bzw. ohne aufliegenden Tag, z. B. bei einem direkt ueber Steam
    Big Picture gestarteten Spiel). Ohne Treffer wird die in
    led_settings.json konfigurierte Leerlauf-Farbe (Standard Weiss)
    zurueckgegeben."""
    return _resolve_active_color(current) or led_settings.get_idle_color()


def update_led(current):
    """Haelt sowohl den optionalen Led_Pico als auch optionale lokale
    USB-RGB-Geraete ueber OpenRGB an (siehe openrgb_link.py - standardmaessig
    Corsair-Geraete, siehe openrgb_config.json/target_names; alle uebrigen
    OpenRGB-Geraete werden separat einmalig beim Start ausgeschaltet, siehe
    main()): ermittelt aus dem (von main() bereits per CURRENT? abgefragten)
    aktuellen Tag-Status die passende Farbe (siehe resolve_led_color(), im
    Leerlauf die konfigurierte Leerlauf-Farbe statt aus) und schickt sie an
    beide weiter - aber nur, wenn sie sich seit dem letzten Durchlauf
    geaendert hat, um nicht bei jedem Takt unnoetig Netzwerk-/USB-Verkehr
    zu erzeugen. Ist die LED-Synchronisation per led_settings.json
    (Hauptschalter, siehe led_settings.py) deaktiviert, werden beide
    stattdessen einmalig ausgeschaltet und dann in Ruhe gelassen, bis
    wieder aktiviert. Led_Pico und OpenRGB-Geraete sind unabhaengig
    voneinander optional: ist eins nicht konfiguriert/erreichbar, wird nur
    dieses eine stillschweigend uebersprungen, ohne das andere zu
    beeintraechtigen. Solange keins von beiden erreichbar war, wird beim
    naechsten Durchlauf erneut versucht (kein dauerhaftes Aufgeben, falls
    z. B. der Led_Pico oder der OpenRGB-Server erst spaeter online geht).
    Pausiert komplett, waehrend _download_pulse_active gesetzt ist (siehe
    _download_monitor_loop()) - der Puls-Thread hat dann die Kontrolle,
    ein gleichzeitiges Senden hier wuerde nur dagegen ansenden."""
    global _last_led_color, _led_pico_ip

    if _download_pulse_active:
        return

    if not led_settings.is_enabled():
        if _last_led_color != _LED_DISABLED:
            led_config = led_link.load_config()
            led_ip = led_config.get("led_pico_ip") or _led_pico_ip or led_link.discover_led_pico(led_config.get("udp_port", 5008))
            if led_ip:
                led_link.turn_off(led_ip, led_config.get("tcp_port", 5007))
            openrgb_link.turn_off()
            _last_led_color = _LED_DISABLED
        return

    color = resolve_led_color(current)
    if color == _last_led_color:
        return

    led_config = led_link.load_config()
    led_tcp_port = led_config.get("tcp_port", 5007)
    led_udp_port = led_config.get("udp_port", 5008)
    led_ip = led_config.get("led_pico_ip") or _led_pico_ip or led_link.discover_led_pico(led_udp_port)
    led_ok = False
    if led_ip:
        led_ok = led_link.set_color(led_ip, led_tcp_port, color)
        if led_ok:
            _led_pico_ip = led_ip
        else:
            # IP war offenbar nicht (mehr) erreichbar - naechstes Mal neu
            # ermitteln statt dauerhaft gegen eine tote IP zu senden.
            _led_pico_ip = None

    openrgb_ok = openrgb_link.set_color(color)

    if led_ok or openrgb_ok:
        _last_led_color = color


def reset_led_cache():
    """Erzwingt beim naechsten update_led()-Aufruf ein erneutes Senden der
    aktuellen Farbe, auch wenn sie sich softwareseitig nicht geaendert hat.
    Fuer main(), nachdem ein Aufwachen aus dem Suspend erkannt wurde (siehe
    dort): ein angeschlossenes Geraet (Led_Pico/USB-RGB) kann waehrend des
    Suspends seinen Zustand verloren haben (z. B. Stromverlust am
    USB-Port), obwohl pico_client.py selbst unveraendert von "Weiss"
    ausgeht - ohne Cache-Reset wuerde update_led() das Senden faelschlich
    uebersehen, weil sich die Farbe aus seiner Sicht nicht geaendert hat."""
    global _last_led_color
    _last_led_color = _UNSET


def blink_leds(color, cycles=3, on_seconds=0.15, off_seconds=0.15):
    """Laesst Led_Pico/OpenRGB kurz zwischen der angegebenen Farbe und Aus
    hin- und herblinken - fuer das Sleep/Shutdown-Blinken (siehe
    _start_sleep_shutdown_listener()). Bewusst kurz gehalten (Standard
    < 1s insgesamt), auch wenn _start_sleep_shutdown_listener() dank
    Inhibitor-Lock (siehe dort) eigentlich mehrere Sekunden Zeit haette -
    das Blinken soll sich nicht traege anfuehlen.
    Ruft am Ende reset_led_cache() auf, damit die naechste normale
    update_led()-Runde (z. B. nach einem abgebrochenen Suspend, oder nach
    dem Aufwachen) die eigentliche Farbe zuverlaessig wiederherstellt."""
    led_config = led_link.load_config()
    led_tcp_port = led_config.get("tcp_port", 5007)
    led_udp_port = led_config.get("udp_port", 5008)
    led_ip = led_config.get("led_pico_ip") or _led_pico_ip or led_link.discover_led_pico(led_udp_port)

    for _ in range(cycles):
        if led_ip:
            led_link.set_color(led_ip, led_tcp_port, color)
        openrgb_link.set_color(color)
        time.sleep(on_seconds)
        if led_ip:
            led_link.turn_off(led_ip, led_tcp_port)
        openrgb_link.turn_off()
        time.sleep(off_seconds)

    reset_led_cache()


def _start_sleep_shutdown_listener():
    """Startet einen Hintergrund-Thread, der ueber DBus (System-Bus,
    org.freedesktop.login1.Manager) auf die Signale PrepareForSleep und
    PrepareForShutdown lauscht - beide werden mit einem bool-Argument
    gesendet (True kurz bevor der PC tatsaechlich schlafen geht bzw.
    herunterfaehrt, False beim Aufwachen bzw. bei einem abgebrochenen
    Shutdown). Bei True wird einmal kurz in der zuletzt gezeigten Farbe
    geblinkt (siehe blink_leds()) - komplett optional per
    led_settings.json umschaltbar (siehe led_settings.is_enabled()/
    is_blink_on_sleep_enabled()).

    Haelt dafuer durchgehend einen "delay"-Inhibitor-Lock
    (org.freedesktop.login1.Manager.Inhibit("sleep:shutdown", ...)) -
    ohne den signalisiert PrepareForSleep/-Shutdown zwar rechtzeitig, aber
    logind wartet nicht darauf, dass ein Programm tatsaechlich reagiert
    hat: das eigentliche Schlafen/Herunterfahren (und damit oft auch die
    Stromversorgung von Led_Pico/USB-RGB) konnte in der Praxis schon
    mitten in der ~1s-Blinksequenz einsetzen, sodass nichts sichtbar
    blinkte, obwohl der Log-Eintrag "... steht bevor - LEDs blinken."
    bereits geschrieben wurde. Mit dem Lock wartet logind bis zu
    InhibitDelayMaxSec (logind.conf, Standard 5s) auf dessen Freigabe -
    nach dem Blinken (bzw. sofort, falls das Feature/LED-Sync deaktiviert
    ist) wird der Lock-Deskriptor geschlossen, was logind freigibt,
    fortzufahren. Fuer die naechste Gelegenheit (naechster Suspend/
    Shutdown) wird direkt danach automatisch ein neuer Lock geholt.

    Nutzt dbus-python + eine GLib-Ereignisschleife (beide auf SteamOS/
    Bazzite bereits systemweit vorhanden, siehe README) statt einer
    zusaetzlichen Abhaengigkeit. Faengt jeden Fehler beim Aufsetzen ab
    (z. B. falls eine der Bibliotheken doch fehlt oder kein System-Bus
    erreichbar ist) und laeuft dann einfach ohne dieses Feature weiter,
    statt den ganzen Dienst zum Absturz zu bringen - rein optionales
    Extra, RFID-Tag-Erkennung/Spielstart haengen nicht davon ab."""
    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError as e:
        print(f"Sleep/Shutdown-Blinken nicht verfuegbar (DBus/PyGObject fehlt: {e}) - wird uebersprungen.", flush=True)
        return

    state = {"manager": None, "inhibit_fd": None}

    def acquire_inhibit_lock():
        if state["inhibit_fd"] is not None or state["manager"] is None:
            return
        try:
            fd = state["manager"].Inhibit(
                "sleep:shutdown",
                "SteamOS Konsole",
                "LEDs vor dem Schlafen/Herunterfahren kurz blinken lassen",
                "delay",
            )
            state["inhibit_fd"] = fd.take()
        except Exception as e:
            print(f"Sleep/Shutdown-Blinken: Inhibitor-Lock nicht erhalten ({e}) - Blinken evtl. unzuverlaessig.", flush=True)

    def release_inhibit_lock():
        fd = state["inhibit_fd"]
        state["inhibit_fd"] = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def on_prepare(start, anlass):
        if not start:
            # Aufwachen aus dem Suspend bzw. abgebrochener Shutdown - fuer
            # das naechste Mal wieder einen Lock bereithalten. Bei
            # Shutdown kommt dieser Zweig i. d. R. nicht mehr zum Tragen,
            # der Prozess wird vorher beendet - schadet hier aber nicht.
            acquire_inhibit_lock()
            return
        try:
            if led_settings.is_enabled() and led_settings.is_blink_on_sleep_enabled():
                color = _last_led_color
                if color in (None, _UNSET, _LED_DISABLED):
                    color = led_settings.get_idle_color()
                print(f"{anlass} steht bevor - LEDs blinken.", flush=True)
                blink_leds(color)
        finally:
            release_inhibit_lock()

    def run_loop():
        try:
            DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            state["manager"] = dbus.Interface(
                bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1"),
                "org.freedesktop.login1.Manager",
            )
            bus.add_signal_receiver(
                lambda start: on_prepare(bool(start), "Suspend"),
                signal_name="PrepareForSleep",
                dbus_interface="org.freedesktop.login1.Manager",
            )
            bus.add_signal_receiver(
                lambda start: on_prepare(bool(start), "Shutdown"),
                signal_name="PrepareForShutdown",
                dbus_interface="org.freedesktop.login1.Manager",
            )
            acquire_inhibit_lock()
            GLib.MainLoop().run()
        except Exception as e:
            print(f"Sleep/Shutdown-Blinken: Fehler beim Einrichten: {e}", flush=True)

    threading.Thread(target=run_loop, name="sleep-shutdown-listener", daemon=True).start()


def _hex_to_hsv(color):
    r = int(color[1:3], 16) / 255
    g = int(color[3:5], 16) / 255
    b = int(color[5:7], 16) / 255
    return colorsys.rgb_to_hsv(r, g, b)


def _hsv_lerp(color1, color2, t):
    """Interpoliert zwischen zwei Hex-Farben im HSV-Farbton (nicht direkt
    in RGB) - eine direkte RGB-Interpolation ergaebe bei z. B. Rot->Gruen
    in der Mitte ein blasses Oliv statt eines kraeftigen Zwischentons."""
    h1, s1, v1 = _hex_to_hsv(color1)
    h2, s2, v2 = _hex_to_hsv(color2)
    h = h1 + (h2 - h1) * t
    s = s1 + (s2 - s1) * t
    v = v1 + (v2 - v1) * t
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _download_gradient_color(progress):
    """Farbverlauf ueber die drei in led_settings.json konfigurierten
    Stuetzfarben bei 0/50/100% (Standard Rot/Gelb/Gruen, siehe
    led_settings.get_download_gradient_start()/-_mid()/-_end()), fuer das
    Download-Pulsieren im Leerlauf (siehe _download_monitor_loop()) - kein
    Tag mit Spiel aufliegend, also keine eigene Farbe zum Pulsieren
    vorhanden. Interpoliert stueckweise (0-50% zwischen Start/Mitte,
    50-100% zwischen Mitte/Ende) im HSV-Farbton, siehe _hsv_lerp()."""
    progress = max(0.0, min(1.0, progress))
    start = led_settings.get_download_gradient_start()
    mid = led_settings.get_download_gradient_mid()
    end = led_settings.get_download_gradient_end()
    if progress <= 0.5:
        return _hsv_lerp(start, mid, progress / 0.5)
    return _hsv_lerp(mid, end, (progress - 0.5) / 0.5)


def _scale_color(color, factor):
    """Skaliert eine Hex-Farbe um factor (0.0-1.0) - fuer den
    Helligkeitsverlauf beim Pulsieren (siehe _download_monitor_loop())."""
    factor = max(0.0, min(1.0, factor))
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"#{round(r * factor):02x}{round(g * factor):02x}{round(b * factor):02x}"


_progress_smooth_appid = None
_progress_smooth_value = 0.0
_progress_smooth_time = 0.0
_progress_smooth_rate = 0.0


def _smoothed_download_progress(appid, raw_progress, actively_transferring=True):
    """Steam schreibt BytesDownloaded/BytesToDownload im Manifest nur alle
    paar Minuten neu (siehe download_monitor.py), obwohl im Hintergrund
    laufend tatsaechlich Daten uebertragen werden - eine direkte
    Weiterverwendung des rohen Werts liesse die LED-Farbe ueber diese
    langen Strecken einfrieren und nur beim naechsten echten
    Steam-Schreibvorgang sprunghaft weiterspringen (wirkte im Test wie
    'aendert sich nur beim Aus-/Wiedereinschalten', siehe Chatverlauf, da
    genau dabei zufaellig ein frischer Wert gelesen wurde). Extrapoliert
    stattdessen zwischen den seltenen echten Messwerten linear anhand der
    zuletzt beobachteten Rate (Fortschritt pro Sekunde zwischen den beiden
    letzten echten Werten), gedeckelt auf maximal 5 Prozentpunkte
    Vorsprung gegenueber dem letzten echten Wert, damit ein zwischenzeitlich
    tatsaechlich pausierter/gestoppter Download nicht unbegrenzt
    weiterzuwandern scheint.

    actively_transferring (siehe download_monitor.is_actively_transferring()):
    False bedeutet, Steam hat appid gerade zugunsten eines anderen
    gleichzeitig wartenden Downloads pausiert (mehrere Titel gleichzeitig
    in der Warteschlange sind auf diesem System keine Seltenheit, siehe
    Chatverlauf) - die Extrapolation wird dann eingefroren, statt mit der
    zuletzt beobachteten (jetzt nicht mehr gueltigen) Rate optimistisch
    weiterzuschaetzen."""
    global _progress_smooth_appid, _progress_smooth_value, _progress_smooth_time, _progress_smooth_rate

    now = time.monotonic()

    if appid != _progress_smooth_appid:
        _progress_smooth_appid = appid
        _progress_smooth_value = raw_progress
        _progress_smooth_time = now
        _progress_smooth_rate = 0.0
        return raw_progress

    if raw_progress != _progress_smooth_value:
        dt = now - _progress_smooth_time
        if dt > 0:
            _progress_smooth_rate = max(0.0, (raw_progress - _progress_smooth_value) / dt)
        _progress_smooth_value = raw_progress
        _progress_smooth_time = now
        return raw_progress

    if not actively_transferring:
        return _progress_smooth_value

    extrapolated = _progress_smooth_value + _progress_smooth_rate * (now - _progress_smooth_time)
    extrapolated = min(extrapolated, _progress_smooth_value + 0.05, 1.0)
    return max(0.0, extrapolated)


def _download_monitor_loop():
    """Laeuft dauerhaft in einem eigenen Hintergrund-Thread (siehe main()):
    prueft, ob Steam aktuell etwas herunterlaedt/aktualisiert (siehe
    download_monitor.get_download_progress()), und laesst waehrenddessen
    die LEDs sanft pulsieren (Sinus-Helligkeitsverlauf, ca. alle 3
    Sekunden ein voller Zyklus) - in der aktuell aufliegenden Spielfarbe,
    falls ein per Tag gestartetes Spiel laeuft (siehe _running_game),
    sonst (Leerlauf/"Konsole an") in einem konfigurierbaren Farbverlauf je
    nach Downloadfortschritt (siehe _download_gradient_color()). Ist
    nichts (mehr) im Download oder das Feature per led_settings.json
    deaktiviert
    (download_pulse, siehe led_settings.py), wird nur alle 2s billig
    nachgeschaut, statt staendig zu pulsieren. Setzt/loescht
    _download_pulse_active, damit update_led() (Hauptschleife) waehrend
    des Pulsierens nicht dagegen ansendet, und ruft beim Ende eines
    Downloads reset_led_cache() auf, damit update_led() danach zuverlaessig
    den eigentlichen statischen Zustand wiederherstellt.

    Wichtig: die Led_Pico-IP wird bewusst nur EINMAL beim Einstieg ins
    Pulsieren ermittelt (discover_led_pico() kann bis zu dessen Timeout
    dauern, siehe led_link.py) und dann fuer die Dauer des Downloads
    zwischengespeichert - eine Neuermittlung bei jedem einzelnen
    Puls-Tick (alle 0.1s) wuerde ohne konfigurierten/erreichbaren
    Led_Pico das fluessige Pulsieren komplett ausbremsen (der Ablauf
    haette dann effektiv die Dauer des Discovery-Timeouts pro Tick statt
    0.1s, siehe Chatverlauf).

    Aus demselben Grund wird auch download_monitor.get_download_progress()
    (fragt bevorzugt live per CDP-Websocket bei Steams eigener UI nach,
    siehe download_monitor.py - jeder Aufruf oeffnet dafuer eine eigene
    Verbindung und dauert ca. 20-50ms) NICHT bei jedem 0.1s-Puls-Tick neu
    abgefragt, sondern nur einmal pro Sekunde (_PROGRESS_POLL_INTERVAL) -
    dazwischen wird der zwischengespeicherte Wert fuer die reine
    Helligkeits-Animation weiterverwendet, sonst wuerde das Pulsieren
    ueber die gesamte Downloaddauer hinweg 10x/Sekunde unnoetig neue
    Verbindungen zu Steams Debug-Port aufbauen."""
    global _download_pulse_active

    _PROGRESS_POLL_INTERVAL = 1.0

    t = 0.0
    led_ip = None
    was_pulsing = False
    next_poll_time = 0.0
    cached_progress_info = None
    cached_active = True
    while True:
        pulse_wanted = led_settings.is_enabled() and led_settings.is_download_pulse_enabled()
        now = time.monotonic()

        if not pulse_wanted:
            cached_progress_info = None
        elif now >= next_poll_time:
            cached_progress_info = download_monitor.get_download_progress()
            cached_active = True
            if cached_progress_info is not None:
                active = download_monitor.is_actively_transferring(cached_progress_info[0])
                cached_active = active if active is not None else True
            next_poll_time = now + _PROGRESS_POLL_INTERVAL

        progress_info = cached_progress_info

        if progress_info is None:
            if _download_pulse_active:
                _download_pulse_active = False
                reset_led_cache()
            was_pulsing = False
            next_poll_time = 0.0
            time.sleep(2)
            continue

        if not was_pulsing:
            led_config = led_link.load_config()
            led_ip = led_config.get("led_pico_ip") or _led_pico_ip or led_link.discover_led_pico(led_config.get("udp_port", 5008))
            was_pulsing = True

        _appid, progress = progress_info
        progress = _smoothed_download_progress(_appid, progress, cached_active)
        _download_pulse_active = True

        active_color = _resolve_active_color(_current_tag)
        if active_color is not None:
            # Bewusst ueber _resolve_active_color(_current_tag) statt
            # _last_led_color: Letzteres wird waehrend des Pulsierens NICHT
            # mehr aktualisiert (update_led() kehrt dann sofort um, siehe
            # dort) - ein laufendes Spiel (per Tag ODER per Prozess-Scan
            # erkannt, siehe _process_detected_color) wuerde sonst in der
            # zuletzt VOR dem Download-Start gezeigten (u.U. laengst
            # veralteten, z. B. noch der Leerlauf-)Farbe gepulst, statt in
            # der tatsaechlichen Tag-/Spielfarbe.
            base_color = active_color
        elif led_settings.is_download_gradient_enabled():
            base_color = _download_gradient_color(progress)
        else:
            # Farbverlauf deaktiviert (siehe led_settings.py) - im
            # Leerlauf trotzdem pulsieren, aber in der normalen
            # Leerlauf-Farbe statt im Rot-Gelb-Gruen-Verlauf.
            base_color = led_settings.get_idle_color()

        brightness = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t))
        color = _scale_color(base_color, brightness)

        led_tcp_port = led_link.load_config().get("tcp_port", 5007)
        if led_ip:
            led_link.set_color(led_ip, led_tcp_port, color)
        openrgb_link.set_color(color)

        t += 0.3
        time.sleep(0.1)


def _start_download_pulse_listener():
    """Startet _download_monitor_loop() (siehe dort) in einem eigenen
    Hintergrund-Thread, damit main() nicht blockiert wird."""
    threading.Thread(target=_download_monitor_loop, name="download-pulse", daemon=True).start()


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
    # Einmalig beim Start: alle OpenRGB-Geraete ausser den target_names
    # (Standard: Corsair, siehe openrgb_config.json) komplett ausschalten,
    # statt mit ihren eigenen Werkseffekten (Rainbow etc.) weiterzulaufen -
    # rein optional, ohne laufenden OpenRGB-Server ein stiller No-Op.
    openrgb_link.turn_off_others()
    # Blinkt die LEDs kurz an, sobald der PC schlafen geht/herunterfaehrt
    # (siehe dort) - laeuft in einem eigenen Hintergrund-Thread, blockiert
    # main() also nicht.
    _start_sleep_shutdown_listener()
    # Laesst die LEDs waehrend eines laufenden Steam-Downloads pulsieren
    # (siehe dort) - ebenfalls ein eigener Hintergrund-Thread.
    _start_download_pulse_listener()

    # Fuer die Suspend-Erkennung unten - bewusst time.monotonic() statt
    # time.time(), da Monotonic-Zeit beim Suspend selbst mit pausiert
    # (die reale Uhrzeit springt beim Aufwachen einfach weiter, aber auch
    # der ganze Prozess war ja die ganze Zeit pausiert - der Vergleich
    # unten erkennt also zuverlaessig eine lange reale Pause).
    last_loop_time = time.monotonic()

    while True:
        now_monotonic = time.monotonic()
        # Eine Zeitluecke deutlich groesser als interval zwischen zwei
        # Durchlaeufen bedeutet praktisch immer: der PC war im Suspend und
        # ist gerade aufgewacht (der Prozess pausiert dabei einfach, siehe
        # oben). LED-Cache zuruecksetzen (siehe reset_led_cache()), damit
        # die aktuelle Farbe garantiert neu gesendet wird, auch falls ein
        # angeschlossenes Geraet waehrend des Suspends seinen Zustand
        # verloren hat.
        if now_monotonic - last_loop_time > interval * 5:
            print("Aus dem Suspend aufgewacht - LED-Zustand wird neu gesendet.", flush=True)
            reset_led_cache()
        last_loop_time = now_monotonic

        if not pico_ip:
            print("Suche Pico im Netzwerk...", flush=True)
            pico_ip = pico_link.discover_pico(udp_port)
            if pico_ip:
                print(f"Pico gefunden unter {pico_ip}", flush=True)

        # current bleibt None, wenn der Pico nicht gefunden/erreichbar ist -
        # update_led() (siehe unten, jetzt bei jedem Durchlauf aufgerufen,
        # nicht nur wenn der Pico erreichbar ist) zeigt dann ueber
        # resolve_led_color() automatisch die Leerlauf-Farbe (Standard
        # Weiss) an, statt die LEDs unveraendert im letzten Zustand zu
        # lassen - so leuchten sie schon, sobald dieser Dienst startet,
        # auch bevor/ohne dass der Pico ueberhaupt gefunden wurde.
        current = None
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

        global _current_tag, _process_detected_color
        _current_tag = current
        _process_detected_color = _scan_for_process_color()
        update_led(current)
        time.sleep(interval)


if __name__ == "__main__":
    main()
