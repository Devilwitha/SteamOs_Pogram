#!/usr/bin/env python3
"""Windows-Version von steamOs/game_scanner.py, zum lokalen Testen auf
einem Windows-Rechner (z. B. um die GUI/den Pico-Client mit echten
Spieledaten zu fuellen, ohne SteamOS-Hardware zu benoetigen).

Nutzt dieselbe Scan-/Datenbank-Logik wie steamOs/game_scanner.py
(VDF-Parsing, games.db-Schema) und ueberschreibt nur die Suche nach der
Steam-Installation: statt der Linux-Pfade wird zuerst die
Windows-Registry (respektiert einen individuellen Installationsordner)
und sonst der uebliche Windows-Standardpfad verwendet.

Aufruf:  python game_scanner.py
Schreibt in dieselbe games.db wie steamOs/game_scanner.py
(../steamOs/games.db) - siehe windows/README.md.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steamOs"))

import game_scanner  # noqa: E402


def find_steam_root_windows():
    """Sucht die Steam-Installation ueber die Windows-Registry
    (HKCU\\Software\\Valve\\Steam -> SteamPath), sonst ueber die
    ueblichen Standard-Installationspfade."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            candidate = Path(path)
            if (candidate / "steamapps").is_dir():
                return candidate
    except OSError:
        pass

    for env_var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_var)
        if not base:
            continue
        candidate = Path(base) / "Steam"
        if (candidate / "steamapps").is_dir():
            return candidate

    return None


def main():
    if sys.platform != "win32":
        print("Hinweis: Dieses Skript ist fuer Windows gedacht.", file=sys.stderr)

    # scan_and_store() ruft find_steam_root() im Namespace von game_scanner
    # auf - durch das Ueberschreiben hier wird ohne Code-Duplikation die
    # Windows-Suche verwendet, der Rest der Logik bleibt identisch.
    game_scanner.find_steam_root = find_steam_root_windows

    count = game_scanner.scan_and_store()
    print(f"{count} Spiel(e) in {game_scanner.DB_PATH} gespeichert.")


if __name__ == "__main__":
    main()
