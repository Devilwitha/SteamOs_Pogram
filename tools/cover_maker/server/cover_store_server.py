#!/usr/bin/env python3
"""Cover Store - lokaler Webserver, der die mit cover_maker.py erstellten
(und zusaetzlich hier direkt hochgeladenen oder im Browser zusammengebauten)
Cover wie in einem kleinen Store mit Vorschaubildern, Suche und Download
anzeigt. Enthaelt zwei Seiten (siehe Navigation oben auf jeder Seite):
"Store" (/, Durchsuchen/Herunterladen/Hochladen) und "Cover Maker"
(/maker, baut aus einzelnen Panel-Bildern + Banner direkt im Browser ein
neues Cover zusammen - eine vereinfachte Web-Variante von cover_maker.py;
Freihand-Bildausschnitt, Rueckseiten-Textfelder/Logos und Banner-Vorlagen
bleiben der Desktop-App vorbehalten).

Nutzt dieselbe Datenbank wie cover_maker.py/assign_game.py
(tools/cover_maker/covers.db, Tabelle "covers") - Cover, die in der
Cover-Maker-App gespeichert werden, tauchen hier also automatisch mit auf.
Zusaetzlich kann hier direkt ein fertiges Cover-Bild hochgeladen und optional
gleich einem Spiel aus steamOs/games.db zugeordnet werden; diese Zuordnung
ist es auch, wonach die Suche filtert.

Nutzt nur die Python-Standardbibliothek + Pillow (bereits Abhaengigkeit von
cover_maker.py) - kein Flask/Django noetig.

Start (Windows):  python cover_store_server.py
Danach im Browser http://127.0.0.1:8090 oeffnen - wird normalerweise
automatisch geoeffnet. Server ist standardmaessig nur lokal erreichbar.
"""
import html
import http.server
import io
import re
import sqlite3
import sys
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path

from PIL import Image, ImageOps

SERVER_DIR = Path(__file__).resolve().parent
COVER_MAKER_DIR = SERVER_DIR.parent
REPO_ROOT = COVER_MAKER_DIR.parent.parent

DB_PATH = COVER_MAKER_DIR / "covers.db"
GAMES_DB_PATH = REPO_ROOT / "steamOs" / "games.db"
UPLOAD_DIR = SERVER_DIR / "uploads"
THUMB_DIR = SERVER_DIR / "thumbnails"

HOST = "127.0.0.1"
PORT = 8090

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
THUMB_MAX = 320

# Panel-Reihenfolge/-Vorgaben wie PANEL_DEFAULTS in cover_maker.py (dieselbe
# Bedeutung: Seite1 | Front | Seite2 | Rueckseite).
MAKER_PANEL_DEFAULTS = [
    {"label": "Seite 1", "width_cm": 1.0},
    {"label": "Front", "width_cm": 6.0},
    {"label": "Seite 2", "width_cm": 1.0},
    {"label": "Rueckseite", "width_cm": 6.0},
]
FIT_MODES = [
    ("crop", "Zuschneiden (zentriert)"),
    ("stretch", "Fuellen (Groesse anpassen)"),
    ("contain", "Einpassen (mit Rand)"),
]

with open(SERVER_DIR / "index.html", encoding="utf-8") as _f:
    STORE_TEMPLATE = _f.read()
with open(SERVER_DIR / "maker.html", encoding="utf-8") as _f:
    MAKER_TEMPLATE = _f.read()


