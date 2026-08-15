#!/usr/bin/env python3
"""Lokale GUI zur Spielauswahl und Tag-Verwaltung.

Zeigt die in ../games.db gespeicherten Spiele (siehe game_scanner.py) in
einer Weboberflaeche an. Bei Klick auf "An Pico senden" wird die UID des
gewaehlten Spiels an den Pico geschickt; der Pico merkt sie zum
Verknuepfen mit dem naechsten aufgelegten Tag vor und bestaetigt den
Empfang, was hier angezeigt wird.

Zusaetzlich wird die vom Pico bekannte Liste erkannter RFID-Tags
angezeigt (siehe Pico/tag_store.py) - Tags koennen von hier aus auch
direkt mit einem Spiel verknuepft oder wieder getrennt werden, ohne sie
erneut an den Leser zu halten (zweite Richtung neben "Spiel waehlen,
dann Tag scannen").

Sowohl Spielen als auch Tags laesst sich hier zusaetzlich eine eigene
Farbe zuweisen (Farbfeld je Zeile, speichert bei Aenderung sofort). Eine
Tag-Farbe hat Vorrang vor der Farbe des verknuepften Spiels. Beide werden
von steamOs/pico_client.py an einen optionalen zweiten Pico (siehe
../../Led_Pico) weitergereicht, der damit einen LED-Streifen ansteuert.

Nutzt nur die Python-Standardbibliothek (kein Tkinter/Qt noetig), damit es
ohne zusaetzliche Pakete auf SteamOS laeuft (schreibgeschuetztes
Root-Dateisystem).

Aufruf:  python3 gui_server.py
Danach im Browser (Desktop-Modus) http://localhost:8080 oeffnen - wird
normalerweise automatisch geoeffnet.
"""
import http.server
import json
import re
import socketserver
import sqlite3
import sys
import urllib.parse
import webbrowser
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
STEAMOS_DIR = GUI_DIR.parent
sys.path.insert(0, str(STEAMOS_DIR))

import audio_player  # noqa: E402
import game_scanner  # noqa: E402
import pico_link  # noqa: E402

DB_PATH = STEAMOS_DIR / "games.db"
AUDIO_DIR = STEAMOS_DIR / "audio"
HOST = "127.0.0.1"
DEFAULT_PORT = 8090
# Diese Endungen werden beim Hochladen akzeptiert (siehe _handle_set_game_audio) -
# audio_player.play() spielt sie plattformabhaengig ab (Windows: MCI, kann alle
# vier; Linux: je nach verfuegbarem Kommandozeilenplayer, siehe audio_player.py).
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}

with open(GUI_DIR / "index.html", encoding="utf-8") as _f:
    PAGE_TEMPLATE = _f.read()


def _escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fetch_games():
    if not DB_PATH.is_file():
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT uid, name, installed, color, audio_path FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()


def set_game_color(uid, color):
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.execute("UPDATE games SET color = ? WHERE uid = ?", (color or None, uid))
        conn.commit()
    finally:
        conn.close()


