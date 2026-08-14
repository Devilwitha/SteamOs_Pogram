#!/usr/bin/env python3
"""Cover Store - lokaler Webserver mit zwei Seiten:

- "/"      Store: durchsucht/zeigt alle Cover (aus cover_maker.py UND aus
           dem Web-Maker gespeichert) mit Vorschaubildern, Suche, Download,
           sowie direktem Hochladen fertiger Cover-Bilder.
- "/maker" Cover Maker: 1:1-Web-Variante von cover_maker.py - dieselbe
           Panel-Logik (Front/Seite1/Seite2/Rueckseite, Zuschnitt per Ziehen,
           Banner, Rueckseite mit Systemanforderungen/Kompatibilitaets-
           Badges/Eingabegeraete-Icons/Firmenlogos, Banner-Vorlagen) ueber
           tools/cover_maker/cover_render.py (dieselbe Rendering-Bibliothek
           wie die Desktop-App - identisches Ergebnisbild). Jeder Browser
           bekommt beim ersten Aufruf ein eigenes Session-Cookie und damit
           eine eigene, von anderen Benutzern unabhaengige Instanz (siehe
           maker_state.py) - mehrere Leute koennen gleichzeitig eigene
           Cover bauen, ohne sich gegenseitig zu beeinflussen.

Nutzt dieselbe Datenbank wie cover_maker.py/assign_game.py
(tools/cover_maker/covers.db, Tabellen "covers" und "banner_templates").

Nutzt nur die Python-Standardbibliothek + Pillow (bereits Abhaengigkeit von
cover_maker.py) - kein Flask/Django noetig.

Start (Windows):  python cover_store_server.py
Danach im Browser http://127.0.0.1:8090 oeffnen - wird normalerweise
automatisch geoeffnet. Server ist standardmaessig nur lokal erreichbar.
"""
import html
import http.server
import io
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import uuid
import webbrowser
from http.cookies import SimpleCookie
from pathlib import Path

from PIL import Image

SERVER_DIR = Path(__file__).resolve().parent
COVER_MAKER_DIR = SERVER_DIR.parent
REPO_ROOT = COVER_MAKER_DIR.parent.parent

sys.path.insert(0, str(COVER_MAKER_DIR))
import cover_render  # noqa: E402 - framework-unabhaengig, keine Tkinter-Abhaengigkeit
import maker_state  # noqa: E402

DB_PATH = COVER_MAKER_DIR / "covers.db"
GAMES_DB_PATH = REPO_ROOT / "steamOs" / "games.db"
UPLOAD_DIR = SERVER_DIR / "uploads"
THUMB_DIR = SERVER_DIR / "thumbnails"
BANNER_TEMPLATES_DIR = COVER_MAKER_DIR / "banner_templates"

HOST = "127.0.0.1"
PORT = 8090

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
THUMB_MAX = 320
PREVIEW_MAX = (1100, 700)

with open(SERVER_DIR / "index.html", encoding="utf-8") as _f:
    STORE_TEMPLATE = _f.read()
with open(SERVER_DIR / "maker.html", encoding="utf-8") as _f:
    MAKER_TEMPLATE = _f.read()


def _escape(text):
    return html.escape(str(text if text is not None else ""), quote=True)