def _escape(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def ensure_covers_db(conn):
    """Gleiches Schema wie in cover_maker.py - eigenstaendig gehalten, damit
    dieser Server ohne Tkinter-Abhaengigkeit lauffaehig bleibt."""
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
    """Minimaler multipart/form-data-Parser (nur fuer den hier verwendeten
    Upload-Fall aus dem Browser), analog zu steamOs/gui/gui_server.py."""
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
            value = {"filename": filename_match.group(1), "content": content}
        else:
            value = content.decode(errors="replace")
        fields.setdefault(field_name, []).append(value)
    return fields


def cm_to_px(cm, dpi):
    return max(1, round(cm / 2.54 * dpi))


def _fit_source(image, mode, w_px, h_px):
    """Portiert aus cover_maker.py (CoverMakerApp._render_source) - reines
    PIL, ohne Tkinter-Abhaengigkeit, daher hier 1:1 wiederverwendbar."""
    w_px, h_px = max(1, w_px), max(1, h_px)
    src = image.convert("RGB")

    if mode == "stretch":
        return src.resize((w_px, h_px), Image.LANCZOS)

    if mode == "contain":
        fitted = ImageOps.contain(src, (w_px, h_px), method=Image.LANCZOS)
        canvas = Image.new("RGB", (w_px, h_px), "white")
        canvas.paste(fitted, ((w_px - fitted.width) // 2, (h_px - fitted.height) // 2))
        return canvas

    # "crop" (Standard) - zentrierter Ausschnitt, analog MODE_CROP im Desktop-Tool
    return ImageOps.fit(src, (w_px, h_px), method=Image.LANCZOS, centering=(0.5, 0.5))


def build_cover_image(height_cm, dpi, banner_image, banner_height_cm, panels):
    """Vereinfachte Web-Variante von CoverMakerApp.build_combined_image:
    reiht die Panels (Liste von {width_cm, fit_mode, image}) nebeneinander
    und legt optional ein durchgehendes Banner oben drueber. Anders als die
    Desktop-App unterstuetzt dies (noch) keinen frei verschiebbaren
    Bildausschnitt, keinen umlaufenden Banner-Wrap-Effekt und keine
    Rueckseite mit Systemanforderungen/Logos - dafuer bleibt cover_maker.py
    die vollstaendige Variante."""
    height_px = cm_to_px(height_cm, dpi)
    widths_px = [cm_to_px(p["width_cm"], dpi) for p in panels]
    total_width_px = sum(widths_px)

    canvas = Image.new("RGB", (total_width_px, height_px), "white")

    banner_h = 0
    if banner_image is not None and banner_height_cm > 0 and height_cm > 0:
        banner_h = round(height_px * min(0.9, banner_height_cm / height_cm))
    content_h = max(1, height_px - banner_h)

    x_offset = 0
    for panel, w_px in zip(panels, widths_px):
        if panel["image"] is not None:
            content = _fit_source(panel["image"], panel["fit_mode"], w_px, content_h)
        else:
            content = Image.new("RGB", (w_px, content_h), "white")
        canvas.paste(content, (x_offset, banner_h))
        x_offset += w_px

    if banner_h > 0:
        banner_resized = _fit_source(banner_image, "stretch", total_width_px, banner_h)
        canvas.paste(banner_resized, (0, 0))

    return canvas


def _render_game_options():
    options = ['<option value="">(kein Spiel verknuepfen)</option>']
    for uid, appid, name in fetch_games():
        options.append(f'<option value="{_escape(uid)}" data-appid="{appid or 0}">{_escape(name)}</option>')
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


def _render_panel_fields():
    blocks = []
    for i, defaults in enumerate(MAKER_PANEL_DEFAULTS, start=1):
        fit_options = "".join(
            f'<option value="{value}"{" selected" if value == "crop" else ""}>{label}</option>'
            for value, label in FIT_MODES
        )
        blocks.append(
            '<div class="panel maker-panel">'
            f"<h2 style='margin-top:0'>Panel {i} &middot; {defaults['label']}</h2>"
            "<div class='field'><label>Bild</label>"
            f"<input type='file' name='panel_{i}_image' accept='.png,.jpg,.jpeg,.webp,.bmp'></div>"
            "<div class='field-row'>"
            "<div class='field'><label>Breite (cm)</label>"
            f"<input type='text' name='panel_{i}_width_cm' value='{defaults['width_cm']:g}'></div>"
            "<div class='field'><label>Modus</label>"
            f"<select name='panel_{i}_fit'>{fit_options}</select></div>"
            "</div>"
            "</div>"
        )
    return "".join(blocks)


def render_maker_page(build_message=""):
    page = MAKER_TEMPLATE.replace("__BUILD_MESSAGE__", build_message)
    page = page.replace("__GAME_OPTIONS__", _render_game_options())
    page = page.replace("__PANEL_FIELDS__", _render_panel_fields())
    return page


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if not parts:
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            self._respond_html(render_store_page(query=query))
            return

        if parts == ["maker"]:
            self._respond_html(render_maker_page())
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
        if self.path not in ("/upload", "/build"):
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b""
        form = _parse_multipart(content_type, raw_body)

        if self.path == "/upload":
            message = self._handle_upload(form)
            self._respond_html(render_store_page(upload_message=message))
        else:
            message = self._handle_build(form)
            self._respond_html(render_maker_page(build_message=message))

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

    def _handle_build(self, form):
        def field(name, default=""):
            return (form.get(name, [default]) or [default])[0]

        def as_float(name, default):
            try:
                return float(field(name, str(default)).replace(",", "."))
            except (ValueError, AttributeError):
                return default

        height_cm = max(0.1, as_float("height_cm", 10.0))
        dpi = max(1, int(as_float("dpi", 300)))
        banner_height_cm = max(0.0, as_float("banner_height_cm", 0.0))

        banner_image = None
        banner_upload = form.get("banner_image", [None])[0]
        if isinstance(banner_upload, dict) and banner_upload.get("filename"):
            try:
                banner_image = Image.open(io.BytesIO(banner_upload["content"]))
                banner_image.load()
            except Exception:
                banner_image = None

        panels = []
        any_image = False
        for i, defaults in enumerate(MAKER_PANEL_DEFAULTS, start=1):
            width_cm = max(0.1, as_float(f"panel_{i}_width_cm", defaults["width_cm"]))
            fit_mode = field(f"panel_{i}_fit", "crop")
            if fit_mode not in {"crop", "stretch", "contain"}:
                fit_mode = "crop"

            image = None
            upload = form.get(f"panel_{i}_image", [None])[0]
            if isinstance(upload, dict) and upload.get("filename"):
                try:
                    image = Image.open(io.BytesIO(upload["content"]))
                    image.load()
                    any_image = True
                except Exception:
                    image = None

            panels.append({"width_cm": width_cm, "fit_mode": fit_mode, "image": image})

        if not any_image:
            return '<div class="message error">Bitte mindestens ein Panel-Bild hochladen.</div>'

        combined = build_cover_image(height_cm, dpi, banner_image, banner_height_cm, panels)

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.png"
        combined.save(dest, dpi=(dpi, dpi))

        game_uid = field("game_uid", "").strip()
        game_name = game_appid = None
        if game_uid:
            for uid, appid, name in fetch_games():
                if uid == game_uid:
                    game_name, game_appid = name, appid
                    break

        cover_id = insert_cover(dest, game_uid, game_name, game_appid)
        linked = f" und mit '{_escape(game_name)}' verknuepft" if game_name else ""
        return (
            f'<div class="message success">Cover #{cover_id} erstellt{linked}.<br>'
            f'<img src="/thumb/{cover_id}" style="max-width:320px;margin-top:10px;'
            f'border:1px solid var(--border);border-radius:4px" alt="Vorschau">'
            "<br><br>"
            f'<a class="btn" href="/view/{cover_id}" target="_blank">ANSEHEN</a> '
            f'<a class="btn secondary" href="/">ZUM STORE</a></div>'
        )

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
        self.end_headers()
        self.wfile.write(encoded)


def main():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    # ThreadingHTTPServer statt einfachem TCPServer: die Store-Seite laedt
    # pro Cover ein eigenes Thumbnail-Bild, der Browser oeffnet dafuer
    # mehrere parallele (Keep-Alive-)Verbindungen. Ein einzeln-threaded
    # Server wuerde dabei haengen bleiben, sobald eine Verbindung offen
    # gehalten wird, waehrend andere Anfragen auf Bedienung warten.
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
