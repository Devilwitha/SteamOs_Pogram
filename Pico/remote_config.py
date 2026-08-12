"""Persistente Verbindungseinstellungen fuer die Steuer-Seite (control.html):
IP/Port der SteamOS-Seite (steamOs/gui/gui_server.py) sowie das gemeinsame
Token, das dort in config.json unter "remote_control_token" hinterlegt ist.

Vom Nutzer einmalig ueber das Formular auf /control gespeichert (siehe
status_server.py) - danach eingebettet in jede Auslieferung von control.html,
damit dessen JavaScript direkt (ohne Umweg ueber den Pico) mit
gui_server.py sprechen kann.

Gleiches Lazy-Load/Speichern-Muster wie tag_store.py, hier aber fuer ein
einzelnes kleines dict statt einer Tag-Liste - kein separates Locking noetig,
da ausschliesslich aus dem Hauptthread (HTTP-Anfragen, siehe ping_server.py)
gelesen/geschrieben wird, nie aus dem Hintergrund-Thread.
"""
import ujson as json

DATEI = "remote_config.json"

_config = None  # {"pc_ip": str, "pc_port": int, "token": str}
_STANDARD = {"pc_ip": "", "pc_port": 8080, "token": ""}


def _laden():
    global _config
    if _config is not None:
        return
    try:
        with open(DATEI) as f:
            geladen = json.load(f)
    except (OSError, ValueError):
        geladen = {}
    _config = dict(_STANDARD)
    _config.update({k: v for k, v in geladen.items() if k in _STANDARD})


def get():
    _laden()
    return dict(_config)


def save(pc_ip, pc_port, token):
    global _config
    _laden()
    _config = {
        "pc_ip": (pc_ip or "").strip(),
        "pc_port": int(pc_port) if str(pc_port).strip() else _STANDARD["pc_port"],
        "token": (token or "").strip(),
    }
    try:
        with open(DATEI, "w") as f:
            json.dump(_config, f)
    except OSError as e:
        print("Konnte", DATEI, "nicht schreiben:", e)
