"""Verwaltet die Erkennung von RFID-Tags, deren Verknuepfung mit
Spiel-UIDs (siehe tag_store.py) sowie den Meldezustand fuer SteamOS.

Der Pico hat nur einen einzigen zweiten Kern, den MicroPythons `_thread`
fuer genau EINEN zusaetzlichen Thread nutzen kann - ein zweiter
`_thread.start_new_thread()`-Aufruf schlaegt mit `OSError: core1 in use`
fehl. Deshalb betreibt dieses Modul selbst KEINEN eigenen Thread;
stattdessen ruft ping_server.py `poll_once()` regelmaessig aus seinem
einen Hintergrund-Thread auf (zusammen mit dem UDP-Discovery-Server).

Ablauf von poll_once():
- Liegt keine Karte auf: Zustand zuruecksetzen, damit die naechste
  Erkennung (auch desselben Tags) sich erneut meldet.
- Liegt eine neue, bisher unbekannte Karte auf: wird in tags.json ohne
  Spiel-Verknuepfung gespeichert (und ist damit fuer die SteamOS-GUI/den
  Status-Server sichtbar).
- Liegt eine Schreibanfrage vor (durch SELECT:<uid> ausgeloest): die
  aufliegende Karte wird mit der gewuenschten Spiel-UID verknuepft.
- Ist die aufliegende Karte mit einer Spiel-UID verknuepft, wird das ueber
  get_tag_status() so lange gemeldet, bis SteamOS es per confirm_started()
  bestaetigt - danach erst wieder bei Tag-Wechsel/-Entfernung.

Zusaetzlich kann jedem Tag unabhaengig von der Spiel-Verknuepfung eine
eigene Farbe zugewiesen werden (set_color(), ueber TAGCOLOR:<uid>:<farbe>
aus der SteamOS-GUI). get_current() liefert diese Farbe (mit Vorrang vor
der Farbe des verknuepften Spiels) fuer den Led_Pico, der darueber einen
LED-Streifen in der passenden Farbe ansteuert (siehe ../Led_Pico und
steamOs/pico_client.py).
"""
import _thread

import tag_store
from rfid_reader import RfidStation, uid_to_hex

POLL_INTERVAL_MS = 300

_lock = _thread.allocate_lock()
_station = None

_pending_write_uid = None
_current_uid_hex = None
_current_game_uid = None
_reported_uid = None


def init(**spi_kwargs):
    global _station
    _station = RfidStation(**spi_kwargs)


def request_write(game_uid):
    """Merkt eine Spiel-UID zum Verknuepfen mit der naechsten aufgelegten
    Karte vor (ausgeloest durch SELECT:<uid>)."""
    global _pending_write_uid
    _lock.acquire()
    try:
        _pending_write_uid = game_uid
    finally:
        _lock.release()


def set_color(uid_hex, color):
    """Setzt die eigene LED-Farbe eines bereits bekannten Tags (siehe
    ../Led_Pico) - unabhaengig von einer Spiel-Verknuepfung. Gibt False
    zurueck, wenn dieser Tag noch nie gesehen wurde."""
    return tag_store.set_color(uid_hex, color)


def link_existing(uid_hex, game_uid):
    """Verknuepft (game_uid gesetzt) oder loest (game_uid leer) einen
    bereits bekannten Tag, ohne dass er erneut aufgelegt werden muss.
    Gibt False zurueck, wenn dieser Tag noch nie gesehen wurde."""
    global _current_game_uid, _reported_uid

    if tag_store.get(uid_hex) is None:
        return False

    tag_store.link(uid_hex, game_uid)

    _lock.acquire()
    if _current_uid_hex == uid_hex:
        _current_game_uid = game_uid or None
        _reported_uid = None
    _lock.release()
    return True


def get_tag_status():
    """Liefert die zu meldende Spiel-UID, oder None, wenn nichts Neues
    gemeldet werden muss."""
    _lock.acquire()
    try:
        if _current_game_uid is not None and _current_game_uid != _reported_uid:
            return _current_game_uid
        return None
    finally:
        _lock.release()


def get_current():
    """Fuer den Status-Server und CURRENT? (siehe ping_server.py): aktuell
    aufliegender Tag (UID, verknuepfte Spiel-UID sowie eigene Farbe,
    jeweils falls vorhanden), oder None wenn keine Karte aufliegt. Die
    Farbe wird bewusst nicht im Debounce-Zustand gecacht, sondern bei
    jedem Aufruf frisch aus tag_store gelesen, damit eine per TAGCOLOR
    geaenderte Farbe sofort wirkt, ohne dass der Tag neu aufgelegt werden
    muss."""
    _lock.acquire()
    try:
        if _current_uid_hex is None:
            return None
        uid_hex = _current_uid_hex
        game_uid = _current_game_uid
    finally:
        _lock.release()

    entry = tag_store.get(uid_hex) or {}
    return {"uid": uid_hex, "game_uid": game_uid, "color": entry.get("color")}


def list_tags():
    """Alle bisher gesehenen Tags mit ihrer (ggf. fehlenden) Spiel-Verknuepfung."""
    return tag_store.to_list()


def confirm_started(game_uid):
    """SteamOS bestaetigt, dass das Spiel gestartet wurde. Gibt True
    zurueck, wenn die UID noch zur aktuell aufliegenden Karte passt."""
    global _reported_uid
    _lock.acquire()
    try:
        if game_uid == _current_game_uid:
            _reported_uid = game_uid
            return True
        return False
    finally:
        _lock.release()


def poll_once():
    """Fuehrt einen einzelnen Lesezyklus aus. Ohne initialisierten
    RFID-Leser (kein RC522 angeschlossen bzw. init() fehlgeschlagen) ein
    No-Op."""
    global _pending_write_uid, _current_uid_hex, _current_game_uid, _reported_uid

    if _station is None:
        return

    card_uid = _station.poll()

    if card_uid is None:
        _lock.acquire()
        _current_uid_hex = None
        _current_game_uid = None
        _reported_uid = None
        _lock.release()
        return

    uid_hex = uid_to_hex(card_uid)
    if tag_store.upsert_seen(uid_hex):
        print("Neuer Tag erkannt:", uid_hex)

    _lock.acquire()
    pending = _pending_write_uid
    _lock.release()

    if pending:
        tag_store.link(uid_hex, pending)
        print("Tag", uid_hex, "verknuepft mit Spiel-UID", pending)
        _lock.acquire()
        if _pending_write_uid == pending:
            _pending_write_uid = None
        _lock.release()

    entry = tag_store.get(uid_hex) or {}
    game_uid = entry.get("game_uid")

    _lock.acquire()
    if uid_hex != _current_uid_hex:
        _reported_uid = None
    _current_uid_hex = uid_hex
    _current_game_uid = game_uid
    _lock.release()
