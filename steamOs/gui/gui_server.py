#!/usr/bin/env python3
"""Lokale GUI zur Spielauswahl.

Zeigt die in ../games.db gespeicherten Spiele (siehe game_scanner.py) in
einer Weboberflaeche an. Bei Klick auf "An Pico senden" wird die UID des
gewaehlten Spiels an den Pico geschickt; der Pico speichert sie in einer
Textdatei und bestaetigt den Empfang, was hier angezeigt wird.

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

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Spielauswahl fuer Pico</title>
<style>
body{font-family:sans-serif;background:#1b1f24;color:#eee;padding:24px;margin:0}
h1{margin-top:0}
table{width:100%;border-collapse:collapse;background:#262b33;border-radius:8px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #333944}
th{background:#1f242b;color:#9fb4c7}
tr:last-child td{border-bottom:none}
.badge{color:#aaa;font-size:0.9em}
.uid{color:#6c7683;font-size:0.8em;font-family:monospace}
button{padding:6px 14px;background:#1a9fff;color:#fff;border:none;border-radius:4px;font-weight:bold;cursor:pointer}
button:hover{background:#0d8ce0}
.message{padding:12px 16px;border-radius:6px;margin-bottom:16px}
.success{background:#1e3a24;color:#7ee08a;border:1px solid #2f5c39}
.error{background:#3a1e1e;color:#e07e7e;border:1px solid #5c2f2f}
</style>
</head>
<body>
<h1>Spiel an Pico senden</h1>
__MESSAGE__
<table>
<thead>
<tr><th>Name</th><th>Status</th><th>UID</th><th></th></tr>
</thead>
<tbody>
__ROWS__
</tbody>
</table>
</body>
</html>
"""


def _escape(text):
    return (
        text.replace("&", "&amp;")
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


def render_page(message_html=""):
    games = fetch_games()

    if not games:
        rows_html = (
            "<tr><td colspan='4'>Keine Spiele gefunden. "
            "Erst <code>python3 ../game_scanner.py</code> ausfuehren.</td></tr>"
        )
    else:
        rows = []
        for game in games:
            badge = "installiert" if game["installed"] else "nicht installiert"
            rows.append(
                "<tr>"
                f"<td>{_escape(game['name'])}</td>"
                f"<td class='badge'>{badge}</td>"
                f"<td class='uid'>{game['uid']}</td>"
                "<td>"
                f"<form method='POST' action='/send' style='margin:0'>"
                f"<input type='hidden' name='uid' value='{game['uid']}'>"
                "<button type='submit'>An Pico senden</button>"
                "</form>"
                "</td>"
                "</tr>"
            )
        rows_html = "".join(rows)

    return PAGE_TEMPLATE.replace("__MESSAGE__", message_html).replace("__ROWS__", rows_html)


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
        if self.path != "/send":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        form = urllib.parse.parse_qs(body)
        uid = form.get("uid", [""])[0]

        message_html = self._send_to_pico(uid)
        self._respond(render_page(message_html))

    def _send_to_pico(self, uid):
        if not uid:
            return "<div class='message error'>Keine UID angegeben.</div>"

        config = pico_link.load_config()
        tcp_port = config.get("tcp_port", 5005)
        udp_port = config.get("udp_port", 5006)
        pico_ip = config.get("pico_ip") or pico_link.discover_pico(udp_port)

        if not pico_ip:
            return "<div class='message error'>Pico wurde im Netzwerk nicht gefunden.</div>"

        ok, confirmed = pico_link.select_game(pico_ip, tcp_port, uid)
        if ok:
            return f"<div class='message success'>Pico hat die Auswahl bestaetigt: {_escape(confirmed)}</div>"
        return f"<div class='message error'>Keine gueltige Bestaetigung vom Pico erhalten ({_escape(str(confirmed))}).</div>"

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
