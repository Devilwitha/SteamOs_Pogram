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

Nutzt nur die Python-Standardbibliothek (kein Tkinter/Qt noetig), damit es
ohne zusaetzliche Pakete auf SteamOS laeuft (schreibgeschuetztes
Root-Dateisystem).

Aufruf:  python3 gui_server.py
Danach im Browser (Desktop-Modus) http://localhost:8080 oeffnen - wird
normalerweise automatisch geoeffnet.
"""
import http.server
import socketserver
import sqlite3
import sys
import urllib.parse
import webbrowser
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
STEAMOS_DIR = GUI_DIR.parent
sys.path.insert(0, str(STEAMOS_DIR))

import pico_link  # noqa: E402

DB_PATH = STEAMOS_DIR / "games.db"
HOST = "127.0.0.1"
PORT = 8080

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
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT uid, name, installed FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()


def _resolve_pico_ip(config):
    udp_port = config.get("udp_port", 5006)
    return config.get("pico_ip") or pico_link.discover_pico(udp_port)


def _render_game_rows(games):
    if not games:
        return (
            "<tr><td colspan='4'>Keine Spiele gefunden. "
            "Erst <code>python3 ../game_scanner.py</code> ausfuehren.</td></tr>"
        )

    rows = []
    for game in games:
        badge = "installiert" if game["installed"] else "nicht installiert"
        rows.append(
            "<tr>"
            f"<td>{_escape(game['name'])}</td>"
            f"<td class='badge'>{badge}</td>"
            f"<td class='uid'>{game['uid']}</td>"
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
        return "<tr><td colspan='4'>Pico nicht erreichbar - Tag-Liste kann nicht geladen werden.</td></tr>"
    if not tags:
        return "<tr><td colspan='4'>Noch keine Tags erkannt. Einen Tag an den RC522 halten.</td></tr>"

    game_names = {g["uid"]: g["name"] for g in games}

    rows = []
    for tag in tags:
        uid = tag.get("uid", "")
        game_uid = tag.get("game_uid")

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


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self._respond(render_page())

    def do_POST(self):
        routes = {
            "/send": self._handle_send,
            "/link_tag": self._handle_link_tag,
            "/unlink_tag": self._handle_unlink_tag,
        }
        handler = routes.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        form = urllib.parse.parse_qs(body)

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

        ok, confirmed = pico_link.select_game(pico_ip, tcp_port, uid)
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
        return self._link(uid, game_uid, "verknuepft")

    def _handle_unlink_tag(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Tag-UID angegeben.</div>"
        return self._link(uid, "", "getrennt")

    def _link(self, uid, game_uid, aktion):
        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        pico_ip = _resolve_pico_ip(config)
        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        if pico_link.link_tag(pico_ip, tcp_port, uid, game_uid):
            return f"<div class='message success'>Tag {_escape(uid)} wurde {aktion}.</div>"
        return f"<div class='message error'>Verknuepfung fuer Tag {_escape(uid)} fehlgeschlagen (unbekannter Tag?).</div>"

    def _respond(self, html):
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
        url = f"http://{HOST}:{PORT}/"
        print(f"GUI laeuft unter {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
