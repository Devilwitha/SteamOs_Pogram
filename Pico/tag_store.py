"""Persistenter Speicher fuer erkannte RFID-Tags: physische Tag-UID (Hex-
String) -> optional verknuepfte Spiel-UID sowie optionale eigene Farbe.
Wird sowohl vom Hintergrund-Polling (tag_manager.py) als auch vom
Status-Server und dem TCP-Protokoll (TAGS?/LINK/TAGCOLOR/CURRENT?) genutzt.

Die Farbe (Hex-String wie '#ff8800') wird unabhaengig von der Spiel-
Verknuepfung gespeichert: ist sie gesetzt, hat sie beim Led_Pico Vorrang
vor der Farbe des verknuepften Spiels (siehe steamOs/pico_client.py).

Bewusst KEINE Daten mehr auf den Tag selbst geschrieben (frueherer Ansatz):
so funktioniert das auch mit Tags, die sich nicht beschreiben lassen bzw.
mit einem anderen Schluessel gesichert sind - es wird nur die (immer
lesbare) physische UID benoetigt.
"""
import ujson as json

DATEI = "tags.json"

_tags = None  # {"<uid_hex>": {"game_uid": str|None, "color": str|None}}


def _laden():
    global _tags
    if _tags is not None:
        return
    try:
        with open(DATEI) as f:
            _tags = json.load(f)
    except (OSError, ValueError):
        _tags = {}


def _speichern():
    try:
        with open(DATEI, "w") as f:
            json.dump(_tags, f)
    except OSError as e:
        print("Konnte", DATEI, "nicht schreiben:", e)


def get(uid_hex):
    _laden()
    return _tags.get(uid_hex)


def upsert_seen(uid_hex):
    """Legt einen neu gesehenen Tag ohne Verknuepfung an, falls noch
    unbekannt. Gibt True zurueck, wenn der Tag neu war."""
    _laden()
    if uid_hex in _tags:
        return False
    _tags[uid_hex] = {"game_uid": None, "color": None}
    _speichern()
    return True


def link(uid_hex, game_uid):
    """Verknuepft (oder loest die Verknuepfung von, falls game_uid leer
    ist) einen bereits bekannten oder neuen Tag mit einer Spiel-UID."""
    _laden()
    entry = _tags.get(uid_hex, {})
    entry["game_uid"] = game_uid or None
    _tags[uid_hex] = entry
    _speichern()


def set_color(uid_hex, color):
    """Setzt (oder loescht, falls color leer ist) die eigene LED-Farbe
    eines Tags. Gibt False zurueck, wenn dieser Tag noch nie gesehen
    wurde."""
    _laden()
    if uid_hex not in _tags:
        return False
    entry = _tags[uid_hex]
    entry["color"] = color or None
    _tags[uid_hex] = entry
    _speichern()
    return True


def to_list():
    _laden()
    return [
        {"uid": uid, "game_uid": daten.get("game_uid"), "color": daten.get("color")}
        for uid, daten in _tags.items()
    ]
