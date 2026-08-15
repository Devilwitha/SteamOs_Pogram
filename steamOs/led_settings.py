"""Persistente allgemeine LED-Einstellungen - eigener Abschnitt in der GUI
(gui/gui_server.py) und der Pico-Steuerseite (Pico/control.html), gelesen
von pico_client.py bei jedem update_led()-Aufruf:

- enabled: Hauptschalter fuer die gesamte LED-Synchronisation (sowohl
  Led_Pico als auch lokale USB-RGB-Geraete ueber OpenRGB, siehe
  led_link.py/openrgb_link.py) - "false" schaltet beide sofort aus und
  ueberspringt jede weitere Farbermittlung/-uebertragung, bis wieder
  aktiviert.
- idle_color: welche Farbe angezeigt wird, wenn kein Tag aufliegt bzw.
  weder Tag noch Spiel eine eigene Farbe haben (z. B. als "Konsole an"-
  Anzeige gedacht, analog zur Standby-/Betriebs-LED einer Spielekonsole -
  Standard Weiss, aber frei waehlbar statt hart codiert).
- blink_on_sleep: ob die LEDs kurz in der zuletzt gezeigten Farbe blinken
  sollen, sobald der PC in den Standby geht oder heruntergefahren wird
  (siehe pico_client.py: _start_sleep_shutdown_listener()/blink_leds()) -
  unabhaengig vom Hauptschalter 'enabled' umschaltbar, da man z. B. das
  Blinken beim Herunterfahren stoeren, die normale Farbanzeige aber
  behalten koennte (und umgekehrt).

Gleiches Lazy-Load/Speichern-Muster wie audio_config.py/led_link.py.
"""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "led_settings.json"

_DEFAULT_CONFIG = {"enabled": True, "idle_color": "#ffffff", "blink_on_sleep": True}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def _save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f)


def is_enabled():
    return bool(load_config().get("enabled", True))


def set_enabled(enabled):
    config = load_config()
    config["enabled"] = bool(enabled)
    _save_config(config)


def get_idle_color():
    return load_config().get("idle_color") or "#ffffff"


def set_idle_color(color):
    config = load_config()
    config["idle_color"] = color
    _save_config(config)


def is_blink_on_sleep_enabled():
    return bool(load_config().get("blink_on_sleep", True))


def set_blink_on_sleep_enabled(enabled):
    config = load_config()
    config["blink_on_sleep"] = bool(enabled)
    _save_config(config)
