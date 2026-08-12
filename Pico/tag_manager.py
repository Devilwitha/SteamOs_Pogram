"""Verwaltet die Erkennung von RFID-Tags, deren Verknuepfung mit
Spiel-UIDs (siehe tag_store.py) sowie den Meldezustand fuer SteamOS.

Der Pico hat nur einen einzigen zweiten Kern, den MicroPythons `_thread`
fuer genau EINEN zusaetzlichen Thread nutzen kann - ein zweiter
`_thread.start_new_thread()`-Aufruf schlaegt mit `OSError: core1 in use`
fehl. Deshalb betreibt dieses Modul selbst KEINEN eigenen Thread;
stattdessen ruft ping_server.py `poll_once()` regelmaessig aus seinem
einen Hintergrund-Thread auf (zusammen mit dem UDP-Discovery-Server).

Ablauf von poll_once():
- Liegt keine Karte auf: Der zuletzt gelesene Tag bleibt fuer
  TAG_GRACE_MS (Standard 3000 ms) weiterhin als aktuell aufliegend
  gemeldet (get_current()/CURRENT?/TAG?), bevor der Zustand zurueckgesetzt
  wird - der MFRC522 liest eine aufliegende Karte nicht bei jedem Zyklus
  zuverlaessig, ohne diese Toleranz wuerde ein einzelner Fehlversuch
  faelschlich als "Tag entfernt" durchgereicht (u. a. an SteamOS, das
  daraufhin das laufende Spiel beenden wuerde - siehe steamOs/pico_client.py)
  und das LCD wuerde zwischen Spielname und Bereitschafts-Bildschirm
  flackern.
- Liegt eine neue, bisher unbekannte Karte auf: wird in tags.json ohne
  Spiel-Verknuepfung gespeichert (und ist damit fuer die SteamOS-GUI/den
  Status-Server sichtbar).
- Liegt eine Schreibanfrage vor (durch SELECT:<uid> ausgeloest): die
  aufliegende Karte wird mit der gewuenschten Spiel-UID verknuepft.
- Ist die aufliegende Karte mit einer Spiel-UID verknuepft, wird das ueber
  get_tag_status() so lange gemeldet, bis SteamOS es per confirm_started()
  bestaetigt - danach erst wieder bei Tag-Wechsel/-Entfernung. Ein Wechsel
  auf einen anderen Tag wird - anders als das Entfernen - sofort ohne
  Toleranzzeit uebernommen.
- Liegt eine Loeschanfrage vor (durch FORGET ausgeloest, siehe
  request_forget()): die naechste aufgelegte Karte wird komplett aus
  tag_store entfernt (nicht nur entknuepft) statt normal verarbeitet zu
  werden - hat Vorrang vor einer gleichzeitig vorgemerkten
  SELECT-Verknuepfung.

Zusaetzlich kann jedem Tag unabhaengig von der Spiel-Verknuepfung eine
eigene Farbe zugewiesen werden (set_color(), ueber TAGCOLOR:<uid>:<farbe>
aus der SteamOS-GUI). get_current() liefert diese Farbe (mit Vorrang vor
der Farbe des verknuepften Spiels) fuer den Led_Pico, der darueber einen
LED-Streifen in der passenden Farbe ansteuert (siehe ../Led_Pico und
steamOs/pico_client.py).
"""
import time
import _thread

import tag_store
from rfid_reader import RfidStation, uid_to_hex

POLL_INTERVAL_MS = 300
TAG_GRACE_MS = 3000

_lock = _thread.allocate_lock()
_station = None

_pending_write_uid = None
_pending_write_name = None
_pending_forget = False
_current_uid_hex = None
_current_game_uid = None
_sent_uid = None
_reported_uid = None
_last_seen_ms = 0


def init(**spi_kwargs):
    global _station
    _station = RfidStation(**spi_kwargs)


def request_write(game_uid, game_name=None):
    """Merkt eine Spiel-UID (optional mit Anzeigename fuers LCD) zum
    Verknuepfen mit der naechsten aufgelegten Karte vor (ausgeloest durch
    SELECT:<uid>[:<name>])."""
    global _pending_write_uid, _pending_write_name
    _lock.acquire()
    try:
        _pending_write_uid = game_uid
        _pending_write_name = game_name
    finally:
        _lock.release()


def request_forget():
    """Versetzt den Pico in den Loeschmodus: die naechste aufgelegte Karte
    wird beim naechsten erfolgreichen Lesen komplett aus tag_store entfernt
    (nicht nur entknuepft), ausgeloest durch FORGET. Hat Vorrang vor einer
    gleichzeitig vorgemerkten SELECT-Verknuepfung."""
    global _pending_forget
    _lock.acquire()
    try:
        _pending_forget = True
    finally:
        _lock.release()


def set_color(uid_hex, color):
    """Setzt die eigene LED-Farbe eines bereits bekannten Tags (siehe
    ../Led_Pico) - unabhaengig von einer Spiel-Verknuepfung. Gibt False
    zurueck, wenn dieser Tag noch nie gesehen wurde."""
    return tag_store.set_color(uid_hex, color)


