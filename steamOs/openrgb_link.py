"""Kommunikationslogik mit lokal per USB angeschlossenen RGB-Geraeten ueber
OpenRGB (https://openrgb.org) - zeigt dieselbe Farbe wie der optionale
Led_Pico (siehe led_link.py), aber lokal am PC per USB statt ueber das
Netzwerk zu einem eigenen Geraet.

Ein PC meldet OpenRGB typischerweise mehrere RGB-faehige Geraete
(Grafikkarte, Mainboard, Maus, Tastatur, ...), von denen hier aber nur
gezielt bestimmte mitgesteuert werden sollen: target_names (siehe
load_config(), Standard: "Corsair") waehlt per Namens-Teilstring (Gross-/
Kleinschreibung egal) aus, welche Geraete die Spiel-/Leerlauf-Farbe
bekommen (set_color()/turn_off(), siehe unten). Alle uebrigen, nicht
passenden Geraete werden stattdessen einmalig beim Start von
pico_client.py komplett ausgeschaltet (turn_off_others()) - sie sollen
nicht mit eigenen Effekten (Rainbow etc.) stoeren, aber auch nicht an der
Spiel-/Leerlauf-Farbe teilnehmen.

Bewusst analog zu led_link.py aufgebaut (set_color()/turn_off() mit
Hex-Farbe rein, bool zurueck), damit update_led() in pico_client.py beide
symmetrisch nebeneinander ansteuern kann - ein Ausfall des einen darf den
anderen nicht beeintraechtigen. Komplett optional: ohne laufenden
OpenRGB-Server, installierte openrgb-python-Bibliothek oder passende
Geraete wird jeder Aufruf still uebersprungen (gibt False zurueck), genau
wie bei einem nicht erreichbaren Led_Pico.

Setzt voraus:
- OpenRGB laeuft im SDK-Server-Modus (Standard-Port 6742), siehe
  steamos-openrgb.service.
- Die offizielle Python-Client-Bibliothek ist installiert
  (`pip install --user openrgb-python`) - anders als der Rest von
  steamOs/ bewusst NICHT auf die Standardbibliothek beschraenkt, da das
  binaere OpenRGB-SDK-Protokoll (verschachtelte Geraete-/Zonen-/LED-
  Beschreibungen) zu fehleranfaellig fuer eine eigene Nachimplementierung
  waere - die offizielle, gepflegte Bibliothek ist hier der robustere Weg.

Konfiguration ueber openrgb_config.json (siehe load_config()): welche
Geraete die Farb-Synchronisation bekommen (target_names) und die
OpenRGB-SDK-Adresse.
"""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "openrgb_config.json"

_DEFAULT_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 6742,
    "target_names": ["Corsair"],
}


def load_config():
    """Laedt openrgb_config.json; fehlt sie oder ist sie unvollstaendig,
    werden die Standardwerte ergaenzt, damit die Integration optional
    bleibt (kein hartes Setup-Erfordernis wie bei config.json/dem
    RFID-Pico)."""
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _matches(device, names):
    names = [n.lower() for n in names if n]
    return any(n in device.name.lower() for n in names)


def _connect(config):
    """Verbindet sich mit dem lokalen OpenRGB-SDK-Server. Gibt den Client
    zurueck, oder None bei fehlender Bibliothek/deaktivierter Integration/
    nicht erreichbarem Server."""
    if not config.get("enabled", True):
        return None
    try:
        from openrgb import OpenRGBClient
    except ImportError:
        return None
    try:
        return OpenRGBClient(
            address=config.get("host", "127.0.0.1"),
            port=config.get("port", 6742),
            name="SteamOS",
        )
    except Exception:
        return None


def _apply(devices, action):
    """Fuehrt action(device) fuer jedes uebergebene Geraet aus, ignoriert
    dabei Fehler an einzelnen Geraeten (ein defektes/nicht reagierendes
    Geraet soll die uebrigen nicht blockieren). Gibt True zurueck, wenn
    mindestens eines erfolgreich gesetzt wurde."""
    ok = False
    for device in devices:
        try:
            action(device)
            ok = True
        except Exception:
            continue
    return ok


def _with_targets(action):
    """Verbindet sich, fuehrt action(device) fuer jedes zu target_names
    passende Geraet aus und trennt die Verbindung danach wieder (kein
    dauerhaft offener Client, analog zum verbindungslosen Muster von
    led_link.py)."""
    config = load_config()
    client = _connect(config)
    if client is None:
        return False
    try:
        targets = [d for d in client.devices if _matches(d, config.get("target_names", []))]
        return _apply(targets, action)
    finally:
        client.disconnect()


def set_color(color):
    """Setzt alle LEDs der zu target_names passenden Geraete (Standard:
    Corsair) auf die angegebene Farbe (z. B. '#ff8800'), analog zu
    led_link.set_color(). Wechselt jedes Geraet dafuer in den
    'Direct'-Modus, falls vorhanden (fuer Echtzeit-Farben noetig - in
    einem Effekt-Modus wie 'Rainbow' wuerde eine gesetzte Farbe sofort
    wieder ueberschrieben)."""
    from openrgb.utils import RGBColor
    r, g, b = _hex_to_rgb(color)

    def action(device):
        mode_names = [m.name for m in device.modes]
        if "Direct" in mode_names:
            device.set_mode("Direct")
        device.set_color(RGBColor(r, g, b))

    return _with_targets(action)


def turn_off():
    """Schaltet die LEDs der zu target_names passenden Geraete aus, analog
    zu led_link.turn_off()."""
    return _with_targets(lambda device: device.off())


def turn_off_others():
    """Schaltet alle Geraete AUSSER den zu target_names passenden
    (Standard: Corsair) komplett aus - fuer den einmaligen Aufruf beim
    Start von pico_client.py, damit z. B. Grafikkarte/Mainboard/Maus nicht
    mit ihren eigenen Werkseffekten (Rainbow etc.) weiterlaufen/stoeren,
    aber auch nicht an der Spiel-/Leerlauf-Farbe teilnehmen (das bleibt
    den target_names-Geraeten vorbehalten, siehe set_color())."""
    config = load_config()
    client = _connect(config)
    if client is None:
        return False
    try:
        others = [d for d in client.devices if not _matches(d, config.get("target_names", []))]
        return _apply(others, lambda device: device.off())
    finally:
        client.disconnect()
