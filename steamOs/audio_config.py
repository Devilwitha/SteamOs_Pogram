"""Persistenter globaler Sound-/Video-Modus fuer die GUI/Steuer-Seite (siehe
gui/gui_server.py, Schalter oben auf der Seite) und pico_client.py (liest
den Modus bei jeder Tag-Erkennung, siehe handle_tag()):

- MODE_SONGS (Standard): wie bisher - jedes Spiel kann in games.db einen
  eigenen Sound haben (audio_path/audio_enabled), der beim Erkennen eines
  damit verknuepften Tags automatisch mitlaeuft.
- MODE_BOOT_SOUND: ein einziger, hier gespeicherter Sound wird bei JEDEM
  erkannten Tag abgespielt, unabhaengig vom verknuepften Spiel (aehnlich
  einem Konsolen-Bootsound).
- MODE_VIDEO: wie MODE_BOOT_SOUND, aber ein einziges Video (siehe
  video_player.py) wird stattdessen vollflaechig abgespielt statt eines
  Sounds.

Bei allen drei Modi bleiben die individuellen Spiel-Sounds in games.db
unangetastet - sie werden in MODE_BOOT_SOUND/MODE_VIDEO nur nicht
verwendet, sodass ein spaeteres Zurueckschalten auf MODE_SONGS sie
unveraendert wiederherstellt.

Gleiches Lazy-Load/Speichern-Muster wie led_link.py/pico_link.py, hier fuer
ein kleines eigenes dict statt games.db, da es sich um eine globale
Einstellung statt einer pro Spiel handelt.
"""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "audio_config.json"

MODE_SONGS = "songs"
MODE_BOOT_SOUND = "boot_sound"
MODE_VIDEO = "video"
VALID_MODES = (MODE_SONGS, MODE_BOOT_SOUND, MODE_VIDEO)

_DEFAULT_CONFIG = {"mode": MODE_SONGS, "boot_sound_path": None, "video_path": None}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def _save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f)


def get_mode():
    mode = load_config().get("mode")
    return mode if mode in VALID_MODES else MODE_SONGS


def set_mode(mode):
    if mode not in VALID_MODES:
        raise ValueError("ungueltiger Sound-Modus: " + str(mode))
    config = load_config()
    config["mode"] = mode
    _save_config(config)


def get_boot_sound_path():
    return load_config().get("boot_sound_path")


def set_boot_sound_path(path):
    config = load_config()
    config["boot_sound_path"] = path
    _save_config(config)


def get_video_path():
    return load_config().get("video_path")


def set_video_path(path):
    config = load_config()
    config["video_path"] = path
    _save_config(config)