# -- Datenbank (covers + banner_templates) ------------------------------
def ensure_covers_db(conn):
    """Gleiches Schema wie in cover_maker.py - eigenstaendig gehalten, damit
    dieser Server ohne Tkinter-Abhaengigkeit lauffaehig bleibt. Beide Tools
    teilen sich dieselbe Datei (tools/cover_maker/covers.db), Cover UND
    Banner-Vorlagen tauchen daher unabhaengig davon auf, wo sie erstellt
    wurden."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS covers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            width_cm REAL,
            height_cm REAL,
            dpi INTEGER,
            created_at TEXT NOT NULL,
            game_uid TEXT,
            game_name TEXT,
            game_appid INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banner_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            console TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def fetch_covers(query=None):
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        conn.row_factory = sqlite3.Row
        if query:
            like = f"%{query}%"
            return conn.execute(
                """
                SELECT * FROM covers
                WHERE game_name LIKE ? COLLATE NOCASE
                   OR file_path LIKE ? COLLATE NOCASE
                ORDER BY created_at DESC
                """,
                (like, like),
            ).fetchall()
        return conn.execute("SELECT * FROM covers ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()


def fetch_cover(cover_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM covers WHERE id = ?", (cover_id,)).fetchone()
    finally:
        conn.close()


def fetch_games():
    if not GAMES_DB_PATH.is_file():
        return []
    conn = sqlite3.connect(GAMES_DB_PATH)
    try:
        return conn.execute(
            "SELECT uid, appid, name FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()


def insert_cover(file_path, game_uid, game_name, game_appid):
    width_cm = height_cm = dpi = None
    try:
        with Image.open(file_path) as img:
            dpi_x = img.info.get("dpi", (None, None))[0]
            if dpi_x:
                dpi = round(dpi_x)
                width_cm = round(img.width / dpi_x * 2.54, 2)
                height_cm = round(img.height / dpi_x * 2.54, 2)
    except Exception:
        pass

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        cur = conn.execute(
            """
            INSERT INTO covers (file_path, width_cm, height_cm, dpi, created_at, game_uid, game_name, game_appid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(Path(file_path).resolve()),
                width_cm,
                height_cm,
                dpi,
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                game_uid or None,
                game_name or None,
                game_appid,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def fetch_banner_templates():
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        return conn.execute(
            "SELECT id, name, file_path, console FROM banner_templates ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()


def fetch_banner_template(template_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM banner_templates WHERE id = ?", (template_id,)
        ).fetchone()
    finally:
        conn.close()


def save_banner_template(name, file_path, console):
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_covers_db(conn)
        conn.execute(
            "INSERT INTO banner_templates (name, file_path, console, created_at) VALUES (?, ?, ?, ?)",
            (name, str(Path(file_path).resolve()), console, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def get_thumbnail_bytes(cover_id, file_path):
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb_path = THUMB_DIR / f"{cover_id}.jpg"
    src = Path(file_path)

    if thumb_path.is_file() and src.is_file() and thumb_path.stat().st_mtime >= src.stat().st_mtime:
        return thumb_path.read_bytes()

    if not src.is_file():
        return None

    try:
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
            img.save(thumb_path, "JPEG", quality=85)
        return thumb_path.read_bytes()
    except Exception:
        return None


def _parse_multipart(content_type, body):
    """Minimaler multipart/form-data-Parser (nur fuer die hier verwendeten
    Upload-Faelle aus dem Browser), analog zu steamOs/gui/gui_server.py.
    Mehrere Dateien mit demselben Feldnamen (z. B. Logo-Mehrfachauswahl)
    landen automatisch als Liste im Ergebnis-Dict."""
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        return {}
    boundary = ("--" + match.group(1)).encode()

    fields = {}
    for chunk in body.split(boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, sep, content = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]

        headers_text = header_blob.decode(errors="replace")
        name_match = re.search(r'name="([^"]*)"', headers_text)
        if not name_match:
            continue
        field_name = name_match.group(1)

        filename_match = re.search(r'filename="([^"]*)"', headers_text)
        if filename_match:
            if not filename_match.group(1):
                continue  # leeres <input type=file> ohne Auswahl -> ignorieren
            value = {"filename": filename_match.group(1), "content": content}
        else:
            value = content.decode(errors="replace")
        fields.setdefault(field_name, []).append(value)
    return fields


# -- Store-Seite ("/") ----------------------------------------------------
def _render_game_options(selected=""):
    options = [f'<option value=""{" selected" if not selected else ""}>(kein Spiel verknuepfen)</option>']
    for uid, appid, name in fetch_games():
        sel = " selected" if uid == selected else ""
        options.append(f'<option value="{_escape(uid)}" data-appid="{appid or 0}"{sel}>{_escape(name)}</option>')
    return "".join(options)


def _render_cards(covers):
    if not covers:
        return '<p class="empty-store">Keine Cover gefunden.</p>'

    cards = []
    for cover in covers:
        thumb_url = f"/thumb/{cover['id']}"
        file_exists = Path(cover["file_path"]).is_file()
        game_html = (
            f'<span class="linked">{_escape(cover["game_name"])}</span>'
            if cover["game_name"]
            else '<span class="unlinked">nicht verknuepft</span>'
        )
        dims = (
            f'{cover["width_cm"]:g}&times;{cover["height_cm"]:g}&nbsp;cm &middot; {cover["dpi"]}&nbsp;dpi'
            if cover["width_cm"] and cover["height_cm"]
            else ""
        )
        created = _escape(cover["created_at"]).replace("T", " ")

        if file_exists:
            actions = (
                f'<a class="btn" href="/view/{cover["id"]}" target="_blank">ANSEHEN</a>'
                f'<a class="btn secondary" href="/download/{cover["id"]}">HERUNTERLADEN</a>'
            )
        else:
            actions = '<span class="missing">Datei fehlt</span>'

        cards.append(
            '<div class="card">'
            f'<a href="/view/{cover["id"]}" target="_blank" class="thumb-frame">'
            f'<img src="{thumb_url}" alt="Cover #{cover["id"]}" loading="lazy">'
            "</a>"
            '<div class="card-body">'
            f"<div class='card-title'>{game_html}</div>"
            f"<div class='card-meta'>{dims}</div>"
            f"<div class='card-meta dim'>{created}</div>"
            f"<div class='card-actions'>{actions}</div>"
            "</div>"
            "</div>"
        )
    return "".join(cards)


def render_store_page(query="", upload_message=""):
    covers = fetch_covers(query.strip() if query else None)
    page = STORE_TEMPLATE.replace("__QUERY__", _escape(query))
    page = page.replace("__UPLOAD_MESSAGE__", upload_message)
    page = page.replace("__GAME_OPTIONS__", _render_game_options())
    page = page.replace("__CARDS__", _render_cards(covers))
    page = page.replace("__COUNT__", str(len(covers)))
    return page


# -- Cover-Maker-Seite ("/maker") -----------------------------------------
def _render_back_editor(index, panel):
    steamdeck_options = "".join(
        f'<option value="{_escape(r)}"{" selected" if r == panel.steamdeck_rating else ""}>{_escape(r)}</option>'
        for r in cover_render.RATING_OPTIONS
    )
    steammachine_options = "".join(
        f'<option value="{_escape(r)}"{" selected" if r == panel.steammachine_rating else ""}>{_escape(r)}</option>'
        for r in cover_render.RATING_OPTIONS
    )
    if panel.logo_names:
        logos_html = "".join(
            '<li>'
            f'<span>{_escape(name)}</span>'
            f'<form method="POST" action="/maker/panel/{index}/logos/remove" class="inline-row">'
            f'<input type="hidden" name="logo_index" value="{i}">'
            '<button type="submit" class="btn secondary logo-remove">&times;</button>'
            '</form></li>'
            for i, name in enumerate(panel.logo_names)
        )
    else:
        logos_html = "<li class='hint-inline'>Keine Logos</li>"

    return f"""
      <div class="back-editor">
        <h2 style="margin-bottom:10px">Rueckseiten-Inhalt</h2>
        <form method="POST" action="/maker/panel/{index}/back">
          <div class="field-row">
            <div class="field"><label>Bildanteil oben (%)</label>
              <input type="text" name="art_ratio_percent" value="{panel.art_ratio_percent:g}"></div>
            <div class="field"><label>Minimum-Titel</label>
              <input type="text" name="min_title" value="{_escape(panel.min_title)}"></div>
            <div class="field"><label>Empfohlen-Titel</label>
              <input type="text" name="rec_title" value="{_escape(panel.rec_title)}"></div>
          </div>
          <div class="field-row">
            <div class="field"><label>Minimum-Text</label>
              <textarea name="min_text_content" rows="5">{_escape(panel.min_text_content)}</textarea></div>
            <div class="field"><label>Empfohlen-Text</label>
              <textarea name="rec_text_content" rows="5">{_escape(panel.rec_text_content)}</textarea></div>
          </div>
          <label class="checkbox-label"><input type="checkbox" name="show_compat" {"checked" if panel.show_compat else ""}> Steam-Kompatibilitaet anzeigen</label>
          <div class="field-row">
            <div class="field"><label>Steam Deck</label><select name="steamdeck_rating">{steamdeck_options}</select></div>
            <div class="field"><label>Steam Machine</label><select name="steammachine_rating">{steammachine_options}</select></div>
          </div>
          <label class="checkbox-label"><input type="checkbox" name="input_kbm" {"checked" if panel.input_kbm else ""}> Maus &amp; Tastatur noetig/empfohlen</label>
          <label class="checkbox-label"><input type="checkbox" name="input_controller" {"checked" if panel.input_controller else ""}> Controller noetig/empfohlen</label>
          <button type="submit">RUECKSEITE UEBERNEHMEN</button>
        </form>

        <div class="field" style="margin-top:12px">
          <label>Firmenlogos (werden unten in einer Reihe angezeigt)</label>
          <ul class="logo-list">{logos_html}</ul>
          <form method="POST" action="/maker/panel/{index}/logos/add" enctype="multipart/form-data">
            <input type="file" name="logo_files" accept=".png,.jpg,.jpeg,.webp,.bmp" multiple onchange="this.form.submit()">
          </form>
        </div>
      </div>
    """


def _render_panel_card(session, index):
    panel = session.panels[index]
    ts = time.time()

    mode_options = "".join(
        f'<option value="{_escape(m)}"{" selected" if m == panel.mode else ""}>{_escape(m)}</option>'
        for m in cover_render.FIT_MODES
    )
    position_options = "".join(
        f'<option value="{p}"{" selected" if p == index else ""}>{p + 1}</option>'
        for p in range(len(session.panels))
    )
    image_label = _escape(panel.image_name) if panel.image_name else "kein Bild"
    aspect = (panel.width_cm / session.height_cm) if session.height_cm else 1.0
    aspect = max(0.15, min(6.0, aspect))
    img_src = f"/maker/panel_source/{index}?t={ts}" if panel.pil_image is not None else "/maker/blank_source"

    wrap_html = ""
    if not panel.is_front:
        wrap_checked = "checked" if panel.wrap_front else ""
        wrap_html = (
            f'<form method="POST" action="/maker/panel/{index}/toggle_wrap" class="inline-row">'
            f'<label class="checkbox-label"><input type="checkbox" name="wrap_front" {wrap_checked} '
            'onchange="this.form.submit()"> Frontbild fortsetzen (Wrap)</label></form>'
        )

    back_checked = "checked" if panel.is_back else ""
    back_editor = _render_back_editor(index, panel) if panel.is_back else ""

    return f"""
    <div class="panel maker-panel">
      <div class="panel-card-header">
        <h2 style="margin:0">Panel {index + 1} &middot; {_escape(panel.name)}</h2>
        <form method="POST" action="/maker/panel/{index}/position" class="inline-row">
          <label class="field-inline-label">Position</label>
          <select name="new_index" onchange="this.form.submit()">{position_options}</select>
        </form>
      </div>

      <div class="crop-box" data-index="{index}" data-cx="{panel.center_x}" data-cy="{panel.center_y}" style="aspect-ratio:{aspect:.3f}">
        <img src="{img_src}" alt="Panel {index + 1}" draggable="false">
        <div class="crop-hint">Ziehen zum Verschieben</div>
      </div>

      <form method="POST" action="/maker/panel/{index}/upload" enctype="multipart/form-data" class="field">
        <label>Bild</label>
        <input type="file" name="image" accept=".png,.jpg,.jpeg,.webp,.bmp" onchange="this.form.submit()">
        <span class="file-current">{image_label}</span>
      </form>

      <div class="field-row">
        <form method="POST" action="/maker/panel/{index}/settings" class="field-row" style="flex:1;margin:0">
          <div class="field"><label>Name</label>
            <input type="text" name="name" value="{_escape(panel.name)}" onchange="this.form.submit()"></div>
          <div class="field"><label>Breite (cm)</label>
            <input type="text" name="width_cm" value="{panel.width_cm:g}" onchange="this.form.submit()"></div>
          <div class="field"><label>Modus</label>
            <select name="mode" onchange="this.form.submit()">{mode_options}</select></div>
        </form>
      </div>

      <form method="POST" action="/maker/panel/{index}/toggle_back" class="inline-row">
        <label class="checkbox-label"><input type="checkbox" name="is_back" {back_checked} onchange="this.form.submit()"> Ist Rueckseite</label>
      </form>
      {wrap_html}
      {back_editor}
    </div>
    """


def _render_banner_section(session):
    banner_label = _escape(session.banner_name) if session.banner_name else "kein Banner"
    templates = fetch_banner_templates()
    template_options = '<option value="">Vorlage waehlen...</option>' + "".join(
        f'<option value="{row[0]}">{_escape(row[1])} [{_escape(row[3] or "?")}]</option>' for row in templates
    )
    console_options = "".join(f'<option value="{_escape(c)}">{_escape(c)}</option>' for c in cover_render.CONSOLE_OPTIONS)

    return f"""
    <div class="panel section">
      <h2 style="margin-bottom:14px">Banner (optional, ueberlagert alle Panels oben ausser Rueckseiten)</h2>
      <div class="field-row">
        <form method="POST" action="/maker/banner/upload" enctype="multipart/form-data" class="field">
          <label>Banner-Bild</label>
          <input type="file" name="banner_image" accept=".png,.jpg,.jpeg,.webp,.bmp" onchange="this.form.submit()">
          <span class="file-current">{banner_label}</span>
        </form>
        <form method="POST" action="/maker/banner/height" class="field">
          <label>Banner-Hoehe (cm)</label>
          <input type="text" name="banner_height_cm" value="{session.banner_height_cm:g}" onchange="this.form.submit()">
        </form>
        <form method="POST" action="/maker/banner/clear" class="field" style="justify-content:flex-end">
          <button type="submit" class="btn secondary">ENTFERNEN</button>
        </form>
      </div>
      <div class="field-row">
        <form method="POST" action="/maker/banner/save_template" class="field-row" style="flex:2;margin:0">
          <div class="field"><label>Vorlagen-Name</label><input type="text" name="template_name" placeholder="z. B. Steam-Leiste"></div>
          <div class="field"><label>Konsole</label><select name="console">{console_options}</select></div>
          <div class="field" style="justify-content:flex-end"><button type="submit">ALS VORLAGE SPEICHERN</button></div>
        </form>
        <form method="POST" action="/maker/banner/load_template" class="field-row" style="flex:1;margin:0">
          <div class="field"><label>Gespeicherte Vorlagen</label><select name="template_id">{template_options}</select></div>
          <div class="field" style="justify-content:flex-end"><button type="submit">LADEN</button></div>
        </form>
      </div>
    </div>
    """


def _render_layout_json(session):
    front_index = next((i for i, p in enumerate(session.panels) if p.is_front), 0)
    panels = [
        {
            "index": i,
            "widthCm": p.width_cm,
            "isBack": p.is_back,
            "isFront": p.is_front,
            "wrapFront": p.wrap_front,
            "centerX": p.center_x,
            "centerY": p.center_y,
        }
        for i, p in enumerate(session.panels)
    ]
    return json.dumps({"panels": panels, "frontIndex": front_index})


def render_maker_page(session, build_message=""):
    with session.lock:
        panels_html = "".join(_render_panel_card(session, i) for i in range(len(session.panels)))
        banner_html = _render_banner_section(session)
        height_cm = session.height_cm
        dpi = session.dpi
        layout_json = _render_layout_json(session)

    page = MAKER_TEMPLATE.replace("__BUILD_MESSAGE__", build_message)
    page = page.replace("__HEIGHT_CM__", f"{height_cm:g}")
    page = page.replace("__DPI__", str(dpi))
    page = page.replace("__BANNER_SECTION__", banner_html)
    page = page.replace("__PANELS_SECTION__", panels_html)
    page = page.replace("__GAME_OPTIONS__", _render_game_options())
    page = page.replace("__PREVIEW_TS__", str(time.time()))
    page = page.replace("__LAYOUT_JSON__", layout_json)
    return page


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    # -- Session-/Cookie-Helfer ------------------------------------------
    def _maybe_set_cookie(self):
        if getattr(self, "_session_is_new", False):
            cookie = SimpleCookie()
            cookie[maker_state.SESSION_COOKIE] = self._session_id
            cookie[maker_state.SESSION_COOKIE]["path"] = "/"
            cookie[maker_state.SESSION_COOKIE]["httponly"] = True
            self.send_header("Set-Cookie", cookie[maker_state.SESSION_COOKIE].OutputString())
            self._session_is_new = False

    def _load_session(self):
        sid, session, is_new = maker_state.get_or_create_session(self.headers)
        self._session_id = sid
        self._session_is_new = is_new
        return session

    def _read_form(self):
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b""
        if content_type.startswith("multipart/form-data"):
            return _parse_multipart(content_type, raw_body)
        return {k: v for k, v in urllib.parse.parse_qs(raw_body.decode(errors="replace")).items()}

    # -- Routing -----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = urllib.parse.parse_qs(parsed.query)

        if not parts:
            self._respond_html(render_store_page(query=query.get("q", [""])[0]))
            return

        if parts[0] == "maker":
            self._dispatch_maker_get(parts[1:], query)
            return

        if parts[0] == "thumb" and len(parts) == 2 and parts[1].isdigit():
            self._serve_thumbnail(int(parts[1]))
            return

        if parts[0] == "download" and len(parts) == 2 and parts[1].isdigit():
            self._serve_file(int(parts[1]), inline=False)
            return

        if parts[0] == "view" and len(parts) == 2 and parts[1].isdigit():
            self._serve_file(int(parts[1]), inline=True)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if parts[:1] == ["maker"]:
            self._dispatch_maker_post(parts[1:])
            return

        if self.path == "/upload":
            form = self._read_form()
            message = self._handle_upload(form)
            self._respond_html(render_store_page(upload_message=message))
            return

        self.send_response(404)
        self.end_headers()

    # -- Store: Upload -------------------------------------------------
    def _handle_upload(self, form):
        upload = form.get("cover_file", [None])[0]
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return '<div class="message error">Bitte eine Bilddatei auswaehlen.</div>'

        ext = Path(upload["filename"]).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return f'<div class="message error">Nicht unterstuetztes Bildformat: {_escape(ext or "(keine Endung)")}</div>'

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
        dest.write_bytes(upload["content"])

        game_uid = (form.get("game_uid", [""])[0] or "").strip()
        game_name = None
        game_appid = None
        if game_uid:
            for uid, appid, name in fetch_games():
                if uid == game_uid:
                    game_name, game_appid = name, appid
                    break

        cover_id = insert_cover(dest, game_uid, game_name, game_appid)
        linked = f" und mit '{_escape(game_name)}' verknuepft" if game_name else ""
        return f'<div class="message success">Cover #{cover_id} hochgeladen{linked}.</div>'

    # -- Cover Maker: GET ------------------------------------------------
    def _dispatch_maker_get(self, rest, query):
        session = self._load_session()

        if not rest:
            saved_id = query.get("saved", [None])[0]
            message = ""
            if saved_id:
                message = (
                    f'<div class="message success">Cover #{_escape(saved_id)} im Store gespeichert.<br>'
                    f'<a class="btn" href="/view/{_escape(saved_id)}" target="_blank">ANSEHEN</a> '
                    f'<a class="btn secondary" href="/">ZUM STORE</a></div>'
                )
            self._respond_html(render_maker_page(session, build_message=message))
            return

        if rest == ["preview"]:
            self._serve_combined_preview(session)
            return

        if rest == ["blank_source"]:
            self._serve_blank_source()
            return

        if len(rest) == 2 and rest[0] == "panel_source" and rest[1].isdigit():
            self._serve_panel_source(session, int(rest[1]))
            return

        self.send_response(404)
        self._maybe_set_cookie()
        self.end_headers()

    def _serve_combined_preview(self, session):
        with session.lock:
            img = cover_render.build_combined_image(
                session.panels, session.height_cm, session.dpi, session.banner_image, session.banner_height_cm
            )
        img.thumbnail(PREVIEW_MAX, Image.LANCZOS)
        self._respond_image_from_pil(img)

    def _serve_panel_source(self, session, index):
        with session.lock:
            if index < 0 or index >= len(session.panels):
                self.send_response(404)
                self._maybe_set_cookie()
                self.end_headers()
                return
            image = session.panels[index].pil_image
        if image is None:
            self._serve_blank_source()
            return
        self._respond_image_from_pil(image)

    def _serve_blank_source(self):
        img = Image.new("RGB", (4, 4), "#0c1017")
        self._respond_image_from_pil(img)

    def _respond_image_from_pil(self, pil_image):
        buf = io.BytesIO()
        pil_image.convert("RGB").save(buf, "JPEG", quality=88)
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_set_cookie()
        self.end_headers()
        self.wfile.write(data)

    # -- Cover Maker: POST -----------------------------------------------
    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self._maybe_set_cookie()
        self.end_headers()

    def _respond_json(self, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._maybe_set_cookie()
        self.end_headers()
        self.wfile.write(encoded)

    def _dispatch_maker_post(self, rest):
        session = self._load_session()
        form = self._read_form()

        def field(name, default=""):
            return (form.get(name, [default]) or [default])[0]

        def as_float(name, default):
            try:
                return float(str(field(name, str(default))).replace(",", "."))
            except (ValueError, AttributeError):
                return default

        def checked(name):
            return field(name, "") in ("on", "true", "1")

        if rest == ["format"]:
            with session.lock:
                session.height_cm = max(0.1, as_float("height_cm", session.height_cm))
                session.dpi = max(1, int(as_float("dpi", session.dpi)))
            self._redirect("/maker")
            return

        if rest == ["reset"]:
            with session.lock:
                session.height_cm = 10.0
                session.dpi = 300
                session.banner_image = None
                session.banner_name = None
                session.banner_height_cm = 1.0
                session.panels = maker_state.new_default_panels()
            self._redirect("/maker")
            return

        if rest == ["save"]:
            game_uid = field("game_uid", "").strip()
            with session.lock:
                combined = cover_render.build_combined_image(
                    session.panels, session.height_cm, session.dpi, session.banner_image, session.banner_height_cm
                )
                dpi = session.dpi
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.png"
            combined.save(dest, dpi=(dpi, dpi))

            game_name = game_appid = None
            if game_uid:
                for uid, appid, name in fetch_games():
                    if uid == game_uid:
                        game_name, game_appid = name, appid
                        break
            cover_id = insert_cover(dest, game_uid, game_name, game_appid)
            with session.lock:
                session.last_saved_cover_id = cover_id
            self._redirect(f"/maker?saved={cover_id}")
            return

        if rest == ["banner", "upload"]:
            upload = form.get("banner_image", [None])[0]
            if isinstance(upload, dict) and upload.get("filename"):
                try:
                    img = Image.open(io.BytesIO(upload["content"]))
                    img.load()
                    with session.lock:
                        session.banner_image = img
                        session.banner_name = upload["filename"]
                except Exception:
                    pass
            self._redirect("/maker")
            return

        if rest == ["banner", "clear"]:
            with session.lock:
                session.banner_image = None
                session.banner_name = None
            self._redirect("/maker")
            return

        if rest == ["banner", "height"]:
            with session.lock:
                session.banner_height_cm = max(0.0, as_float("banner_height_cm", session.banner_height_cm))
            self._redirect("/maker")
            return

        if rest == ["banner", "save_template"]:
            name = field("template_name", "").strip() or "Banner"
            console = field("console", cover_render.CONSOLE_OPTIONS[0])
            with session.lock:
                banner_img = session.banner_image
            if banner_img is not None:
                BANNER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
                dest = BANNER_TEMPLATES_DIR / f"{uuid.uuid4().hex}.png"
                banner_img.convert("RGB").save(dest)
                save_banner_template(name, dest, console)
            self._redirect("/maker")
            return

        if rest == ["banner", "load_template"]:
            template_id = field("template_id", "")
            if template_id:
                try:
                    row = fetch_banner_template(int(template_id))
                except ValueError:
                    row = None
                if row is not None:
                    try:
                        img = Image.open(row["file_path"])
                        img.load()
                        with session.lock:
                            session.banner_image = img
                            session.banner_name = Path(row["file_path"]).name
                    except Exception:
                        pass
            self._redirect("/maker")
            return

        if len(rest) >= 3 and rest[0] == "panel" and rest[1].isdigit():
            index = int(rest[1])
            action = rest[2]
            with session.lock:
                if index < 0 or index >= len(session.panels):
                    self.send_response(404)
                    self._maybe_set_cookie()
                    self.end_headers()
                    return
                panel = session.panels[index]

                if action == "upload":
                    upload = form.get("image", [None])[0]
                    if isinstance(upload, dict) and upload.get("filename"):
                        try:
                            img = Image.open(io.BytesIO(upload["content"]))
                            img.load()
                            panel.pil_image = img
                            panel.image_name = upload["filename"]
                            panel.center_x = panel.center_y = 0.5
                        except Exception:
                            pass
                    self._redirect("/maker")
                    return

                if action == "settings":
                    panel.name = field("name", panel.name).strip() or panel.name
                    panel.width_cm = max(0.1, as_float("width_cm", panel.width_cm))
                    mode = field("mode", panel.mode)
                    if mode in cover_render.FIT_MODES:
                        panel.mode = mode
                    self._redirect("/maker")
                    return

                if action == "crop":
                    panel.center_x = min(1.0, max(0.0, as_float("center_x", panel.center_x)))
                    panel.center_y = min(1.0, max(0.0, as_float("center_y", panel.center_y)))
                    self._respond_json({"ok": True})
                    return

                if action == "toggle_back":
                    panel.is_back = checked("is_back")
                    self._redirect("/maker")
                    return

                if action == "toggle_wrap":
                    panel.wrap_front = checked("wrap_front")
                    self._redirect("/maker")
                    return

                if action == "position":
                    new_index = int(as_float("new_index", index))
                    new_index = max(0, min(len(session.panels) - 1, new_index))
                    if new_index != index:
                        moved = session.panels.pop(index)
                        session.panels.insert(new_index, moved)
                    self._redirect("/maker")
                    return

                if action == "back":
                    panel.art_ratio_percent = max(1.0, min(99.0, as_float("art_ratio_percent", panel.art_ratio_percent)))
                    panel.min_title = field("min_title", panel.min_title).strip() or cover_render.DEFAULT_MIN_TITLE
                    panel.rec_title = field("rec_title", panel.rec_title).strip() or cover_render.DEFAULT_REC_TITLE
                    panel.min_text_content = field("min_text_content", panel.min_text_content)
                    panel.rec_text_content = field("rec_text_content", panel.rec_text_content)
                    panel.show_compat = checked("show_compat")
                    steamdeck = field("steamdeck_rating", panel.steamdeck_rating)
                    if steamdeck in cover_render.RATING_OPTIONS:
                        panel.steamdeck_rating = steamdeck
                    steammachine = field("steammachine_rating", panel.steammachine_rating)
                    if steammachine in cover_render.RATING_OPTIONS:
                        panel.steammachine_rating = steammachine
                    panel.input_kbm = checked("input_kbm")
                    panel.input_controller = checked("input_controller")
                    self._redirect("/maker")
                    return

                if action == "logos" and len(rest) >= 4 and rest[3] == "add":
                    for upload in form.get("logo_files", []):
                        if isinstance(upload, dict) and upload.get("filename"):
                            try:
                                img = Image.open(io.BytesIO(upload["content"]))
                                img.load()
                                panel.logos.append(img)
                                panel.logo_names.append(upload["filename"])
                            except Exception:
                                pass
                    self._redirect("/maker")
                    return

                if action == "logos" and len(rest) >= 4 and rest[3] == "remove":
                    try:
                        li = int(field("logo_index", "-1"))
                    except ValueError:
                        li = -1
                    if 0 <= li < len(panel.logos):
                        del panel.logos[li]
                        del panel.logo_names[li]
                    self._redirect("/maker")
                    return

        self.send_response(404)
        self._maybe_set_cookie()
        self.end_headers()

    # -- Store: Thumbnail/Download/View ------------------------------------
    def _serve_thumbnail(self, cover_id):
        cover = fetch_cover(cover_id)
        if cover is None:
            self.send_response(404)
            self.end_headers()
            return
        data = get_thumbnail_bytes(cover_id, cover["file_path"])
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, cover_id, inline):
        cover = fetch_cover(cover_id)
        if cover is None:
            self.send_response(404)
            self.end_headers()
            return
        path = Path(cover["file_path"])
        if not path.is_file():
            self.send_response(404)
            self.end_headers()
            return

        suffix = path.suffix.lower()
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(suffix, "application/octet-stream")

        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f'{disposition}; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _respond_html(self, html_text):
        encoded = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._maybe_set_cookie()
        self.end_headers()
        self.wfile.write(encoded)


def main():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    # ThreadingHTTPServer statt einfachem TCPServer: mehrere Benutzer (bzw.
    # mehrere parallele Bild-/Vorschau-Requests derselben Seite) duerfen
    # gleichzeitig bedient werden, ohne dass ein einzelner offener Request
    # alle anderen blockiert.
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        url = f"http://{HOST}:{PORT}/"
        print(f"Cover Store laeuft unter {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    if sys.platform != "win32":
        print("Hinweis: fuer den Einsatz auf Windows gedacht, laeuft aber plattformunabhaengig.")
    main()
