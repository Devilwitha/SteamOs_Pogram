#!/usr/bin/env python3
"""Liest die auf diesem SteamOS-Geraet vorhandenen Steam-Spiele ein und
schreibt sie in eine lokale SQLite-Datenbank (games.db).

Jedes Spiel bekommt eine stabile UID (deterministisch aus der Steam-AppID
abgeleitet, damit wiederholte Scans keine Duplikate erzeugen). Der Name
wird immer gespeichert; Installationspfad und Start-Kommando nur, wenn das
Spiel tatsaechlich installiert ist.

Neue Spiele ohne Farbe (siehe README: 'color' wird nie ueberschrieben,
sobald einmal gesetzt) bekommen automatisch eine zugewiesen (siehe
_assign_auto_colors()): bevorzugt aus Steams eigenem lokalem Bildcache
(appcache/librarycache/<appid>/) per PIL, sonst eine kraeftige Zufallsfarbe
statt alle unbenannt gleich (z. B. blau) zu lassen.
"""
import colorsys
import random
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import vdf_parser

try:
    from PIL import Image
except ImportError:
    Image = None

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "games.db"

# Feste Namespace-UUID, damit dieselbe AppID immer dieselbe UID ergibt.
UID_NAMESPACE = uuid.UUID("f5f6a1d0-6e3b-4a2e-9b0a-8f1d2c3e4a5b")

STEAM_ROOT_CANDIDATES = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".steam/root",
]


def find_steam_root():
    for candidate in STEAM_ROOT_CANDIDATES:
        if (candidate / "steamapps").is_dir():
            return candidate
    return None


def find_library_paths(steam_root):
    """Liefert alle Steam-Bibliotheksordner (Hauptinstallation + zusaetzliche
    Laufwerke aus libraryfolders.vdf)."""
    libraries = [steam_root]

    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf_path.is_file():
        try:
            data = vdf_parser.load(vdf_path)
            root = data.get("libraryfolders", data)
            for entry in root.values():
                if not isinstance(entry, dict):
                    continue
                path_str = entry.get("path")
                if path_str:
                    lib_path = Path(path_str)
                    if lib_path not in libraries:
                        libraries.append(lib_path)
        except (OSError, ValueError) as e:
            print(f"Warnung: libraryfolders.vdf konnte nicht gelesen werden: {e}", file=sys.stderr)

    return libraries


def scan_manifests(library_path):
    """Liest alle appmanifest_*.acf Dateien einer Bibliothek aus."""
    games = []
    steamapps_dir = library_path / "steamapps"
    if not steamapps_dir.is_dir():
        return games

    for manifest_path in steamapps_dir.glob("appmanifest_*.acf"):
        try:
            data = vdf_parser.load(manifest_path)
        except (OSError, ValueError) as e:
            print(f"Warnung: {manifest_path} konnte nicht gelesen werden: {e}", file=sys.stderr)
            continue

        app_state = data.get("AppState")
        if not app_state:
            continue

        appid = app_state.get("appid")
        name = app_state.get("name")
        installdir = app_state.get("installdir")
        if not appid or not name:
            continue

        install_path = None
        if installdir:
            candidate = steamapps_dir / "common" / installdir
            if candidate.is_dir():
                install_path = candidate

        games.append({
            "appid": int(appid),
            "name": name,
            "install_path": str(install_path) if install_path else None,
            "installed": install_path is not None,
        })

    return games


def make_uid(appid):
    return str(uuid.uuid5(UID_NAMESPACE, str(appid)))


# Dateinamen im Steam-Bildcache (appcache/librarycache/<appid>/), die als
# Vorlage fuer die automatische Farbermittlung in Frage kommen - in dieser
# Reihenfolge probiert: das vertikale Bibliotheks-Cover ist am ehesten
# reprasentativ und ueberall vorhanden, der Store-Header als Rueckfall.
# Danach wird noch jede sonstige Bilddatei im Ordner probiert (Steam legt
# manche Cache-Dateien ohne Endung an, aber mit gueltigem Bildinhalt -
# z. B. der kleine quadratische Icon-Hash).
_LIBRARY_IMAGE_NAMES = ("library_600x900.jpg", "header.jpg")


def _find_library_image(steam_root, appid):
    """Sucht das beste verfuegbare Cover-/Icon-Bild eines Spiels in Steams
    eigenem lokalem Bildcache. Gibt None zurueck, wenn nichts gefunden
    wurde (z. B. Spiel noch nie in der Steam-Bibliothek geoeffnet)."""
    cache_dir = steam_root / "appcache" / "librarycache" / str(appid)
    if not cache_dir.is_dir():
        return None
    for name in _LIBRARY_IMAGE_NAMES:
        candidate = cache_dir / name
        if candidate.is_file():
            return candidate
    for candidate in sorted(cache_dir.iterdir()):
        if candidate.is_file():
            return candidate
    return None


