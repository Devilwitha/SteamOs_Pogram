#!/usr/bin/env python3
"""Plattformuebergreifende, nicht blockierende Vollbild-Videowiedergabe fuer
den optionalen Video-Modus (siehe audio_config.py, MODE_VIDEO): statt eines
Sounds wird bei jedem erkannten Tag ein einziges, global hinterlegtes Video
vollflaechig abgespielt (aehnlich einem Konsolen-Boot-Video) - unabhaengig
vom verknuepften Spiel.

Gleiches nicht-blockierendes Ein-Prozess-Muster wie audio_player.py (siehe
dort): startet ein externes Kommandozeilenprogramm im Hintergrund, ein
neuer play() beendet automatisch eine noch laufende vorherige Wiedergabe.
Bevorzugt mpv/vlc (echte, robuste Vollbildwiedergabe), ffplay als Fallback,
da es (ueber ffmpeg) am ehesten schon vorhanden ist - dieselbe Praeferenz
wie in audio_player.py._LINUX_PLAYERS. Kein MCI-Zweig fuer Windows wie bei
audio_player.py, da MCI kein zuverlaessiges Vollbild fuer Video bietet -
fuer lokale Tests dort muss also eines der u. g. Programme installiert sein.
"""
import shutil
import subprocess
from pathlib import Path

_proc = None

# Reihenfolge = Praeferenz: mpv/vlc bieten echte, robuste Vollbildwiedergabe
# inkl. sauberem Beenden; ffplay als Fallback.
_PLAYERS = [
    ("mpv", ["--fullscreen", "--really-quiet", "--no-terminal"]),
    ("cvlc", ["--fullscreen", "--play-and-exit", "--quiet"]),
    ("vlc", ["--fullscreen", "--play-and-exit", "--quiet"]),
    ("ffplay", ["-fs", "-autoexit", "-loglevel", "quiet"]),
]


def _find_player():
    for name, args in _PLAYERS:
        if shutil.which(name):
            return [name, *args]
    return None


def play(path):
    """Startet die Vollbild-Wiedergabe von path nicht blockierend (laeuft
    parallel zu allem anderen, insb. zu einem per launch_game() gestarteten
    Spiel). path darf leer/None sein oder auf keine vorhandene Datei zeigen
    (dann No-Op)."""
    global _proc
    if not path or not Path(path).is_file():
        return
    stop()
    player = _find_player()
    if not player:
        print("Videowiedergabe: kein Player gefunden (mpv/vlc/ffplay).", flush=True)
        return
    try:
        _proc = subprocess.Popen(
            [*player, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(f"Videowiedergabe fehlgeschlagen: {e}", flush=True)
        _proc = None


def stop():
    """Beendet eine laufende Wiedergabe, falls vorhanden. Ohne laufende
    Wiedergabe ein No-Op."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except OSError:
            pass
    _proc = None
