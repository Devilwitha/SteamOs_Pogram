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

Spielen laesst sich hier zusaetzlich eine eigene Farbe zuweisen (Farbfeld
je Zeile, speichert bei Aenderung sofort) - genau eine Farbe pro Spiel,
keine separate Tag-Farbe mehr (fruehers TAGCOLOR-Feature, siehe
Git-Historie). Diese Farbe wird von steamOs/pico_client.py an einen
optionalen zweiten Pico (siehe ../../Led_Pico) weitergereicht, der damit
einen LED-Streifen ansteuert.

Nutzt nur die Python-Standardbibliothek (kein Tkinter/Qt noetig), damit es
ohne zusaetzliche Pakete auf SteamOS laeuft (schreibgeschuetztes
Root-Dateisystem).

Aufruf:  python3 gui_server.py
Danach im Browser (Desktop-Modus) http://localhost:8080 oeffnen - wird
normalerweise automatisch geoeffnet.
"""
import colorsys
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

import audio_config  # noqa: E402
import audio_player  # noqa: E402
import download_monitor  # noqa: E402
import game_scanner  # noqa: E402
import led_settings  # noqa: E402
import pico_link  # noqa: E402
import video_player  # noqa: E402

VERSION = "1.0.0"

DB_PATH = STEAMOS_DIR / "games.db"
AUDIO_DIR = STEAMOS_DIR / "audio"
VIDEO_DIR = STEAMOS_DIR / "video"
HOST = "127.0.0.1"
DEFAULT_PORT = 8090
# Diese Endungen werden beim Hochladen akzeptiert (siehe _handle_set_game_audio) -
# audio_player.play() spielt sie plattformabhaengig ab (Windows: MCI, kann alle
# vier; Linux: je nach verfuegbarem Kommandozeilenplayer, siehe audio_player.py).
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
# Analog fuer den Video-Modus (siehe set_video()) - von video_player.py per
# mpv/vlc/ffplay vollflaechig abgespielt.
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
# Dateiname (ohne Endung) des globalen Boot-Sounds/-Videos in AUDIO_DIR/
# VIDEO_DIR (siehe set_boot_sound()/set_video()) - fuehrender Unterstrich,
# damit er nie mit einer Spiel-UID (siehe games.db, immer eine UUID)
# kollidieren kann.
BOOT_SOUND_BASENAME = "_boot_sound"
VIDEO_BASENAME = "_boot_video"
# Anzeigetexte je Sound-Modus (siehe _handle_set_audio_mode()/_api_set_audio_mode()).
AUDIO_MODE_LABELS = {
    audio_config.MODE_SONGS: "Einzelne Songs je Spiel",
    audio_config.MODE_BOOT_SOUND: "Ein Boot-Sound fuer alle Spiele",
    audio_config.MODE_VIDEO: "Ein Video (Vollbild) fuer alle Spiele",
}

with open(GUI_DIR / "index.html", encoding="utf-8") as _f:
    PAGE_TEMPLATE = _f.read()
with open(GUI_DIR / "dashboard.html", encoding="utf-8") as _f:
    DASHBOARD_TEMPLATE = _f.read()


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
            "SELECT uid, name, installed, color, audio_path, audio_enabled "
            "FROM games ORDER BY name COLLATE NOCASE"
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


def set_game_audio_enabled(uid, enabled):
    """Schaltet die automatische Wiedergabe eines bereits hochgeladenen
    Sounds bei Tagstart um (pico_client.py prueft audio_enabled vor jedem
    audio_player.play(), siehe dort) - ohne die Datei selbst zu entfernen,
    im Unterschied zu remove_game_audio(). Der manuelle Test-Play-Button
    (_handle_play_game_audio/_api_play_game_audio) bleibt davon unberuehrt
    und spielt auch einen deaktivierten Sound weiterhin zum Testen ab."""
    conn = sqlite3.connect(DB_PATH)
    try:
        game_scanner.ensure_db(conn)
        conn.execute(
            "UPDATE games SET audio_enabled = ? WHERE uid = ?",
            (1 if enabled else 0, uid),
        )
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
        # audio_enabled bewusst mit zurueckgesetzt: ein frisch hochgeladener
        # (oder ersetzter) Sound soll sofort wieder automatisch abgespielt
        # werden, auch wenn der vorherige zuletzt deaktiviert war.
        conn.execute(
            "UPDATE games SET audio_path = ?, audio_enabled = 1 WHERE uid = ?",
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


def _clear_existing_boot_sound_files():
    """Analog zu _clear_existing_audio_files(), aber fuer den globalen
    Boot-Sound (siehe set_boot_sound())."""
    for old in AUDIO_DIR.glob(f"{BOOT_SOUND_BASENAME}.*"):
        try:
            old.unlink()
        except OSError:
            pass


def set_boot_sound(filename, content):
    """Wie set_game_audio(), aber fuer den einen globalen Sound, der im
    Boot-Sound-Modus (siehe audio_config.py) bei jedem erkannten Tag
    abgespielt wird - unabhaengig vom verknuepften Spiel."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        return False, f"Nicht unterstuetztes Audioformat: {ext or '(keine Endung)'}"

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _clear_existing_boot_sound_files()
    dest = AUDIO_DIR / f"{BOOT_SOUND_BASENAME}{ext}"
    dest.write_bytes(content)
    audio_config.set_boot_sound_path(str(dest.resolve()))
    return True, None