def _dominant_color_from_image(path):
    """Ermittelt eine reprasentative Farbe aus einem Bild per PIL: auf eine
    kleine Palette reduziert (Median-Cut-Quantisierung), davon die
    haeufigste Farbe genommen - liefert deutlich lebendigere/passendere
    Ergebnisse als ein reiner Pixel-Mittelwert (der bei Coverbildern oft in
    einem blassen Grau/Braun landet). Gibt None zurueck, wenn die Datei
    nicht als Bild gelesen werden kann bzw. PIL nicht installiert ist."""
    if Image is None or path is None:
        return None
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((100, 100))
            quantized = img.quantize(colors=8, method=Image.MEDIANCUT)
            palette = quantized.getpalette()
            counts = quantized.getcolors()
            if not counts:
                return None
            _count, index = max(counts, key=lambda c: c[0])
            r, g, b = palette[index * 3:index * 3 + 3]
            return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return None


def _random_color():
    """Kraeftige Zufallsfarbe (feste hohe Saettigung/Helligkeit im
    HSV-Raum, nur der Farbton ist zufaellig) statt gleichfoermigem
    RGB-Zufall, der oft blass/grau wirkt - Rueckfall fuer Spiele ohne
    brauchbares Cover-Bild (kein PIL, Bild fehlt/nicht lesbar)."""
    r, g, b = colorsys.hsv_to_rgb(random.random(), 0.65, 0.95)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _assign_auto_colors(conn, steam_root):
    """Weist jedem Spiel ohne Farbe (color IS NULL) automatisch eine zu -
    nach Moeglichkeit aus dessen Steam-Cover, sonst eine Zufallsfarbe.
    Laeuft nach jedem upsert_game()-Durchlauf; ruehrt Spiele mit bereits
    gesetzter Farbe (manuell in der GUI oder von einem frueheren Lauf
    dieser Funktion vergeben) nicht an, siehe ensure_db()-Docstring zu
    'color'."""
    rows = conn.execute("SELECT uid, appid FROM games WHERE color IS NULL").fetchall()
    for uid, appid in rows:
        image_path = _find_library_image(steam_root, appid) if steam_root else None
        color = _dominant_color_from_image(image_path) or _random_color()
        conn.execute("UPDATE games SET color = ? WHERE uid = ?", (color, uid))


def ensure_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            uid TEXT PRIMARY KEY,
            appid INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            installed INTEGER NOT NULL DEFAULT 0,
            install_path TEXT,
            launch_command TEXT,
            color TEXT,
            last_scanned TEXT NOT NULL
        )
    """)
    # Migration fuer vor der Farb-/Sound-Zuweisung angelegte games.db-Dateien,
    # die diese Spalten noch nicht haben (CREATE TABLE IF NOT EXISTS aendert
    # ein bestehendes Schema nicht).
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
    if "color" not in existing_cols:
        conn.execute("ALTER TABLE games ADD COLUMN color TEXT")
    if "audio_path" not in existing_cols:
        conn.execute("ALTER TABLE games ADD COLUMN audio_path TEXT")
    if "audio_enabled" not in existing_cols:
        # Default 1 (an): bereits hochgeladene Sounds bleiben nach diesem
        # Upgrade unveraendert aktiv, statt stillschweigend zu verstummen.
        conn.execute("ALTER TABLE games ADD COLUMN audio_enabled INTEGER NOT NULL DEFAULT 1")
    conn.commit()


def upsert_game(conn, game):
    uid = make_uid(game["appid"])
    # 'steam -applaunch <appid>' startet ein installiertes Spiel ueber den
    # Steam-Client (inkl. Proton-Kompatibilitaetsschicht, falls noetig).
    launch_command = f"steam -applaunch {game['appid']}" if game["installed"] else None

    conn.execute("""
        INSERT INTO games (uid, appid, name, installed, install_path, launch_command, last_scanned)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(appid) DO UPDATE SET
            name=excluded.name,
            installed=excluded.installed,
            install_path=excluded.install_path,
            launch_command=excluded.launch_command,
            last_scanned=excluded.last_scanned
    """, (
        uid,
        game["appid"],
        game["name"],
        1 if game["installed"] else 0,
        game["install_path"],
        launch_command,
        time.strftime("%Y-%m-%dT%H:%M:%S"),
    ))


def scan_and_store():
    steam_root = find_steam_root()
    if steam_root is None:
        print("Steam-Installation wurde nicht gefunden.", file=sys.stderr)
        return 0

    all_games = {}
    for library_path in find_library_paths(steam_root):
        for game in scan_manifests(library_path):
            all_games[game["appid"]] = game

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_db(conn)
        for game in all_games.values():
            upsert_game(conn, game)
        _assign_auto_colors(conn, steam_root)
        conn.commit()
    finally:
        conn.close()

    return len(all_games)


def reset_all_colors():
    """Setzt die Farbe ALLER Spiele zurueck auf die automatisch aus dem
    Cover ermittelte (bzw. eine neue Zufallsfarbe, falls kein Cover
    gefunden wird) - im Unterschied zu _assign_auto_colors() (nur Spiele
    ohne Farbe) ueberschreibt das auch bereits manuell in der GUI
    zugewiesene Farben. Fuer den "Farben zuruecksetzen"-Button in der GUI
    (siehe gui_server.py). Gibt die Anzahl betroffener Spiele zurueck."""
    steam_root = find_steam_root()
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_db(conn)
        conn.execute("UPDATE games SET color = NULL")
        count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        _assign_auto_colors(conn, steam_root)
        conn.commit()
    finally:
        conn.close()
    return count


def main():
    count = scan_and_store()
    print(f"{count} Spiel(e) in {DB_PATH} gespeichert.")


if __name__ == "__main__":
    main()
