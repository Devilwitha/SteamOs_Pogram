#!/usr/bin/env python3
"""Liest die auf diesem SteamOS-Geraet vorhandenen Steam-Spiele ein und
schreibt sie in eine lokale SQLite-Datenbank (games.db).

Jedes Spiel bekommt eine stabile UID (deterministisch aus der Steam-AppID
abgeleitet, damit wiederholte Scans keine Duplikate erzeugen). Der Name
wird immer gespeichert; Installationspfad und Start-Kommando nur, wenn das
Spiel tatsaechlich installiert ist.
"""
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import vdf_parser

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
    # Migration fuer vor der Farbzuweisung angelegte games.db-Dateien, die
    # die Spalte 'color' noch nicht haben (CREATE TABLE IF NOT EXISTS
    # aendert ein bestehendes Schema nicht).
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
    if "color" not in existing_cols:
        conn.execute("ALTER TABLE games ADD COLUMN color TEXT")
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
        conn.commit()
    finally:
        conn.close()

    return len(all_games)


def main():
    count = scan_and_store()
    print(f"{count} Spiel(e) in {DB_PATH} gespeichert.")


if __name__ == "__main__":
    main()