def remove_boot_sound():
    audio_player.stop()
    _clear_existing_boot_sound_files()
    audio_config.set_boot_sound_path(None)


def _clear_existing_video_files():
    """Analog zu _clear_existing_boot_sound_files(), aber fuer das globale
    Video (siehe set_video())."""
    for old in VIDEO_DIR.glob(f"{VIDEO_BASENAME}.*"):
        try:
            old.unlink()
        except OSError:
            pass


def set_video(filename, content):
    """Wie set_boot_sound(), aber fuer das eine globale Video, das im
    Video-Modus (siehe audio_config.py) bei jedem erkannten Tag statt eines
    Sounds vollflaechig abgespielt wird (siehe video_player.py)."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return False, f"Nicht unterstuetztes Videoformat: {ext or '(keine Endung)'}"

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    _clear_existing_video_files()
    dest = VIDEO_DIR / f"{VIDEO_BASENAME}{ext}"
    dest.write_bytes(content)
    audio_config.set_video_path(str(dest.resolve()))
    return True, None


def remove_video():
    video_player.stop()
    _clear_existing_video_files()
    audio_config.set_video_path(None)


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


def _render_game_rows(games, show_audio=True):
    """show_audio=False (Boot-Sound-Modus, siehe audio_config.py) blendet
    die komplette Sound-Spalte aus - die individuellen Spiel-Sounds bleiben
    dabei in games.db unangetastet, nur ihre Bedienelemente verschwinden
    vorübergehend, siehe render_page()."""
    colspan = 6 if show_audio else 5
    if not games:
        return (
            f"<tr><td colspan='{colspan}'>Keine Spiele gefunden. "
            "Erst <code>python3 ../game_scanner.py</code> ausfuehren.</td></tr>"
        )

    rows = []
    for game in games:
        badge = "installiert" if game["installed"] else "nicht installiert"
        color = game["color"] or "#00e5ff"

        audio_cell = ""
        if show_audio:
            audio_path = game["audio_path"]
            audio_enabled = bool(game["audio_enabled"])

            if audio_path:
                audio_name = _escape(Path(audio_path).name)
                # Umschalt-Button zeigt den aktuellen Zustand an und traegt in
                # 'enabled' bereits den Zielwert fuer den naechsten Klick (also
                # das jeweilige Gegenteil) - kein JS noetig, gleiches Muster wie
                # die uebrigen Formulare auf dieser Seite.
                toggle_label = "Aktiv" if audio_enabled else "Inaktiv"
                toggle_class = "" if audio_enabled else " class='secondary'"
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
                    "<form method='POST' action='/toggle_game_audio' class='inline-form'>"
                    f"<input type='hidden' name='uid' value='{game['uid']}'>"
                    f"<input type='hidden' name='enabled' value='{'0' if audio_enabled else '1'}'>"
                    f"<button type='submit'{toggle_class} "
                    "title='Automatische Wiedergabe beim Tag-Start umschalten'>"
                    f"{toggle_label}</button>"
                    "</form>"
                    "<form method='POST' action='/remove_game_audio' class='inline-form'>"
                    f"<input type='hidden' name='uid' value='{game['uid']}'>"
                    "<button type='submit' class='secondary'>&#10005;</button>"
                    "</form>"
                    "</div>"
                )
            else:
                audio_html = "<span class='unlinked'>kein Sound</span>"

            audio_cell = (
                "<td class='audio-cell'>"
                f"{audio_html}"
                "<form method='POST' action='/set_game_audio' enctype='multipart/form-data' class='inline-form'>"
                f"<input type='hidden' name='uid' value='{game['uid']}'>"
                "<input type='file' name='audio_file' accept='.mp3,.wav,.ogg,.flac,.m4a' onchange='this.form.submit()'>"
                "</form>"
                "</td>"
            )

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
            f"{audio_cell}"
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
    # Spiele, die bereits an einen ANDEREN Tag verknuepft sind, tauchen in
    # der Auswahlliste eines Tags nicht mehr auf (siehe Chatverlauf - sonst
    # liesse sich ein Spiel versehentlich an mehrere Tags gleichzeitig
    # haengen). Das eigene, bereits verknuepfte Spiel eines Tags bleibt in
    # dessen eigener Liste natuerlich weiterhin sichtbar/ausgewaehlt.
    linked_elsewhere = {t.get("game_uid") for t in tags if t.get("game_uid")}

    rows = []
    for tag in tags:
        uid = tag.get("uid", "")
        game_uid = tag.get("game_uid")

        options = ["<option value=''>Spiel waehlen ...</option>"]
        for g in games:
            if g["uid"] in linked_elsewhere and g["uid"] != game_uid:
                continue
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


def _render_global_media_section(current_path, icon, empty_label, play_action, stop_action, remove_action, upload_action, upload_field, accept):
    """Gemeinsamer Aufbau fuer die Boot-Sound- bzw. Video-Sektion im
    Audio-Modus-Panel (siehe _render_audio_mode_panel()): aktueller
    Dateiname + Test-Play/Stop/Entfernen-Buttons (falls hinterlegt) sowie
    das Upload-Feld fuer eine neue Datei - analog zum Sound-Bereich einer
    Spielzeile in _render_game_rows(), aber ohne 'uid' (gilt global statt
    pro Spiel) und ohne 'Aktiv/Inaktiv'-Umschalter (im Boot-Sound-/
    Video-Modus ist der jeweils gewaehlte Modus per Definition immer aktiv)."""
    if current_path:
        name = _escape(Path(current_path).name)
        current_html = (
            f"<div class='audio-current'>{icon} {name}</div>"
            "<div class='inline-form'>"
            f"<form method='POST' action='{play_action}' class='inline-form'>"
            "<button type='submit'>&#9658;</button>"
            "</form>"
            f"<form method='POST' action='{stop_action}' class='inline-form'>"
            "<button type='submit' class='secondary'>&#9632;</button>"
            "</form>"
            f"<form method='POST' action='{remove_action}' class='inline-form'>"
            "<button type='submit' class='secondary'>&#10005;</button>"
            "</form>"
            "</div>"
        )
    else:
        current_html = f"<span class='unlinked'>{empty_label}</span>"

    return (
        "<div style='margin-top:14px'>"
        f"{current_html}"
        f"<form method='POST' action='{upload_action}' enctype='multipart/form-data' "
        "class='inline-form' style='margin-top:8px'>"
        f"<input type='file' name='{upload_field}' accept='{accept}' onchange='this.form.submit()'>"
        "</form>"
        "</div>"
    )


def _render_audio_mode_panel():
    """Schalter oben auf der Seite zwischen den drei Sound-/Video-Modi
    (siehe audio_config.py) sowie - je nach gewaehltem Modus - die
    Upload-/Test-Bedienelemente fuer den einen globalen Boot-Sound bzw. das
    eine globale Video."""
    mode = audio_config.get_mode()
    songs_checked = " checked" if mode == audio_config.MODE_SONGS else ""
    boot_checked = " checked" if mode == audio_config.MODE_BOOT_SOUND else ""
    video_checked = " checked" if mode == audio_config.MODE_VIDEO else ""

    media_section = ""
    if mode == audio_config.MODE_BOOT_SOUND:
        media_section = _render_global_media_section(
            audio_config.get_boot_sound_path(), "&#127925;", "Kein Boot-Sound hinterlegt",
            "/play_boot_sound", "/stop_boot_sound", "/remove_boot_sound",
            "/set_boot_sound", "boot_sound_file", ".mp3,.wav,.ogg,.flac,.m4a",
        )
    elif mode == audio_config.MODE_VIDEO:
        media_section = _render_global_media_section(
            audio_config.get_video_path(), "&#127916;", "Kein Video hinterlegt",
            "/play_video", "/stop_video", "/remove_video",
            "/set_video", "video_file", ".mp4,.mkv,.webm,.avi,.mov",
        )

    return (
        "<form method='POST' action='/set_audio_mode' class='inline-form' style='gap:22px;flex-wrap:wrap'>"
        "<label class='inline-form' style='gap:6px'>"
        f"<input type='radio' name='mode' value='songs'{songs_checked} onchange='this.form.submit()'> "
        "Einzelne Songs je Spiel"
        "</label>"
        "<label class='inline-form' style='gap:6px'>"
        f"<input type='radio' name='mode' value='boot_sound'{boot_checked} onchange='this.form.submit()'> "
        "Ein Boot-Sound fuer alle Spiele"
        "</label>"
        "<label class='inline-form' style='gap:6px'>"
        f"<input type='radio' name='mode' value='video'{video_checked} onchange='this.form.submit()'> "
        "Ein Video (Vollbild) fuer alle Spiele"
        "</label>"
        "</form>"
        f"{media_section}"
    )


def _download_status():
    """Aktueller Download-Fortschritt (siehe download_monitor.py) fuer den
    Fortschritts-Zeiger auf dem Farbverlauf-Balken in
    _render_led_settings_panel() sowie fuer /api/state (von dort periodisch
    per JS abgefragt, siehe index.html/control.html) - liefert zusaetzlich
    den Spielnamen (ueber die appid in games.db aufgeloest), falls
    bekannt. Bewusst unabhaengig vom Glaettungszustand in
    pico_client._smoothed_download_progress() (laeuft in einem anderen
    Prozess/Service) - der Zeiger zeigt daher den rohen, nicht
    interpolierten Wert, was fuer eine Positionsanzeige ausreicht."""
    info = download_monitor.get_download_progress()
    if info is None:
        return {"active": False, "progress": None, "appid": None, "name": None}

    appid, progress = info
    name = None
    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute("SELECT name FROM games WHERE appid = ?", (appid,)).fetchone()
            if row:
                name = row[0]
        finally:
            conn.close()

    return {"active": True, "progress": progress, "appid": appid, "name": name}


def _hsv_lerp(color1, color2, t):
    """Interpoliert zwischen zwei Hex-Farben im HSV-Farbton - dieselbe
    Rechnung wie pico_client._hsv_lerp(), hier dupliziert statt importiert
    (gui_server.py und pico_client.py laufen als getrennte Prozesse/Dienste,
    siehe Modul-Docstrings), damit die Vorschau exakt zeigt, was
    tatsaechlich auf den LEDs zu sehen sein wird."""
    h1, s1, v1 = colorsys.rgb_to_hsv(int(color1[1:3], 16) / 255, int(color1[3:5], 16) / 255, int(color1[5:7], 16) / 255)
    h2, s2, v2 = colorsys.rgb_to_hsv(int(color2[1:3], 16) / 255, int(color2[3:5], 16) / 255, int(color2[5:7], 16) / 255)
    h = h1 + (h2 - h1) * t
    s = s1 + (s2 - s1) * t
    v = v1 + (v2 - v1) * t
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _gradient_preview_css(start, mid, end, steps=10):
    """CSS linear-gradient() fuer die Vorschau des Download-Farbverlaufs -
    stueckweise HSV-Interpolation (0-50% Start->Mitte, 50-100% Mitte->Ende),
    identisch zu pico_client._download_gradient_color()."""
    stops = []
    for i in range(steps + 1):
        t = i / steps
        color = _hsv_lerp(start, mid, t / 0.5) if t <= 0.5 else _hsv_lerp(mid, end, (t - 0.5) / 0.5)
        stops.append(f"{color} {round(t * 100)}%")
    return f"linear-gradient(90deg, {', '.join(stops)})"


def _render_led_settings_panel():
    """Eigener Abschnitt fuer die allgemeinen LED-Einstellungen (siehe
    led_settings.py): Hauptschalter fuer die gesamte LED-Synchronisation
    (Led_Pico + lokale USB-RGB-Geraete ueber OpenRGB, siehe
    pico_client.update_led()), die Leerlauf-Farbe ("Konsole an" -
    angezeigt, wenn kein Tag aufliegt bzw. weder Tag noch Spiel eine eigene
    Farbe haben), der Schalter fuer das Sleep/Shutdown-Blinken (siehe
    pico_client._start_sleep_shutdown_listener()), der Schalter fuer das
    Download-Pulsieren sowie dessen Start-/Endfarbe (siehe
    pico_client._download_monitor_loop()/_download_gradient_color()).
    Gleiches Umschalt-Button-Muster wie beim Sound-Aktiv/Inaktiv-Umschalter
    in _render_game_rows()."""
    settings = led_settings.load_config()
    enabled = bool(settings.get("enabled", True))
    idle_color = settings.get("idle_color") or "#ffffff"
    blink_on_sleep = bool(settings.get("blink_on_sleep", True))
    download_pulse = bool(settings.get("download_pulse", True))
    gradient_start = settings.get("download_gradient_start") or "#ff0000"
    gradient_mid = settings.get("download_gradient_mid") or "#ffff00"
    gradient_end = settings.get("download_gradient_end") or "#00ff00"
    gradient_enabled = bool(settings.get("download_gradient_enabled", True))

    def _switch(action, field, current, title):
        cls = "switch on" if current else "switch off"
        return (
            f"<form method='POST' action='{action}' class='inline-form'>"
            f"<input type='hidden' name='{field}' value='{'0' if current else '1'}'>"
            f"<button type='submit' class='{cls}' title='{title}'></button>"
            "</form>"
        )

    gradient_css = _gradient_preview_css(gradient_start, gradient_mid, gradient_end)
    download = _download_status()
    if download["active"] and download["progress"] is not None:
        marker_pct = max(0.0, min(1.0, download["progress"])) * 100
        marker_style = f"left:{marker_pct:.1f}%"
        marker_label = f"{marker_pct:.0f}%"
        if download["name"]:
            marker_label += f" &middot; {_escape(download['name'])}"
    else:
        marker_style = "display:none"
        marker_label = ""

    return (
        "<div class='led-panel'>"

        "<div class='led-group'>"
        "<p class='led-group-title'><span class='swatch-dot'></span>Allgemein</p>"
        "<div class='led-row'>"
        "<div class='led-row-label'>LED-Synchronisation<small>Led_Pico + lokale USB-RGB-Geraete (OpenRGB) gemeinsam</small></div>"
        + _switch("/set_led_enabled", "enabled", enabled, "Schaltet Led_Pico und lokale USB-RGB-LEDs gemeinsam ein/aus")
        + "</div>"
        "<div class='led-row'>"
        "<div class='led-row-label'>Leerlauf-Farbe (&quot;Konsole an&quot;)<small>Angezeigt, wenn kein Tag/Spiel eine eigene Farbe hat</small></div>"
        "<form method='POST' action='/set_idle_led_color' class='color-field'>"
        f"<input type='color' name='color' value='{idle_color}' onchange='this.form.submit()'>"
        f"<span class='hex'>{idle_color}</span>"
        "</form>"
        "</div>"
        "</div>"

        "<div class='led-group'>"
        "<p class='led-group-title'><span class='swatch-dot'></span>Sleep &amp; Shutdown</p>"
        "<div class='led-row'>"
        "<div class='led-row-label'>Blinken beim Einschlafen/Herunterfahren<small>Kurzes Blinken in der zuletzt gezeigten Farbe</small></div>"
        + _switch("/set_blink_on_sleep", "enabled", blink_on_sleep, "LEDs kurz blinken lassen, sobald der PC in den Standby geht oder herunterfaehrt")
        + "</div>"
        "</div>"

        "<div class='led-group'>"
        "<p class='led-group-title'><span class='swatch-dot'></span>Download-Anzeige</p>"
        "<div class='led-row'>"
        "<div class='led-row-label'>Download-Pulsieren<small>Sanftes Pulsieren waehrend Steam etwas laedt/aktualisiert</small></div>"
        + _switch("/set_download_pulse", "enabled", download_pulse, "LEDs waehrend eines laufenden Steam-Downloads sanft pulsieren lassen")
        + "</div>"
        "<div class='led-row'>"
        "<div class='led-row-label'>Farbverlauf im Leerlauf<small>An: Rot-Gelb-Gruen je Fortschritt &middot; Aus: normale Leerlauf-Farbe. Mit Tag wird immer in dessen Spielfarbe gepulst.</small></div>"
        + _switch("/set_download_gradient_enabled", "enabled", gradient_enabled, "Steuert nur den Leerlauf-Fall: An = Rot-Gelb-Gruen-Verlauf je Downloadfortschritt, Aus = stattdessen in der normalen Leerlauf-Farbe pulsieren")
        + "</div>"
        "<div class='led-row'>"
        "<div class='led-row-label'>Verlauffarben<small>Bei 0% / 50% / 100% Downloadfortschritt</small></div>"
        "<form method='POST' action='/set_download_gradient_start' class='color-field'>"
        f"<input type='color' name='color' value='{gradient_start}' onchange='this.form.submit()'>"
        "</form>"
        "<form method='POST' action='/set_download_gradient_mid' class='color-field'>"
        f"<input type='color' name='color' value='{gradient_mid}' onchange='this.form.submit()'>"
        "</form>"
        "<form method='POST' action='/set_download_gradient_end' class='color-field'>"
        f"<input type='color' name='color' value='{gradient_end}' onchange='this.form.submit()'>"
        "</form>"
        f"<div class='gradient-preview' style='background:{gradient_css}'>"
        f"<div class='gradient-marker' id='gradient-marker' style='{marker_style}'>"
        f"<span class='gradient-marker-label' id='gradient-marker-label'>{marker_label}</span>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"

        "</div>"
    )


def render_page(message_html=""):
    games = fetch_games()
    show_audio = audio_config.get_mode() == audio_config.MODE_SONGS

    config = pico_link.load_config()
    tcp_port = config.get("tcp_port", 5005)
    pico_ip = _resolve_pico_ip(config)
    tags = pico_link.fetch_tags(pico_ip, tcp_port) if pico_ip else None

    page = PAGE_TEMPLATE.replace("__MESSAGE__", message_html)
    page = page.replace("__AUDIO_MODE_PANEL__", _render_audio_mode_panel())
    page = page.replace("__LED_SETTINGS_PANEL__", _render_led_settings_panel())
    page = page.replace("__SOUND_TH__", "<th>Sound</th>" if show_audio else "")
    page = page.replace("__ROWS__", _render_game_rows(games, show_audio))
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
            "audio_enabled": bool(g["audio_enabled"]),
        }
        for g in games
    ]
    boot_sound_path = audio_config.get_boot_sound_path()
    video_path = audio_config.get_video_path()
    return {
        "ok": True,
        "app_version": VERSION,
        "games": games_json,
        "tags": tags if tags is not None else [],
        "pico_reachable": tags is not None,
        "audio_mode": audio_config.get_mode(),
        "has_boot_sound": bool(boot_sound_path),
        "boot_sound_name": Path(boot_sound_path).name if boot_sound_path else None,
        "has_video": bool(video_path),
        "video_name": Path(video_path).name if video_path else None,
        "led_enabled": led_settings.is_enabled(),
        "idle_led_color": led_settings.get_idle_color(),
        "blink_on_sleep": led_settings.is_blink_on_sleep_enabled(),
        "download_pulse": led_settings.is_download_pulse_enabled(),
        "download_gradient_start": led_settings.get_download_gradient_start(),
        "download_gradient_mid": led_settings.get_download_gradient_mid(),
        "download_gradient_end": led_settings.get_download_gradient_end(),
        "download_gradient_enabled": led_settings.is_download_gradient_enabled(),
        **{f"download_{k}": v for k, v in _download_status().items()},
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
    "/api/forget_tag": "_api_forget_tag",
    "/api/set_game_audio": "_api_set_game_audio",
    "/api/remove_game_audio": "_api_remove_game_audio",
    "/api/toggle_game_audio": "_api_toggle_game_audio",
    "/api/play_game_audio": "_api_play_game_audio",
    "/api/stop_game_audio": "_api_stop_game_audio",
    "/api/set_audio_mode": "_api_set_audio_mode",
    "/api/set_boot_sound": "_api_set_boot_sound",
    "/api/remove_boot_sound": "_api_remove_boot_sound",
    "/api/play_boot_sound": "_api_play_boot_sound",
    "/api/stop_boot_sound": "_api_stop_boot_sound",
    "/api/set_video": "_api_set_video",
    "/api/remove_video": "_api_remove_video",
    "/api/play_video": "_api_play_video",
    "/api/stop_video": "_api_stop_video",
    "/api/set_led_enabled": "_api_set_led_enabled",
    "/api/set_idle_led_color": "_api_set_idle_led_color",
    "/api/set_blink_on_sleep": "_api_set_blink_on_sleep",
    "/api/set_download_pulse": "_api_set_download_pulse",
    "/api/set_download_gradient_start": "_api_set_download_gradient_start",
    "/api/set_download_gradient_mid": "_api_set_download_gradient_mid",
    "/api/set_download_gradient_end": "_api_set_download_gradient_end",
    "/api/set_download_gradient_enabled": "_api_set_download_gradient_enabled",
    "/api/reset_all_colors": "_api_reset_all_colors",
}


class _ReusableTCPServer(socketserver.TCPServer):
    """socketserver.TCPServer setzt standardmaessig kein SO_REUSEADDR - nach
    jedem Neustart (z. B. systemctl restart, oder waehrend der Entwicklung)
    kann der Port dadurch bis zu ~60s im TIME_WAIT haengen bleiben (sobald
    zwischenzeitlich mindestens eine Client-Verbindung bestand), der naechste
    Start schlaegt dann mit 'Address already in use' fehl, obwohl kein
    anderer Prozess den Port tatsaechlich noch haelt."""
    allow_reuse_address = True


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
        if self.path == "/":
            # Neue Startseite: das Controller-Einstellungsmenue (LEDs,
            # Sound, Spiele-/Tag-Zuordnung) - Spielstart selbst uebernimmt
            # Steam Big Picture, das gehoert hier nicht mehr her. Baut sich
            # komplett per fetch('/api/state') selbst auf, deshalb ohne
            # Platzhalter-Ersetzung wie bei render_page() unveraendert
            # ausgeliefert.
            self._respond(DASHBOARD_TEMPLATE)
            return
        if self.path == "/admin":
            # Bisherige Verwaltungs-GUI (Tags, Sounds, LED-Einstellungen,
            # Datei-Uploads) - frueher unter '/', jetzt hinter dem Menue.
            self._respond(render_page())
            return
        self.send_response(404)
        self.end_headers()

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
            "/forget_tag": self._handle_forget_tag,
            "/set_game_audio": self._handle_set_game_audio,
            "/remove_game_audio": self._handle_remove_game_audio,
            "/toggle_game_audio": self._handle_toggle_game_audio,
            "/play_game_audio": self._handle_play_game_audio,
            "/stop_game_audio": self._handle_stop_game_audio,
            "/set_audio_mode": self._handle_set_audio_mode,
            "/set_boot_sound": self._handle_set_boot_sound,
            "/remove_boot_sound": self._handle_remove_boot_sound,
            "/play_boot_sound": self._handle_play_boot_sound,
            "/stop_boot_sound": self._handle_stop_boot_sound,
            "/set_video": self._handle_set_video,
            "/remove_video": self._handle_remove_video,
            "/play_video": self._handle_play_video,
            "/stop_video": self._handle_stop_video,
            "/set_led_enabled": self._handle_set_led_enabled,
            "/set_idle_led_color": self._handle_set_idle_led_color,
            "/set_blink_on_sleep": self._handle_set_blink_on_sleep,
            "/set_download_pulse": self._handle_set_download_pulse,
            "/set_download_gradient_start": self._handle_set_download_gradient_start,
            "/set_download_gradient_mid": self._handle_set_download_gradient_mid,
            "/set_download_gradient_end": self._handle_set_download_gradient_end,
            "/set_download_gradient_enabled": self._handle_set_download_gradient_enabled,
            "/reset_all_colors": self._handle_reset_all_colors,
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

    def _handle_toggle_game_audio(self, form):
        uid = form.get("uid", [""])[0]
        if not uid:
            return "<div class='message error'>Keine Spiel-UID angegeben.</div>"
        enabled = form.get("enabled", ["1"])[0] == "1"
        set_game_audio_enabled(uid, enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return f"<div class='message success'>Automatische Wiedergabe {zustand}.</div>"

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

    def _handle_set_audio_mode(self, form):
        mode = form.get("mode", [""])[0]
        if mode not in audio_config.VALID_MODES:
            return "<div class='message error'>Ungueltiger Sound-Modus.</div>"
        audio_config.set_mode(mode)
        label = AUDIO_MODE_LABELS[mode]
        return f"<div class='message success'>Sound-Modus umgestellt: {label}.</div>"

    def _handle_set_boot_sound(self, form):
        upload = form.get("boot_sound_file", [None])[0]
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return "<div class='message error'>Keine Datei ausgewaehlt.</div>"

        ok, error = set_boot_sound(upload["filename"], upload["content"])
        if ok:
            return f"<div class='message success'>Boot-Sound '{_escape(upload['filename'])}' gespeichert.</div>"
        return f"<div class='message error'>{_escape(error)}</div>"

    def _handle_remove_boot_sound(self, form):
        remove_boot_sound()
        return "<div class='message success'>Boot-Sound entfernt.</div>"

    def _handle_play_boot_sound(self, form):
        path = audio_config.get_boot_sound_path()
        if not path:
            return "<div class='message error'>Kein Boot-Sound hinterlegt.</div>"
        audio_player.play(path)
        return "<div class='message success'>Wiedergabe gestartet.</div>"

    def _handle_stop_boot_sound(self, form):
        audio_player.stop()
        return "<div class='message success'>Wiedergabe gestoppt.</div>"

    def _handle_set_video(self, form):
        upload = form.get("video_file", [None])[0]
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return "<div class='message error'>Keine Datei ausgewaehlt.</div>"

        ok, error = set_video(upload["filename"], upload["content"])
        if ok:
            return f"<div class='message success'>Video '{_escape(upload['filename'])}' gespeichert.</div>"
        return f"<div class='message error'>{_escape(error)}</div>"

    def _handle_remove_video(self, form):
        remove_video()
        return "<div class='message success'>Video entfernt.</div>"

    def _handle_play_video(self, form):
        path = audio_config.get_video_path()
        if not path:
            return "<div class='message error'>Kein Video hinterlegt.</div>"
        video_player.play(path)
        return "<div class='message success'>Wiedergabe gestartet.</div>"

    def _handle_stop_video(self, form):
        video_player.stop()
        return "<div class='message success'>Wiedergabe gestoppt.</div>"

    def _handle_set_led_enabled(self, form):
        enabled = form.get("enabled", ["1"])[0] == "1"
        led_settings.set_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return f"<div class='message success'>LEDs {zustand}.</div>"

    def _handle_set_idle_led_color(self, form):
        color = form.get("color", ["#ffffff"])[0]
        led_settings.set_idle_color(color)
        return "<div class='message success'>Leerlauf-Farbe gespeichert.</div>"

    def _handle_set_blink_on_sleep(self, form):
        enabled = form.get("enabled", ["1"])[0] == "1"
        led_settings.set_blink_on_sleep_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return f"<div class='message success'>Blinken bei Sleep/Shutdown {zustand}.</div>"

    def _handle_set_download_pulse(self, form):
        enabled = form.get("enabled", ["1"])[0] == "1"
        led_settings.set_download_pulse_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return f"<div class='message success'>Download-Pulsieren {zustand}.</div>"

    def _handle_set_download_gradient_start(self, form):
        color = form.get("color", ["#ff0000"])[0]
        led_settings.set_download_gradient_start(color)
        return "<div class='message success'>Download-Farbe bei 0% gespeichert.</div>"

    def _handle_set_download_gradient_mid(self, form):
        color = form.get("color", ["#ffff00"])[0]
        led_settings.set_download_gradient_mid(color)
        return "<div class='message success'>Download-Farbe bei 50% gespeichert.</div>"

    def _handle_set_download_gradient_end(self, form):
        color = form.get("color", ["#00ff00"])[0]
        led_settings.set_download_gradient_end(color)
        return "<div class='message success'>Download-Farbe bei 100% gespeichert.</div>"

    def _handle_set_download_gradient_enabled(self, form):
        enabled = form.get("enabled", ["1"])[0] == "1"
        led_settings.set_download_gradient_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return f"<div class='message success'>Download-Farbverlauf {zustand}.</div>"

    def _handle_reset_all_colors(self, form):
        count = game_scanner.reset_all_colors()
        return f"<div class='message success'>Farben von {count} Spiel(en) auf ihre Cover-Durchschnittsfarbe zurueckgesetzt.</div>"

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

    def _api_toggle_game_audio(self, data):
        uid = data.get("uid", "")
        if not uid:
            return {"ok": False, "message": "Keine Spiel-UID angegeben."}
        enabled = bool(data.get("enabled"))
        set_game_audio_enabled(uid, enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return {"ok": True, "message": f"Automatische Wiedergabe {zustand}."}

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

    def _api_set_audio_mode(self, data):
        mode = data.get("mode", "")
        if mode not in audio_config.VALID_MODES:
            return {"ok": False, "message": "Ungueltiger Sound-Modus."}
        audio_config.set_mode(mode)
        label = AUDIO_MODE_LABELS[mode]
        return {"ok": True, "message": f"Sound-Modus umgestellt: {label}."}

    def _api_set_boot_sound(self, data):
        upload = data.get("boot_sound_file")
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return {"ok": False, "message": "Keine Datei ausgewaehlt."}

        ok, error = set_boot_sound(upload["filename"], upload["content"])
        if ok:
            return {"ok": True, "message": f"Boot-Sound '{upload['filename']}' gespeichert."}
        return {"ok": False, "message": error}

    def _api_remove_boot_sound(self, data):
        remove_boot_sound()
        return {"ok": True, "message": "Boot-Sound entfernt."}

    def _api_play_boot_sound(self, data):
        path = audio_config.get_boot_sound_path()
        if not path:
            return {"ok": False, "message": "Kein Boot-Sound hinterlegt."}
        audio_player.play(path)
        return {"ok": True, "message": "Wiedergabe gestartet."}

    def _api_stop_boot_sound(self, data):
        audio_player.stop()
        return {"ok": True, "message": "Wiedergabe gestoppt."}

    def _api_set_video(self, data):
        upload = data.get("video_file")
        if not upload or not isinstance(upload, dict) or not upload.get("filename"):
            return {"ok": False, "message": "Keine Datei ausgewaehlt."}

        ok, error = set_video(upload["filename"], upload["content"])
        if ok:
            return {"ok": True, "message": f"Video '{upload['filename']}' gespeichert."}
        return {"ok": False, "message": error}

    def _api_remove_video(self, data):
        remove_video()
        return {"ok": True, "message": "Video entfernt."}

    def _api_play_video(self, data):
        path = audio_config.get_video_path()
        if not path:
            return {"ok": False, "message": "Kein Video hinterlegt."}
        video_player.play(path)
        return {"ok": True, "message": "Wiedergabe gestartet."}

    def _api_stop_video(self, data):
        video_player.stop()
        return {"ok": True, "message": "Wiedergabe gestoppt."}

    def _api_set_led_enabled(self, data):
        enabled = bool(data.get("enabled"))
        led_settings.set_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return {"ok": True, "message": f"LEDs {zustand}."}

    def _api_set_idle_led_color(self, data):
        color = data.get("color", "#ffffff")
        led_settings.set_idle_color(color)
        return {"ok": True, "message": "Leerlauf-Farbe gespeichert."}

    def _api_set_blink_on_sleep(self, data):
        enabled = bool(data.get("enabled"))
        led_settings.set_blink_on_sleep_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return {"ok": True, "message": f"Blinken bei Sleep/Shutdown {zustand}."}

    def _api_set_download_pulse(self, data):
        enabled = bool(data.get("enabled"))
        led_settings.set_download_pulse_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return {"ok": True, "message": f"Download-Pulsieren {zustand}."}

    def _api_set_download_gradient_start(self, data):
        color = data.get("color", "#ff0000")
        led_settings.set_download_gradient_start(color)
        return {"ok": True, "message": "Download-Farbe bei 0% gespeichert."}

    def _api_set_download_gradient_mid(self, data):
        color = data.get("color", "#ffff00")
        led_settings.set_download_gradient_mid(color)
        return {"ok": True, "message": "Download-Farbe bei 50% gespeichert."}

    def _api_set_download_gradient_end(self, data):
        color = data.get("color", "#00ff00")
        led_settings.set_download_gradient_end(color)
        return {"ok": True, "message": "Download-Farbe bei 100% gespeichert."}

    def _api_set_download_gradient_enabled(self, data):
        enabled = bool(data.get("enabled"))
        led_settings.set_download_gradient_enabled(enabled)
        zustand = "aktiviert" if enabled else "deaktiviert"
        return {"ok": True, "message": f"Download-Farbverlauf {zustand}."}

    def _api_reset_all_colors(self, data):
        count = game_scanner.reset_all_colors()
        return {"ok": True, "message": f"Farben von {count} Spiel(en) auf ihre Cover-Durchschnittsfarbe zurueckgesetzt."}

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
    with _ReusableTCPServer((host, port), Handler) as httpd:
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
