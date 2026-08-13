"""Session-Zustand fuer den Web-Cover-Maker (/maker).

Jeder Browser bekommt beim ersten Aufruf von /maker ein eigenes
Session-Cookie und damit eine eigene, isolierte MakerSession im
Server-Speicher (siehe SESSIONS) - unabhaengig von allen anderen
Benutzern, genau wie ein frisch gestartetes cover_maker.py-Fenster auf dem
Desktop. PanelState bildet dieselben Felder wie die Panel-Klasse in
cover_maker.py nach (inkl. Rueckseiten-Text/Ratings/Logos), damit
cover_render.py beide identisch rendern kann.

Sessions leben nur im Prozessspeicher (kein Neustart-persistentes Backing-
Store noetig fuer dieses lokale Tool) und werden nach SESSION_TTL_SECONDS
Inaktivitaet aufgeraeumt.
"""
import secrets
import threading
import time
from http.cookies import SimpleCookie

import cover_render

SESSION_COOKIE = "cm_session"
SESSION_TTL_SECONDS = 4 * 60 * 60  # 4 Stunden Inaktivitaet -> Session verwerfen

# Reihenfolge/-Rollen wie PANEL_DEFAULTS/FRONT_PANEL_INDEX/BACK_PANEL_INDEX/
# WRAP_FRONT_DEFAULT_INDEX in cover_maker.py: Seite1 | Front | Seite2 | Rueckseite.
MAKER_PANEL_DEFAULTS = [
    {"name": "Seite 1", "width_cm": 1.0, "is_front": False, "is_back": False, "wrap_front": False},
    {"name": "Front", "width_cm": 6.0, "is_front": True, "is_back": False, "wrap_front": False},
    {"name": "Seite 2", "width_cm": 1.0, "is_front": False, "is_back": False, "wrap_front": True},
    {"name": "Rueckseite", "width_cm": 6.0, "is_front": False, "is_back": True, "wrap_front": False},
]

_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


class PanelState:
    """Spiegelt die Panel-Klasse aus cover_maker.py (nur ohne Tkinter-
    Bindung) - dieselben Attributnamen, damit cover_render.py identisch
    funktioniert."""

    def __init__(self, name, width_cm, is_front=False, is_back=False, wrap_front=False):
        self.name = name
        self.width_cm = width_cm
        self.mode = cover_render.MODE_CROP
        self.pil_image = None
        self.image_name = None
        self.center_x = 0.5
        self.center_y = 0.5
        self.is_front = is_front
        self.is_back = is_back
        self.wrap_front = wrap_front

        # Rueckseiten-Felder (nur relevant wenn is_back)
        self.art_ratio_percent = 50.0
        self.min_title = cover_render.DEFAULT_MIN_TITLE
        self.rec_title = cover_render.DEFAULT_REC_TITLE
        self.min_text_content = cover_render.DEFAULT_REQUIREMENTS_TEXT
        self.rec_text_content = cover_render.DEFAULT_REQUIREMENTS_TEXT
        self.logos = []  # Liste von PIL.Image (RGBA-faehig)
        self.logo_names = []
        self.show_compat = True
        self.steamdeck_rating = cover_render.RATING_OPTIONS[0]
        self.steammachine_rating = cover_render.RATING_OPTIONS[0]
        self.input_kbm = False
        self.input_controller = False


def new_default_panels():
    return [
        PanelState(d["name"], d["width_cm"], d["is_front"], d["is_back"], d["wrap_front"])
        for d in MAKER_PANEL_DEFAULTS
    ]


class MakerSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.height_cm = 10.0
        self.dpi = 300
        self.banner_image = None
        self.banner_name = None
        self.banner_height_cm = 1.0
        self.panels = new_default_panels()
        self.last_saved_cover_id = None
        self.last_touch = time.time()


def _purge_expired():
    cutoff = time.time() - SESSION_TTL_SECONDS
    expired = [sid for sid, s in _SESSIONS.items() if s.last_touch < cutoff]
    for sid in expired:
        del _SESSIONS[sid]


def get_session_id(headers) -> str | None:
    raw = headers.get("Cookie")
    if not raw:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return None
    morsel = cookie.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def get_or_create_session(headers):
    """Liefert (session_id, MakerSession, is_new). is_new=True bedeutet,
    der Aufrufer muss das Session-Cookie auf der Antwort setzen."""
    sid = get_session_id(headers)
    with _SESSIONS_LOCK:
        _purge_expired()
        if sid and sid in _SESSIONS:
            session = _SESSIONS[sid]
            session.last_touch = time.time()
            return sid, session, False

        sid = secrets.token_hex(20)
        session = MakerSession()
        _SESSIONS[sid] = session
        return sid, session, True


def session_count() -> int:
    with _SESSIONS_LOCK:
        return len(_SESSIONS)