def _lookup_game_audio_path(uid):
    if not uid or not DB_PATH.is_file():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        row = conn.execute("SELECT audio_path FROM games WHERE uid = ?", (uid,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _clear_existing_audio_files(uid):
    """Loescht evtl. schon vorhandene Audiodateien dieses Spiels (gleicher
    uid-Dateiname, egal welche Endung) - noetig, damit beim Ersetzen eines
    Sounds mit anderem Format (z. B. .mp3 -> .wav) keine Datei-Leiche mit der
    alten Endung liegen bleibt (siehe set_game_audio())."""
    for old in AUDIO_DIR.glob(f"{uid}.*"):
        try:
            old.unlink()
        except OSError:
            pass


def set_game_audio(uid, filename, content):
    """Kopiert eine hochgeladene Audiodatei lokal nach AUDIO_DIR (analog zum
    Cover-Bild-Muster in tools/cover_maker: einmal lokal ablegen, absoluten
    Pfad in der DB speichern, damit Wiedergabe/Tag-Start sie immer von genau
    diesem einen Ort laden - kein erneuter Zugriff auf die urspruengliche
    Quelldatei noetig)."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        return False, f"Nicht unterstuetztes Audioformat: {ext or '(keine Endung)'}"

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _clear_existing_audio_files(uid)
    dest = AUDIO_DIR / f"{uid}{ext}"
    dest.write_bytes(content)

    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.execute(
            "UPDATE games SET audio_path = ? WHERE uid = ?",
            (str(dest.resolve()), uid),
        )
        conn.commit()
    finally:
        conn.close()
    return True, None


def remove_game_audio(uid):
    audio_player.stop()
    _clear_existing_audio_files(uid)
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.execute("UPDATE games SET audio_path = NULL WHERE uid = ?", (uid,))
        conn.commit()
    finally:
        conn.close()


def _parse_multipart(content_type, body):
    """Minimaler multipart/form-data-Parser (nur fuer den hier verwendeten
    Upload-Fall aus dem Browser - kein RFC-vollstaendiger Parser). Liefert
    wie urllib.parse.parse_qs ein dict von Feldname -> Werteliste; bei
    Datei-Feldern ist der Wert ein dict {'filename':..., 'content': bytes}
    statt eines str."""
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


def _resolve_pico_ip(config):
    udp_port = config.get("udp_port", 5006)
    return config.get("pico_ip") or pico_link.discover_pico(udp_port)


def _lookup_game_name(uid):
    """Anzeigename zu einer Spiel-UID (fuers Pico-LCD) - None, wenn
    unbekannt oder DB nicht vorhanden."""
    if not uid or not DB_PATH.is_file():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        row = conn.execute("SELECT name FROM games WHERE uid = ?", (uid,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _render_game_rows(games):
    if not games:
        return (
            "<tr><td colspan='6'>Keine Spiele gefunden. "
            "Erst <code>python3 ../game_scanner.py</code> ausfuehren.</td></tr>"
        )

    rows = []
    for game in games:
        badge = "installiert" if game["installed"] else "nicht installiert"
        color = game["color"] or "#00e5ff"
        audio_path = game["audio_path"]

        if audio_path:
            audio_name = _escape(Path(audio_path).name)
            audio_html = (
                f"<div class='audio-current'>&#127925; {audio_name}</div>"
                "<div class='inline-form'>"
                "<form method='POST' action='/play_game_audio' class='inline-form'>"
                f"<input type='hidden' name='uid' value='{game['uid']}'>"
                "<button type='submit'>&#9658;</button>"
                "</form>"
                "<form method='POST' action='/stop_game_audio' class='inline-form'>"
                f"<input type='hidden' name='uid' value='{game['uid']}'>"
                "<button type='submit' class='secondary'>&#9632;</button>"
                "</form>"
                "<form method='POST' action='/remove_game_audio' class='inline-form'>"
                f"<input type='hidden' name='uid' value='{game['uid']}'>"
                "<button type='submit' class='secondary'>&#10005;</button>"
                "</form>"
                "</div>"
            )
        else:
            audio_html = "<span class='unlinked'>kein Sound</span>"

        rows.append(
            "<tr>"
            f"<td>{_escape(game['name'])}</td>"
            f"<td class='badge'>{badge}</td>"
            f"<td class='uid'>{game['uid']}</td>"
            "<td>"
            "<form method='POST' action='/set_game_color' class='inline-form'>"
            f"<input type='hidden' name='uid' value='{game['uid']}'>"
            f"<input type='color' name='color' value='{color}' onchange='this.form.submit()'>"
            "</form>"
            "</td>"
            "<td class='audio-cell'>"
            f"{audio_html}"
            "<form method='POST' action='/set_game_audio' enctype='multipart/form-data' class='inline-form'>"
            f"<input type='hidden' name='uid' value='{game['uid']}'>"
            "<input type='file' name='audio_file' accept='.mp3,.wav,.ogg,.flac,.m4a' onchange='this.form.submit()'>"
            "</form>"
            "</td>"
            "<td>"
            "<form method='POST' action='/send' class='inline-form'>"
            f"<input type='hidden' name='uid' value='{game['uid']}'>"
            "<button type='submit'>An Pico senden</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_tag_rows(tags, games):
    if tags is None:
        return "<tr><td colspan='5'>Pico nicht erreichbar - Tag-Liste kann nicht geladen werden.</td></tr>"
    if not tags:
        return "<tr><td colspan='5'>Noch keine Tags erkannt. Einen Tag an den RC522 halten.</td></tr>"

    game_names = {g["uid"]: g["name"] for g in games}

    rows = []
    for tag in tags:
        uid = tag.get("uid", "")
        game_uid = tag.get("game_uid")
        color = tag.get("color") or "#00e5ff"

        options = ["<option value=''>Spiel waehlen ...</option>"]
        for g in games:
            selected = " selected" if g["uid"] == game_uid else ""
            options.append(f"<option value='{g['uid']}'{selected}>{_escape(g['name'])}</option>")

        if game_uid:
            status_html = f"<span class='linked'>{_escape(game_names.get(game_uid, game_uid))}</span>"
            unlink_button = (
                "<form method='POST' action='/unlink_tag' class='inline-form'>"
                f"<input type='hidden' name='uid' value='{uid}'>"
                "<button type='submit' class='secondary'>Trennen</button>"
                "</form>"
            )
        else:
            status_html = "<span class='unlinked'>nicht verknuepft</span>"
            unlink_button = ""

        rows.append(
            "<tr>"
            f"<td class='uid'>{uid}</td>"
            f"<td>{status_html}</td>"
            "<td>"
            "<form method='POST' action='/set_tag_color' class='inline-form'>"
            f"<input type='hidden' name='uid' value='{uid}'>"
            f"<input type='color' name='color' value='{color}' onchange='this.form.submit()'>"
            "</form>"
            "</td>"
            "<td>"
            "<form method='POST' action='/link_tag' class='inline-form'>"
            f"<input type='hidden' name='uid' value='{uid}'>"
            f"<select name='game_uid'>{''.join(options)}</select>"
            "<button type='submit'>Verknuepfen</button>"
            "</form>"
            "</td>"
            f"<td>{unlink_button}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_page(message_html=""):
    games = fetch_games()

    config = pico_link.load_config()
    tcp_port = config.get("tcp_port", 5005)
    pico_ip = _resolve_pico_ip(config)
    tags = pico_link.fetch_tags(pico_ip, tcp_port) if pico_ip else None

    page = PAGE_TEMPLATE.replace("__MESSAGE__", message_html)
    page = page.replace("__ROWS__", _render_game_rows(games))
    page = page.replace("__TAG_ROWS__", _render_tag_rows(tags, games))
    return page


def _state_payload():
    """JSON-Schnappschuss von Spielen + Tags fuer entfernte Clients (siehe
    /api/state) - z. B. die vom Pico selbst gehostete Steuer-Seite
    (Pico/control.html), die kein HTML von hier einbetten kann und sich den
    Zustand stattdessen per fetch() selbst zusammenbaut."""
    games = fetch_games()

    config = pico_link.load_config()
    tcp_port = config.get("tcp_port", 5005)
    pico_ip = _resolve_pico_ip(config)
    tags = pico_link.fetch_tags(pico_ip, tcp_port) if pico_ip else None

    games_json = [
        {
            "uid": g["uid"],
            "name": g["name"],
            "installed": bool(g["installed"]),
            "color": g["color"],
            "has_audio": bool(g["audio_path"]),
            "audio_name": Path(g["audio_path"]).name if g["audio_path"] else None,
        }
        for g in games
    ]
    return {
        "ok": True,
        "games": games_json,
        "tags": tags if tags is not None else [],
        "pico_reachable": tags is not None,
    }


# Endpunkte fuer entfernte Clients (siehe Pico/control.html): gleiche
# Aktionen wie die Formulare unten, aber JSON statt HTML-Seite als Antwort
# und Token-pflichtig sobald die Anfrage nicht von localhost kommt (siehe
# Handler._is_authorized). Rufen bewusst dieselben modul-globalen Funktionen
# auf wie die HTML-Handler weiter unten, statt Logik zu duplizieren.
API_ROUTES = {
    "/api/select_game": "_api_select_game",
    "/api/link_tag": "_api_link_tag",
    "/api/unlink_tag": "_api_unlink_tag",
    "/api/set_game_color": "_api_set_game_color",
    "/api/set_tag_color": "_api_set_tag_color",
    "/api/forget_tag": "_api_forget_tag",
    "/api/set_game_audio": "_api_set_game_audio",
    "/api/remove_game_audio": "_api_remove_game_audio",
    "/api/play_game_audio": "_api_play_game_audio",
    "/api/stop_game_audio": "_api_stop_game_audio",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _is_authorized(self):
        """Lokale Anfragen (die bisherige Desktop-GUI) sind immer erlaubt.
        Alles andere - insbesondere die vom Pico gehostete Steuer-Seite,
        die aus dem Browser eines dritten Geraets im LAN heraus per fetch()
        auf diesen Server zugreift - braucht ein passendes Token, sobald
        eines in config.json hinterlegt ist. Ohne hinterlegtes Token bleibt
        der Fernzugriff komplett gesperrt (sicherer Default)."""
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        token = (pico_link.load_config().get("remote_control_token") or "").strip()
        if not token:
            return False
        return self.headers.get("X-Control-Token", "") == token

    def do_OPTIONS(self):
        # CORS-Preflight fuer die Pico-Steuer-Seite (anderer Origin) - hier
        # bewusst ohne Token-Pruefung, da Browser bei Preflights keine
        # benutzerdefinierten Header mitschicken; die eigentliche Anfrage
        # danach wird ganz normal ueber _is_authorized() geprueft.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Control-Token")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._is_authorized():
            self._respond_json(401, {"ok": False, "message": "Unauthorized"})
            return
        if self.path == "/api/state":
            self._respond_json(200, _state_payload())
            return
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self._respond(render_page())

    def _read_api_payload(self):
        """Wie der Body-Parser unten fuer die HTML-Formulare, gibt aber
        einfache Skalarwerte statt Listen zurueck (parse_qs-Konvention) und
        versteht zusaetzlich JSON-Bodies, da die Pico-Steuer-Seite ihre
        Aktionen ueberwiegend als fetch(..., {body: JSON.stringify(...)})
        schickt; nur der Datei-Upload nutzt weiterhin multipart/form-data
        (FormData im Browser)."""
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b""
        if content_type.startswith("multipart/form-data"):
            parsed = _parse_multipart(content_type, raw_body)
            return {k: v[0] for k, v in parsed.items()}
        if content_type.startswith("application/json"):
            if not raw_body:
                return {}
            try:
                return json.loads(raw_body.decode("utf-8"))
            except ValueError:
                return {}
        parsed = urllib.parse.parse_qs(raw_body.decode())
        return {k: v[0] for k, v in parsed.items()}

    def do_POST(self):
        if not self._is_authorized():
            self._respond_json(401, {"ok": False, "message": "Unauthorized"})
            return

        if self.path in API_ROUTES:
            payload = self._read_api_payload()
            result = getattr(self, API_ROUTES[self.path])(payload)
            self._respond_json(200 if result.get("ok") else 400, result)
            return

        routes = {
            "/send": self._handle_send,
            "/link_tag": self._handle_link_tag,
            "/unlink_tag": self._handle_unlink_tag,
            "/set_game_color": self._handle_set_game_color,
            "/set_tag_color": self._handle_set_tag_color,
            "/forget_tag": self._handle_forget_tag,
            "/set_game_audio": self._handle_set_game_audio,
            "/remove_game_audio": self._handle_remove_game_audio,
            "/play_game_audio": self._handle_play_game_audio,
            "/stop_game_audio": self._handle_stop_game_audio,
        }
        handler = routes.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        if content_type.startswith("multipart/form-data"):
            form = _parse_multipart(content_type, raw_body)
        else:
            form = urllib.parse.parse_qs(raw_body.decode())

        message_html = handler(form)
        self._respond(render_page(message_html))

    def _handle_send(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine UID angegeben.</div>"

        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        ok, confirmed = pico_link.select_game(pico_ip, tcp_port, uid, name=_lookup_game_name(uid))
        if ok:
            return (
                "<div class='message success'>Pico hat die Auswahl bestaetigt: "
                f"{_escape(confirmed)}<br>Jetzt einen Tag an den RC522 halten, "
                "um ihn damit zu verknuepfen.</div>"
            )
        return f"<div class='message error'>Keine gueltige Bestaetigung vom Pico erhalten ({_escape(confirmed)}).</div>"

    def _handle_link_tag(self, form):
        uid = form.get("uid", [""])[0]
        game_uid = form.get("game_uid", [""])[0]
        if not uid or not game_uid:
            return "<div class='message error'>Bitte ein Spiel auswaehlen.</div>"
        return self._link(uid, game_uid, "verknuepft", name=_lookup_game_name(game_uid))

    def _handle_unlink_tag(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Tag-UID angegeben.</div>"
        return self._link(uid, "", "getrennt")

    def _handle_set_game_color(self, form):
        uid = form.get("uid", [""])[0]
        color = form.get("color", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Spiel-UID angegeben.</div>"
        set_game_color(uid, color)
        return "<div class='message success'>Farbe fuer Spiel gespeichert.</div>"

    def _handle_set_tag_color(self, form):
        uid = form.get("uid", [""])[0]
        color = form.get("color", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Tag-UID angegeben.</div>"

        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        if pico_link.set_tag_color(pico_ip, tcp_port, uid, color):
            return f"<div class='message success'>Farbe fuer Tag {_escape(uid)} gespeichert.</div>"
        return f"<div class='message error'>Farbe fuer Tag {_escape(uid)} konnte nicht gespeichert werden (unbekannter Tag?).</div>"

    def _handle_forget_tag(self, form):
        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        if pico_link.forget_next_tag(pico_ip, tcp_port):
            return (
                "<div class='message success'>Loeschmodus aktiv: Jetzt den zu loeschenden Tag an "
                "den RC522 halten - er wird beim naechsten Erkennen dauerhaft entfernt (inklusive "
                "einer eventuellen Spiel-Verknuepfung).</div>"
            )
        return "<div class='message error'>Pico hat den Loeschmodus nicht bestaetigt.</div>"

    def _handle_set_game_audio(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Spiel-UID angegeben.</div>"

        upload = form.get("audio_file", [None])[0]
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return "<div class='message error'>Keine Datei ausgewaehlt.</div>"

        ok, error = set_game_audio(uid, upload["filename"], upload["content"])
        if ok:
            return f"<div class='message success'>Sound '{_escape(upload['filename'])}' gespeichert.</div>"
        return f"<div class='message error'>{_escape(error)}</div>"

    def _handle_remove_game_audio(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Spiel-UID angegeben.</div>"
        remove_game_audio(uid)
        return "<div class='message success'>Sound entfernt.</div>"

    def _handle_play_game_audio(self, form):
        uid = form.get("uid", [""])[0]
        path = _lookup_game_audio_path(uid)
        if not path:
            return "<div class='message error'>Kein Sound fuer dieses Spiel hinterlegt.</div>"
        audio_player.play(path)
        return "<div class='message success'>Wiedergabe gestartet.</div>"

    def _handle_stop_game_audio(self, form):
        audio_player.stop()
        return "<div class='message success'>Wiedergabe gestoppt.</div>"

    def _link(self, uid, game_uid, aktion, name=None):
        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        if pico_link.link_tag(pico_ip, tcp_port, uid, game_uid, name=name):
            return f"<div class='message success'>Tag {_escape(uid)} wurde {aktion}.</div>"
        return f"<div class='message error'>Verknuepfung fuer Tag {_escape(uid)} fehlgeschlagen (unbekannter Tag?).</div>"

    # -- JSON-API fuer entfernte Clients (siehe API_ROUTES oben) -----------
    def _api_select_game(self, data):
        uid = data.get("uid", "")
        if not uid:
            return {"ok": False, "message": "Keine UID angegeben."}

        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return {"ok": False, "message": "Pico wurde im Netzwerk nicht gefunden."}

        ok, confirmed = pico_link.select_game(pico_ip, tcp_port, uid, name=_lookup_game_name(uid))
        if ok:
            return {"ok": True, "message": f"Pico hat die Auswahl bestaetigt: {confirmed}"}
        return {"ok": False, "message": f"Keine gueltige Bestaetigung vom Pico erhalten ({confirmed})."}

    def _api_link_tag(self, data):
        uid = data.get("uid", "")
        game_uid = data.get("game_uid", "")
        if not uid or not game_uid:
            return {"ok": False, "message": "Bitte ein Spiel auswaehlen."}
        return self._api_link(uid, game_uid, "verknuepft", name=_lookup_game_name(game_uid))

    def _api_unlink_tag(self, data):
        uid = data.get("uid", "")
        if not uid:
            return {"ok": False, "message": "Keine Tag-UID angegeben."}
        return self._api_link(uid, "", "getrennt")

    def _api_link(self, uid, game_uid, aktion, name=None):
        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return {"ok": False, "message": "Pico wurde im Netzwerk nicht gefunden."}
        if pico_link.link_tag(pico_ip, tcp_port, uid, game_uid, name=name):
            return {"ok": True, "message": f"Tag {uid} wurde {aktion}."}
        return {"ok": False, "message": f"Verknuepfung fuer Tag {uid} fehlgeschlagen (unbekannter Tag?)."}

    def _api_set_game_color(self, data):
        uid = data.get("uid", "")
        color = data.get("color", "")
        if not uid:
            return {"ok": False, "message": "Keine Spiel-UID angegeben."}
        set_game_color(uid, color)
        return {"ok": True, "message": "Farbe fuer Spiel gespeichert."}

    def _api_set_tag_color(self, data):
        uid = data.get("uid", "")
        color = data.get("color", "")
        if not uid:
            return {"ok": False, "message": "Keine Tag-UID angegeben."}

        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return {"ok": False, "message": "Pico wurde im Netzwerk nicht gefunden."}

        if pico_link.set_tag_color(pico_ip, tcp_port, uid, color):
            return {"ok": True, "message": f"Farbe fuer Tag {uid} gespeichert."}
        return {"ok": False, "message": f"Farbe fuer Tag {uid} konnte nicht gespeichert werden (unbekannter Tag?)."}

    def _api_forget_tag(self, data):
        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return {"ok": False, "message": "Pico wurde im Netzwerk nicht gefunden."}

        if pico_link.forget_next_tag(pico_ip, tcp_port):
            return {
                "ok": True,
                "message": (
                    "Loeschmodus aktiv: Jetzt den zu loeschenden Tag an den RC522 halten - "
                    "er wird beim naechsten Erkennen dauerhaft entfernt."
                ),
            }
        return {"ok": False, "message": "Pico hat den Loeschmodus nicht bestaetigt."}

    def _api_set_game_audio(self, data):
        uid = data.get("uid", "")
        if not uid:
            return {"ok": False, "message": "Keine Spiel-UID angegeben."}

        upload = data.get("audio_file")
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return {"ok": False, "message": "Keine Datei ausgewaehlt."}

        ok, error = set_game_audio(uid, upload["filename"], upload["content"])
        if ok:
            return {"ok": True, "message": f"Sound '{upload['filename']}' gespeichert."}
        return {"ok": False, "message": error}

    def _api_remove_game_audio(self, data):
        uid = data.get("uid", "")
        if not uid:
            return {"ok": False, "message": "Keine Spiel-UID angegeben."}
        remove_game_audio(uid)
        return {"ok": True, "message": "Sound entfernt."}

    def _api_play_game_audio(self, data):
        uid = data.get("uid", "")
        path = _lookup_game_audio_path(uid)
        if not path:
            return {"ok": False, "message": "Kein Sound fuer dieses Spiel hinterlegt."}
        audio_player.play(path)
        return {"ok": True, "message": "Wiedergabe gestartet."}

    def _api_stop_game_audio(self, data):
        audio_player.stop()
        return {"ok": True, "message": "Wiedergabe gestoppt."}

    def _respond(self, html):
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def _respond_json(self, status, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)


def main():
    # gui_bind erlaubt es, den Server bewusst fuers LAN zu oeffnen (z. B.
    # "0.0.0.0"), damit die vom Pico gehostete Steuer-Seite (siehe
    # Pico/control.html) ihn per fetch() erreichen kann - siehe
    # Handler._is_authorized fuer die dafuer noetige Token-Pruefung.
    # Standardmaessig bleibt es bei 127.0.0.1, bestehende Installationen
    # sind also unveraendert nur lokal erreichbar.
    config = pico_link.load_config()
    host = config.get("gui_bind") or HOST
    port = config.get("gui_port") or DEFAULT_PORT
    with socketserver.TCPServer((host, port), Handler) as httpd:
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        url = f"http://{display_host}:{port}/"
        print(f"GUI laeuft unter {url}")
        if host == "0.0.0.0":
            print(f"Im LAN erreichbar unter Port {port} (Token-geschuetzt, siehe config.json)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
