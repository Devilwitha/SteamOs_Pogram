#!/usr/bin/env python3
"""Plattformuebergreifende, nicht blockierende Audiowiedergabe fuer
Spiel-/Tag-Sounds.

Wird sowohl von der GUI (gui/gui_server.py - Abspielen/Stoppen-Buttons je
Spiel) als auch von pico_client.py (Sound gleichzeitig mit dem Spielstart
beim Tag-Erkennen) verwendet. Absichtlich ohne Drittanbieter-Abhaengigkeit
(siehe gui_server.py-Docstring: SteamOS hat ein schreibgeschuetztes
Root-Dateisystem, es soll ohne zusaetzliche Pakete auskommen):

- Windows: die im System eingebaute Media Control Interface (MCI, ueber
  winmm.dll) uebernimmt die Wiedergabe inkl. MP3 und WAV.
- Linux/SteamOS: ein extern gestartetes Kommandozeilenprogramm (das erste
  gefundene aus _LINUX_PLAYERS - ffplay/mpg123/cvlc/paplay/aplay sind auf
  den meisten Distributionen bzw. SteamOS bereits vorhanden).

play()/stop() halten jeweils nur eine Wiedergabe gleichzeitig fest (ein
Sound pro Tag/Spiel reicht fuer diesen Anwendungsfall) - ein neuer play()-
Aufruf beendet automatisch eine noch laufende vorherige Wiedergabe.
"""
import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

_MCI_ALIAS = "steamos_gamesound"
_linux_proc = None


def _mci(command):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.winmm.mciSendStringW(command, buf, len(buf), None)


def _short_path(path):
    """mciSendStringW() parst den 'open'-Befehl ueber eine veraltete
    Kommandozeilen-Syntax, die bei langen Pfaden (grob > 100-127 Zeichen
    Gesamtlaenge des Befehls) mit einem irrefuehrenden '8.3-Dateiname
    ungueltig'-Fehler abbricht, obwohl der Pfad selbst gueltig ist -
    betrifft z. B. tief verschachtelte Projekt-/Nutzerordner. Der DOS-Kurzname
    (8.3) umgeht das zuverlaessig, da er unabhaengig von der urspruenglichen
    Pfadlaenge kurz ist. Ohne Kurznamen-Unterstuetzung (selten, z. B. per
    Registry global deaktiviert) faellt dies auf den Originalpfad zurueck."""
    buf = ctypes.create_unicode_buffer(260)
    return path if not ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) else buf.value


def _play_windows(path):
    # 'close' auf einen evtl. nicht (mehr) offenen Alias liefert einen
    # MCI-Fehlercode, der hier bewusst ignoriert wird.
    _mci(f'close {_MCI_ALIAS}')
    _mci(f'open "{_short_path(path)}" alias {_MCI_ALIAS}')
    _mci(f'play {_MCI_ALIAS}')


def _stop_windows():
    _mci(f'stop {_MCI_ALIAS}')
    _mci(f'close {_MCI_ALIAS}')


# Reihenfolge = Praeferenz: ffplay/mpg123/cvlc koennen auch MP3, paplay/aplay
# nur WAV - werden aber als letzter Ausweg trotzdem probiert.
_LINUX_PLAYERS = [
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpg123", ["-q"]),
    ("cvlc", ["--play-and-exit", "--quiet"]),
    ("paplay", []),
    ("aplay", ["-q"]),
]


def _find_linux_player():
    for name, args in _LINUX_PLAYERS:
        if shutil.which(name):
            return [name, *args]
    return None


def _play_linux(path):
    global _linux_proc
    _stop_linux()
    player = _find_linux_player()
    if not player:
        print(
            "Audiowiedergabe: kein Player gefunden (ffplay/mpg123/cvlc/paplay/aplay).",
            flush=True,
        )
        return
    try:
        _linux_proc = subprocess.Popen(
            [*player, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(f"Audiowiedergabe fehlgeschlagen: {e}", flush=True)
        _linux_proc = None


def _stop_linux():
    global _linux_proc
    if _linux_proc is not None and _linux_proc.poll() is None:
        try:
            _linux_proc.terminate()
        except OSError:
            pass
    _linux_proc = None


def play(path):
    """Startet die Wiedergabe von path nicht blockierend (laeuft parallel
    zu allem anderen, insb. zu einem per launch_game() gestarteten Spiel).
    path darf leer/None sein oder auf keine vorhandene Datei zeigen (dann
    No-Op) - so kann direkt game['audio_path'] durchgereicht werden."""
    if not path or not Path(path).is_file():
        return
    if sys.platform == "win32":
        _play_windows(str(path))
    else:
        _play_linux(str(path))


def stop():
    """Beendet eine laufende Wiedergabe, falls vorhanden. Ohne laufende
    Wiedergabe ein No-Op."""
    if sys.platform == "win32":
        _stop_windows()
    else:
        _stop_linux()