def link_existing(uid_hex, game_uid, game_name=None):
    """Verknuepft (game_uid gesetzt) oder loest (game_uid leer) einen
    bereits bekannten Tag, ohne dass er erneut aufgelegt werden muss.
    Gibt False zurueck, wenn dieser Tag noch nie gesehen wurde."""
    global _current_game_uid, _sent_uid, _reported_uid

    if tag_store.get(uid_hex) is None:
        return False

    tag_store.link(uid_hex, game_uid, game_name)

    _lock.acquire()
    if _current_uid_hex == uid_hex:
        _current_game_uid = game_uid or None
        _sent_uid = None
        _reported_uid = None
    _lock.release()
    return True


def get_tag_status():
    """Liefert die zu meldende Spiel-UID, oder None, wenn nichts Neues
    gemeldet werden muss. Merkt sich dabei zugleich (fuers LCD/Status,
    siehe _status_locked()), dass diese UID per TAG? an SteamOS
    uebermittelt wurde."""
    global _sent_uid
    _lock.acquire()
    try:
        if _current_game_uid is not None and _current_game_uid != _reported_uid:
            _sent_uid = _current_game_uid
            return _current_game_uid
        return None
    finally:
        _lock.release()


def _status_locked(game_uid):
    """Meldezustand des uebergebenen Spiel-UID gegenueber SteamOS, fuers
    LCD und den Status-Server. Muss unter _lock aufgerufen werden.
    "erkannt": Tag liegt auf und ist verknuepft, aber SteamOS hat noch
        nicht per TAG? danach gefragt.
    "gesendet": TAG? hat diese UID bereits an SteamOS gemeldet, aber
        STARTED:<uid> steht noch aus.
    "gestartet": SteamOS hat den Spielstart per STARTED:<uid> bestaetigt."""
    if game_uid is None:
        return None
    if game_uid == _reported_uid:
        return "gestartet"
    if game_uid == _sent_uid:
        return "gesendet"
    return "erkannt"


def get_current():
    """Fuer den Status-Server und CURRENT? (siehe ping_server.py): aktuell
    aufliegender Tag (UID, verknuepfte Spiel-UID, Meldezustand gegenueber
    SteamOS sowie eigene Farbe, jeweils falls vorhanden), oder None wenn
    keine Karte aufliegt. Die Farbe wird bewusst nicht im Debounce-Zustand
    gecacht, sondern bei jedem Aufruf frisch aus tag_store gelesen, damit
    eine per TAGCOLOR geaenderte Farbe sofort wirkt, ohne dass der Tag neu
    aufgelegt werden muss."""
    _lock.acquire()
    try:
        if _current_uid_hex is None:
            return None
        uid_hex = _current_uid_hex
        game_uid = _current_game_uid
        status = _status_locked(game_uid)
    finally:
        _lock.release()

    entry = tag_store.get(uid_hex) or {}
    return {
        "uid": uid_hex,
        "game_uid": game_uid,
        "game_name": entry.get("game_name"),
        "color": entry.get("color"),
        "status": status,
    }


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
    global _pending_write_uid, _pending_write_name, _pending_forget, _current_uid_hex, _current_game_uid, _sent_uid, _reported_uid, _last_seen_ms

    if _station is None:
        return

    card_uid = _station.poll()

    if card_uid is None:
        # Nicht sofort zuruecksetzen: eine aufliegende Karte wird vom
        # MFRC522 nicht bei jedem Zyklus zuverlaessig gelesen. Erst wenn
        # seit dem letzten erfolgreichen Lesen TAG_GRACE_MS vergangen sind,
        # gilt der Tag wirklich als entfernt.
        _lock.acquire()
        if _current_uid_hex is not None and time.ticks_diff(time.ticks_ms(), _last_seen_ms) >= TAG_GRACE_MS:
            _current_uid_hex = None
            _current_game_uid = None
            _sent_uid = None
            _reported_uid = None
        _lock.release()
        return

    uid_hex = uid_to_hex(card_uid)

    _lock.acquire()
    _last_seen_ms = time.ticks_ms()
    forget_now = _pending_forget
    _lock.release()

    if forget_now:
        # Loeschmodus: diese Karte wird komplett entfernt statt normal
        # verarbeitet zu werden - auch eine bestehende Spiel-Verknuepfung
        # ist damit weg. Weder upsert_seen() noch die Link-Logik unten
        # sollen den Tag danach in derselben Runde wieder anlegen.
        tag_store.forget(uid_hex)
        print("Tag", uid_hex, "geloescht")
        _lock.acquire()
        _pending_forget = False
        _current_uid_hex = None
        _current_game_uid = None
        _sent_uid = None
        _reported_uid = None
        _lock.release()
        return

    if tag_store.upsert_seen(uid_hex):
        print("Neuer Tag erkannt:", uid_hex)

    _lock.acquire()
    pending = _pending_write_uid
    pending_name = _pending_write_name
    _lock.release()

    if pending:
        tag_store.link(uid_hex, pending, pending_name)
        print("Tag", uid_hex, "verknuepft mit Spiel-UID", pending)
        _lock.acquire()
        if _pending_write_uid == pending:
            _pending_write_uid = None
            _pending_write_name = None
        _lock.release()

    entry = tag_store.get(uid_hex) or {}
    game_uid = entry.get("game_uid")

    _lock.acquire()
    if uid_hex != _current_uid_hex:
        _sent_uid = None
        _reported_uid = None
    _current_uid_hex = uid_hex
    _current_game_uid = game_uid
    _lock.release()
