#!/usr/bin/env python3
"""Natives Controller-Einstellungsmenue - Ersatz fuer den Browser-Kiosk
(dashboard.html) als Big-Picture-Ziel (siehe launch_dashboard.py).

Grund: Chromes Gamepad-Web-API liefert unter Wayland (SteamOS/Bazzite)
keine zuverlaessigen Controller-Events, wenn die Seite von Steam aus
gestartet wird - weder ueber Steam Input (Eintrags-Schalter UND globale
"Xbox/PlayStation/Generic-Konfigurationsunterstuetzung" probiert) noch
ohne. Dieses Programm liest den Controller stattdessen direkt ueber SDL2
(pygame-ce, siehe README fuer den Installationshinweis - "pygame" selbst
hat fuer neuere Python-Versionen oft noch kein vorgebautes Wheel, "pygame-ce"
ist ein API-kompatibler Fork mit aktuelleren Wheels, siehe
https://pyga.me/) - dieselbe ausgereifte Eingabe-Schicht, die auch echte
native Linux-Spiele fuer Controller-Support nutzen, unabhaengig von
Fenster-Fokus-Weiterleitung durch Compositor/Steam/Browser.

Spricht dieselbe JSON-API wie dashboard.html (siehe gui_server.py,
API_ROUTES) - das Backend selbst ist unveraendert, dieses Programm ist
nur eine zweite, native Praesentationsschicht fuer dieselben Daten/
Aktionen. Menue-Struktur (Kategorien, Zeilen-Typen, Navigation) ist ein
bewusster 1:1-Port von dashboard.html, damit sich beide identisch
anfuehlen.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pygame
import pygame._sdl2.controller as sdl2_controller

STEAMOS_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = STEAMOS_DIR / "config.json"

FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# -- Farben (identisch zu den CSS-Variablen in dashboard.html) --------------
BG = (8, 11, 16)
PANEL = (17, 21, 29)
PANEL2 = (22, 28, 39)
BORDER = (35, 44, 61)
CYAN = (0, 229, 255)
CYAN_DIM = (8, 145, 168)
MAGENTA = (255, 46, 151)
GREEN = (57, 255, 140)
AMBER = (255, 178, 56)
RED = (255, 77, 109)
TEXT = (232, 237, 245)
DIM = (118, 134, 160)

PALETTE = [
    "#ff4d6d", "#ff8800", "#ffb238", "#ffe14d", "#39ff8c", "#00e5ff",
    "#0891a8", "#3b82f6", "#7c5cff", "#ff2e97", "#ffffff", "#7686a0",
]

AUDIO_MODES = ["songs", "boot_sound", "video"]
AUDIO_MODE_LABELS = {
    "songs": "Einzelne Songs je Spiel",
    "boot_sound": "Ein Boot-Sound für alle Spiele",
    "video": "Ein Video (Vollbild) für alle Spiele",
}

CATEGORIES = [
    ("leds", "LEDs"),
    ("sound", "Sound"),
    ("games", "Spiele"),
    ("tags", "Tags"),
    ("tools", "Werkzeuge"),
    ("info", "Info"),
]


def hex_to_rgb(color):
    color = color or "#7686a0"
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


# -- Backend-Anbindung (dasselbe /api/* wie dashboard.html) -----------------
def _gui_port():
    port = 8090
    if CONFIG_PATH.is_file():
        try:
            port = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("gui_port", 8090)
        except (OSError, ValueError):
            pass
    return port


BASE_URL = f"http://127.0.0.1:{_gui_port()}"


def api(path, body=None):
    try:
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            BASE_URL + path, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except (OSError, urllib.error.URLError, ValueError):
        return {"ok": False, "message": "Server nicht erreichbar."}


def fetch_state():
    try:
        with urllib.request.urlopen(BASE_URL + "/api/state", timeout=8) as resp:
            return json.loads(resp.read())
    except (OSError, urllib.error.URLError, ValueError):
        return None


def wait_for_server(timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fetch_state() is not None:
            return True
        time.sleep(0.5)
    return False


# -- Zeilen-Modell ------------------------------------------------------
# Direktes Pendant zu den *Row()-Baustein-Funktionen in dashboard.html -
# jede Kategorie liefert eine Liste von Row-Objekten, render()/dispatch()
# bedienen sie generisch ueber ihren 'type'.
class Row:
    def __init__(self, type_, label, **kw):
        self.type = type_
        self.label = label
        self.value_fn = kw.get("value_fn")
        self.hint_fn = kw.get("hint_fn")
        self.color_fn = kw.get("color_fn")
        self.badge_fn = kw.get("badge_fn")
        self.subtext_fn = kw.get("subtext_fn")
        self.on_activate = kw.get("on_activate")
        self.on_cycle = kw.get("on_cycle")


def toggle_row(label, value, setter):
    def activate():
        r = setter(not value)
        toast(r.get("message"), r.get("ok"))
        request_reload()
    return Row("toggle", label, value_fn=lambda: value, on_activate=activate)


def color_row(label, color, setter):
    def cycle(direction):
        try:
            idx = PALETTE.index((color or "").lower())
        except ValueError:
            idx = -1
        nxt = PALETTE[0] if idx < 0 else PALETTE[(idx + direction) % len(PALETTE)]
        r = setter(nxt)
        toast(r.get("message"), r.get("ok"))
        request_reload()
    return Row(
        "color", label,
        color_fn=lambda: hex_to_rgb(color),
        hint_fn=lambda: (color or "#7686a0").upper(),
        on_cycle=cycle,
    )


def enum_row(label, value, options, label_fn, setter):
    def set_value(nxt):
        r = setter(nxt)
        toast(r.get("message"), r.get("ok"))
        request_reload()

    def cycle(direction):
        idx = options.index(value) if value in options else -1
        set_value(options[0] if idx < 0 else options[(idx + direction) % len(options)])

    def activate():
        idx = options.index(value) if value in options else -1
        set_value(options[(idx + 1) % len(options)])

    return Row("enum", label, hint_fn=lambda: label_fn(value), on_cycle=cycle, on_activate=activate)


def button_row(label, action):
    def activate():
        r = action()
        if isinstance(r, dict) and "ok" in r:
            toast(r.get("message"), r.get("ok"))
            request_reload()
    return Row("button", label, on_activate=activate)


def info_row(label):
    return Row("info", label)


def stat_row(label, value):
    return Row("stat", label, hint_fn=lambda: value)


# -- Kategorien (1:1 Port der *Rows()-Funktionen aus dashboard.html) -------
def leds_rows(state):
    return [
        toggle_row("LED-Synchronisation", state["led_enabled"],
                   lambda v: api("/api/set_led_enabled", {"enabled": v})),
        color_row('Leerlauf-Farbe ("Konsole an")', state["idle_led_color"],
                  lambda c: api("/api/set_idle_led_color", {"color": c})),
        toggle_row("Blinken bei Sleep/Shutdown", state["blink_on_sleep"],
                   lambda v: api("/api/set_blink_on_sleep", {"enabled": v})),
        toggle_row("Download-Pulsieren", state["download_pulse"],
                   lambda v: api("/api/set_download_pulse", {"enabled": v})),
        toggle_row("Farbverlauf im Leerlauf", state["download_gradient_enabled"],
                   lambda v: api("/api/set_download_gradient_enabled", {"enabled": v})),
        color_row("Verlauf-Startfarbe (0%)", state["download_gradient_start"],
                  lambda c: api("/api/set_download_gradient_start", {"color": c})),
        color_row("Verlauf-Mittelfarbe (50%)", state["download_gradient_mid"],
                  lambda c: api("/api/set_download_gradient_mid", {"color": c})),
        color_row("Verlauf-Endfarbe (100%)", state["download_gradient_end"],
                  lambda c: api("/api/set_download_gradient_end", {"color": c})),
    ]


def sound_rows(state):
    rows = [enum_row(
        "Sound-Modus", state["audio_mode"], AUDIO_MODES,
        lambda m: AUDIO_MODE_LABELS.get(m, m),
        lambda mode: api("/api/set_audio_mode", {"mode": mode}),
    )]
    mode = state["audio_mode"]
    if mode == "boot_sound":
        if state["has_boot_sound"]:
            rows.append(button_row(f"▶ Boot-Sound abspielen ({state['boot_sound_name']})",
                                    lambda: api("/api/play_boot_sound", {})))
            rows.append(button_row("■ Wiedergabe stoppen", lambda: api("/api/stop_boot_sound", {})))
        else:
            rows.append(info_row("Kein Boot-Sound hinterlegt - Upload unter /admin."))
    elif mode == "video":
        if state["has_video"]:
            rows.append(button_row(f"▶ Video abspielen ({state['video_name']})",
                                    lambda: api("/api/play_video", {})))
            rows.append(button_row("■ Wiedergabe stoppen", lambda: api("/api/stop_video", {})))
        else:
            rows.append(info_row("Kein Video hinterlegt - Upload unter /admin."))
    else:
        rows.append(info_row('Sound pro Spiel: siehe Kategorie "Spiele".'))
    return rows


def games_rows(state):
    games = state["games"]
    if not games:
        return [info_row("Keine Spiele gefunden. Zuerst game_scanner.py ausführen.")]
    rows = []
    for g in games:
        def make(game):
            def activate():
                open_game_actions(game)
            sub = ("Sound: " + ("aktiv" if game["audio_enabled"] else "inaktiv")) if game["has_audio"] else "Kein Sound"
            row = Row(
                "list-item", game["name"],
                color_fn=lambda: hex_to_rgb(game["color"]),
                badge_fn=lambda: None if game["installed"] else "nicht installiert",
                subtext_fn=lambda: sub,
                on_activate=activate,
            )
            return row
        rows.append(make(g))
    return rows


def open_game_actions(game):
    items = [color_row("Farbe", game["color"],
                        lambda c: api("/api/set_game_color", {"uid": game["uid"], "color": c}))]
    if game["has_audio"]:
        items.append(toggle_row(
            "Sound: Aktiv" if game["audio_enabled"] else "Sound: Inaktiv",
            game["audio_enabled"],
            lambda v: api("/api/toggle_game_audio", {"uid": game["uid"], "enabled": v}),
        ))
        items.append(button_row("▶ Sound testen", lambda: api("/api/play_game_audio", {"uid": game["uid"]})))
        items.append(button_row("■ Wiedergabe stoppen", lambda: api("/api/stop_game_audio", {})))
    else:
        items.append(info_row("Kein Sound hinterlegt - Upload unter /admin."))
    items.append(button_row("Für nächsten Tag vormerken",
                             lambda: api("/api/select_game", {"uid": game["uid"]})))
    open_submenu("Spiel: " + game["name"], items)


def short_uid(uid):
    return uid[:6] + "…" + uid[-4:] if len(uid) > 14 else uid


def tags_rows(state):
    tags = state["tags"]
    if not tags:
        return [info_row("Noch keine Tags erkannt. Einen Tag an den RC522 halten.")]
    game_names = {g["uid"]: g["name"] for g in state["games"]}
    rows = []
    for t in tags:
        def make(tag):
            sub = ("→ " + game_names.get(tag.get("game_uid"), tag.get("game_uid"))) if tag.get("game_uid") else "nicht verknüpft"
            return Row(
                "list-item", short_uid(tag["uid"]),
                color_fn=lambda: hex_to_rgb(tag.get("color")),
                subtext_fn=lambda: sub,
                on_activate=lambda: open_tag_actions(tag, state),
            )
        rows.append(make(t))
    return rows


def open_tag_actions(tag, state):
    items = [button_row("Verknüpfen mit...", lambda: open_game_picker(tag, state) or None)]
    if tag.get("game_uid"):
        items.append(button_row("Trennen", lambda: api("/api/unlink_tag", {"uid": tag["uid"]})))
    items.append(color_row("Farbe", tag.get("color"),
                            lambda c: api("/api/set_tag_color", {"uid": tag["uid"], "color": c})))

    def delete():
        r = api("/api/forget_tag", {})
        close_submenu()
        if r.get("ok"):
            return {"ok": True, "message": "Löschmodus aktiv - jetzt den Tag an den RC522 halten."}
        return r
    items.append(button_row("Löschen...", delete))
    open_submenu("Tag: " + short_uid(tag["uid"]), items)


def open_game_picker(tag, state):
    games = state["games"]
    if not games:
        open_submenu("Verknüpfen: " + short_uid(tag["uid"]), [info_row("Keine Spiele in der Datenbank.")])
        return

    def make(game):
        def activate():
            r = api("/api/link_tag", {"uid": tag["uid"], "game_uid": game["uid"]})
            close_submenu()
            close_submenu()
            return r
        return button_row(game["name"], activate)
    open_submenu("Verknüpfen: " + short_uid(tag["uid"]), [make(g) for g in games])


_tools_confirm_armed = False


def tools_rows(_state):
    global _tools_confirm_armed

    def activate():
        global _tools_confirm_armed
        if not _tools_confirm_armed:
            _tools_confirm_armed = True
            return
        _tools_confirm_armed = False
        r = api("/api/reset_all_colors", {})
        toast(r.get("message"), r.get("ok"))
        request_reload()

    label = "Wirklich ALLE Spielfarben zurücksetzen? (A = Ja)" if _tools_confirm_armed else "Farben zurücksetzen..."
    return [Row("button", label, on_activate=activate)]


def info_rows(state):
    return [
        stat_row("Version", state.get("app_version") or "–"),
        stat_row("Hersteller", "BolliSoft"),
        stat_row("Code", "Nico Bollhalder"),
    ]


CATEGORY_ROWS = {
    "leds": leds_rows,
    "sound": sound_rows,
    "games": games_rows,
    "tags": tags_rows,
    "tools": tools_rows,
    "info": info_rows,
}


# -- Navigations-/Anwendungszustand --------------------------------------
class AppState:
    def __init__(self):
        self.state = None
        self.focus_zone = "sidebar"  # 'sidebar' | 'content'
        self.category_index = 0
        self.content_index = 0
        self.submenu_stack = []  # [{'title':..., 'items':[...], 'index':0}]
        self.toast_message = None
        self.toast_ok = True
        self.toast_until = 0.0
        self.reload_requested = True
        self.quit_requested = False


APP = AppState()


def toast(message, ok):
    if message is None:
        return
    APP.toast_message = message
    APP.toast_ok = ok is not False
    APP.toast_until = time.monotonic() + 2.6


def request_reload():
    APP.reload_requested = True


def current_rows():
    if APP.submenu_stack:
        return APP.submenu_stack[-1]["items"]
    if not APP.state:
        return []
    cat_id = CATEGORIES[APP.category_index][0]
    return CATEGORY_ROWS[cat_id](APP.state)


def active_index():
    if APP.submenu_stack:
        return APP.submenu_stack[-1]["index"]
    return APP.content_index


def set_active_index(i):
    rows = current_rows()
    clamped = max(0, min(len(rows) - 1, i)) if rows else 0
    if APP.submenu_stack:
        APP.submenu_stack[-1]["index"] = clamped
    else:
        APP.content_index = clamped


def open_submenu(title, items):
    APP.submenu_stack.append({"title": title, "items": items, "index": 0})


def close_submenu():
    if APP.submenu_stack:
        APP.submenu_stack.pop()


def leave_to_sidebar_or_close_submenu():
    global _tools_confirm_armed
    if APP.submenu_stack:
        close_submenu()
    else:
        APP.focus_zone = "sidebar"
        _tools_confirm_armed = False


def change_category(direction):
    global _tools_confirm_armed
    APP.category_index = (APP.category_index + direction) % len(CATEGORIES)
    APP.content_index = 0
    APP.submenu_stack = []
    _tools_confirm_armed = False
    APP.focus_zone = "content"


def dispatch(action):
    if not APP.state:
        return
    if action == "lb":
        change_category(-1)
        return
    if action == "rb":
        change_category(1)
        return

    if APP.focus_zone == "sidebar" and not APP.submenu_stack:
        if action == "up":
            APP.category_index = (APP.category_index - 1) % len(CATEGORIES)
            APP.content_index = 0
        elif action == "down":
            APP.category_index = (APP.category_index + 1) % len(CATEGORIES)
            APP.content_index = 0
        elif action in ("right", "a"):
            APP.focus_zone = "content"
        return

    rows = current_rows()
    if not rows:
        if action in ("left", "b"):
            leave_to_sidebar_or_close_submenu()
        return
    idx = active_index()
    row = rows[idx]
    if action == "up":
        set_active_index(idx - 1)
    elif action == "down":
        set_active_index(idx + 1)
    elif action == "left":
        if row.on_cycle:
            row.on_cycle(-1)
        elif not APP.submenu_stack:
            APP.focus_zone = "sidebar"
    elif action == "right":
        if row.on_cycle:
            row.on_cycle(1)
    elif action == "a":
        if row.on_activate:
            row.on_activate()
    elif action == "b":
        leave_to_sidebar_or_close_submenu()


# -- Rendering ------------------------------------------------------------
SIDEBAR_WIDTH = 260
TOPBAR_HEIGHT = 70
HINTS_HEIGHT = 44
ROW_HEIGHT = 58
ROW_GAP = 10
ROW_MARGIN_X = 30


def load_fonts():
    path = next((p for p in FONT_PATH_CANDIDATES if Path(p).is_file()), None)
    def f(size):
        return pygame.font.Font(path, size) if path else pygame.font.SysFont("sans", size, bold=True)
    return {
        "title": f(26),
        "cat": f(20),
        "header": f(28),
        "label": f(20),
        "sub": f(15),
        "value": f(18),
        "hint": f(15),
        "toast": f(18),
        "clock": f(20),
        "clock_small": f(13),
    }


def draw_text(screen, font, text, pos, color, anchor="topleft"):
    surf = font.render(text, True, color)
    rect = surf.get_rect(**{anchor: pos})
    screen.blit(surf, rect)
    return rect


def draw_icon(screen, cat_id, rect, color):
    cx, cy = rect.center
    s = rect.width  # ~24
    if cat_id == "leds":
        pygame.draw.circle(screen, color, (cx, cy - s * 0.05), s * 0.32, 2)
        pygame.draw.line(screen, color, (cx - s * 0.18, cy + s * 0.36), (cx + s * 0.18, cy + s * 0.36), 2)
    elif cat_id == "sound":
        pygame.draw.polygon(screen, color, [
            (cx - s * 0.42, cy - s * 0.12), (cx - s * 0.18, cy - s * 0.12),
            (cx + s * 0.12, cy - s * 0.38), (cx + s * 0.12, cy + s * 0.38),
            (cx - s * 0.18, cy + s * 0.12), (cx - s * 0.42, cy + s * 0.12),
        ])
        pygame.draw.arc(screen, color, (cx + s * 0.02, cy - s * 0.3, s * 0.5, s * 0.6), -0.7, 0.7, 2)
    elif cat_id == "games":
        pygame.draw.rect(screen, color, (cx - s * 0.4, cy - s * 0.22, s * 0.8, s * 0.44), 2, border_radius=int(s * 0.2))
        pygame.draw.line(screen, color, (cx - s * 0.22, cy - s * 0.08), (cx - s * 0.22, cy + s * 0.08), 2)
        pygame.draw.line(screen, color, (cx - s * 0.3, cy), (cx - s * 0.14, cy), 2)
        pygame.draw.circle(screen, color, (int(cx + s * 0.18), int(cy - s * 0.05)), 2)
        pygame.draw.circle(screen, color, (int(cx + s * 0.28), int(cy + s * 0.08)), 2)
    elif cat_id == "tags":
        pygame.draw.polygon(screen, color, [
            (cx - s * 0.38, cy), (cx - s * 0.05, cy - s * 0.38), (cx + s * 0.38, cy - s * 0.38),
            (cx + s * 0.38, cy + s * 0.05), (cx + s * 0.05, cy + s * 0.38),
        ], 2)
        pygame.draw.circle(screen, color, (int(cx + s * 0.2), int(cy - s * 0.2)), 2)
    elif cat_id == "tools":
        pygame.draw.circle(screen, color, (int(cx - s * 0.2), int(cy - s * 0.2)), s * 0.16, 2)
        pygame.draw.line(screen, color, (cx - s * 0.08, cy - s * 0.08), (cx + s * 0.3, cy + s * 0.3), 2)
        pygame.draw.rect(screen, color, (cx + s * 0.2, cy + s * 0.2, s * 0.22, s * 0.14), 1, border_radius=2)
    elif cat_id == "info":
        pygame.draw.circle(screen, color, (cx, cy), s * 0.4, 2)
        pygame.draw.line(screen, color, (cx, cy - s * 0.02), (cx, cy + s * 0.28), 2)
        pygame.draw.circle(screen, color, (cx, int(cy - s * 0.22)), 2)


def row_rect(index, area_rect):
    top = area_rect.top + index * (ROW_HEIGHT + ROW_GAP)
    return pygame.Rect(area_rect.left, top, area_rect.width, ROW_HEIGHT)


def draw_row_list(screen, fonts, rows, area, focused_index):
    """Zeichnet rows in area mit Scrolling, falls mehr Zeilen vorhanden
    sind als Platz haben (z. B. die Spieleliste mit 50+ Eintraegen) - haelt
    den fokussierten Index dabei stets sichtbar (mittig, sofern moeglich).
    Gibt [(rect, original_index), ...] nur fuer tatsaechlich gezeichnete
    Zeilen zurueck, fuer Maus-Hit-Testing."""
    visible_count = max(1, (area.height + ROW_GAP) // (ROW_HEIGHT + ROW_GAP))
    max_scroll = max(0, len(rows) - visible_count)
    scroll_start = 0
    if focused_index is not None:
        scroll_start = max(0, min(max_scroll, focused_index - visible_count // 2))

    row_rects = []
    for i in range(scroll_start, min(len(rows), scroll_start + visible_count)):
        rect = row_rect(i - scroll_start, area)
        focused = i == focused_index
        draw_row(screen, fonts, rows[i], rect, focused)
        row_rects.append((rect, i))

    if len(rows) > visible_count:
        track = pygame.Rect(area.right - 4, area.top, 4, area.height)
        pygame.draw.rect(screen, BORDER, track, border_radius=2)
        thumb_h = max(24, area.height * visible_count // len(rows))
        thumb_y = area.top + (area.height - thumb_h) * scroll_start // max(1, max_scroll)
        pygame.draw.rect(screen, CYAN_DIM, (track.left, thumb_y, 4, thumb_h), border_radius=2)

    return row_rects


def draw_row(screen, fonts, row, rect, focused):
    bg = PANEL2 if focused else PANEL
    if row.type == "info":
        draw_text(screen, fonts["sub"], row.label, (rect.left + 6, rect.centery), DIM, anchor="midleft")
        return

    dim = bool(row.badge_fn and row.badge_fn())
    if focused:
        pygame.draw.rect(screen, bg, rect, border_radius=10)
        pygame.draw.rect(screen, CYAN, rect, 2, border_radius=10)
    else:
        pygame.draw.rect(screen, bg, rect, border_radius=10)
        pygame.draw.rect(screen, BORDER, rect, 1, border_radius=10)

    label_color = tuple(int(c * 0.65) for c in TEXT) if dim else TEXT
    x = rect.left + 18
    if row.type == "list-item" and row.color_fn:
        swatch = pygame.Rect(x, rect.centery - 8, 16, 16)
        pygame.draw.rect(screen, row.color_fn(), swatch, border_radius=4)
        x += 26

    label_top = rect.centery - 16 if row.subtext_fn else rect.centery - 11
    draw_text(screen, fonts["label"], row.label, (x, label_top), label_color)
    if row.badge_fn and row.badge_fn():
        badge_text = row.badge_fn().upper()
        bsurf = fonts["sub"].render(badge_text, True, AMBER)
        brect = bsurf.get_rect()
        brect.left = x + fonts["label"].size(row.label)[0] + 10
        brect.centery = label_top + 11
        pygame.draw.rect(screen, (60, 45, 20), brect.inflate(10, 6), border_radius=4)
        screen.blit(bsurf, brect)
    if row.subtext_fn:
        draw_text(screen, fonts["sub"], row.subtext_fn(), (x, rect.centery + 8), DIM)

    value_right = rect.right - 18
    if row.type == "toggle":
        on = row.value_fn()
        text = "An" if on else "Aus"
        color = GREEN if on else DIM
        draw_text(screen, fonts["value"], text, (value_right, rect.centery), color, anchor="midright")
    elif row.type == "color":
        draw_text(screen, fonts["value"], "›", (value_right, rect.centery), DIM, anchor="midright")
        hint_surf = fonts["value"].render(row.hint_fn(), True, DIM)
        hint_rect = hint_surf.get_rect(midright=(value_right - 26, rect.centery))
        screen.blit(hint_surf, hint_rect)
        swatch = pygame.Rect(0, 0, 16, 16)
        swatch.center = (hint_rect.left - 16, rect.centery)
        pygame.draw.rect(screen, row.color_fn(), swatch, border_radius=4)
        draw_text(screen, fonts["value"], "‹", (swatch.left - 14, rect.centery), DIM, anchor="midright")
    elif row.type == "enum":
        draw_text(screen, fonts["value"], "›", (value_right, rect.centery), DIM, anchor="midright")
        hint_surf = fonts["value"].render(row.hint_fn(), True, DIM)
        hint_rect = hint_surf.get_rect(midright=(value_right - 22, rect.centery))
        screen.blit(hint_surf, hint_rect)
        draw_text(screen, fonts["value"], "‹", (hint_rect.left - 8, rect.centery), DIM, anchor="midright")
    elif row.type == "stat":
        draw_text(screen, fonts["value"], row.hint_fn(), (value_right, rect.centery), CYAN_DIM, anchor="midright")
    elif row.type in ("button", "list-item"):
        draw_text(screen, fonts["value"], "›", (value_right, rect.centery), DIM, anchor="midright")


def render_submenu(screen, fonts, size):
    if not APP.submenu_stack:
        return
    top = APP.submenu_stack[-1]
    if top["index"] >= len(top["items"]):
        top["index"] = max(0, len(top["items"]) - 1)

    overlay = pygame.Surface(size, pygame.SRCALPHA)
    overlay.fill((4, 6, 10, 200))
    screen.blit(overlay, (0, 0))

    card_w = min(560, size[0] - 80)
    n = len(top["items"])
    card_h = min(size[1] - 100, 70 + n * (ROW_HEIGHT + ROW_GAP))
    card = pygame.Rect(0, 0, card_w, card_h)
    card.center = (size[0] // 2, size[1] // 2)
    pygame.draw.rect(screen, PANEL2, card, border_radius=14)
    pygame.draw.rect(screen, BORDER, card, 1, border_radius=14)

    draw_text(screen, fonts["cat"], top["title"], (card.left + 20, card.top + 18), CYAN)
    area = pygame.Rect(card.left + 16, card.top + 56, card.width - 32, card.height - 72)
    return draw_row_list(screen, fonts, top["items"], area, top["index"])


def render_frame(screen, fonts, size):
    w, h = size
    screen.fill(BG)

    # Topbar
    pygame.draw.line(screen, BORDER, (0, TOPBAR_HEIGHT), (w, TOPBAR_HEIGHT), 1)
    pygame.draw.rect(screen, CYAN, (24, 22, 4, 26))
    draw_text(screen, fonts["title"], "STEAMOS", (40, TOPBAR_HEIGHT // 2), CYAN_DIM, anchor="midleft")
    steam_w = fonts["title"].size("STEAMOS ")[0]
    draw_text(screen, fonts["title"], "KONSOLE", (40 + steam_w, TOPBAR_HEIGHT // 2), TEXT, anchor="midleft")

    state = APP.state
    right = w - 30
    if state:
        clock_surf_time = time.strftime("%H:%M")
        clock_surf_date = time.strftime("%a %d.%m")
        t_rect = draw_text(screen, fonts["clock"], clock_surf_time, (right, TOPBAR_HEIGHT // 2 - 8), TEXT, anchor="midright")
        draw_text(screen, fonts["clock_small"], clock_surf_date, (right, TOPBAR_HEIGHT // 2 + 12), DIM, anchor="midright")
        right = t_rect.left - 24

        if state.get("download_active") and state.get("download_progress") is not None:
            pct = max(0.0, min(1.0, state["download_progress"]))
            label = f"{state.get('download_name') or 'Download'} · {round(pct * 100)}%"
            label_surf = fonts["sub"].render(label, True, DIM)
            track_w = 180
            track = pygame.Rect(0, 0, track_w, 6)
            track.midright = (right, TOPBAR_HEIGHT // 2)
            fill = pygame.Rect(track.left, track.top, int(track_w * pct), 6)
            pygame.draw.rect(screen, (255, 255, 255, 20), track, border_radius=3)
            pygame.draw.rect(screen, CYAN_DIM, fill, border_radius=3)
            label_rect = label_surf.get_rect(midright=(track.left - 12, TOPBAR_HEIGHT // 2))
            screen.blit(label_surf, label_rect)

    # Sidebar
    sidebar = pygame.Rect(0, TOPBAR_HEIGHT, SIDEBAR_WIDTH, h - TOPBAR_HEIGHT - HINTS_HEIGHT)
    pygame.draw.line(screen, BORDER, (SIDEBAR_WIDTH, TOPBAR_HEIGHT), (SIDEBAR_WIDTH, h - HINTS_HEIGHT), 1)

    cat_rects = []
    for i, (cat_id, label) in enumerate(CATEGORIES):
        rect = pygame.Rect(sidebar.left, sidebar.top + i * 52, sidebar.width, 52)
        cat_rects.append(rect)
        is_current = i == APP.category_index
        is_focused = is_current and APP.focus_zone == "sidebar" and not APP.submenu_stack
        if is_current:
            pygame.draw.rect(screen, PANEL, rect)
        if is_focused:
            pygame.draw.rect(screen, CYAN, (rect.left, rect.top, 3, rect.height))
        color = CYAN if is_focused else (TEXT if is_current else DIM)
        icon_rect = pygame.Rect(0, 0, 22, 22)
        icon_rect.midleft = (rect.left + 22, rect.centery)
        draw_icon(screen, cat_id, icon_rect, color)
        draw_text(screen, fonts["cat"], label, (rect.left + 46, rect.centery), color, anchor="midleft")

    # Content
    content = pygame.Rect(SIDEBAR_WIDTH + ROW_MARGIN_X, TOPBAR_HEIGHT + 24,
                           w - SIDEBAR_WIDTH - ROW_MARGIN_X * 2, h - TOPBAR_HEIGHT - HINTS_HEIGHT - 40)
    cat_id, cat_label = CATEGORIES[APP.category_index]
    header_icon = pygame.Rect(0, 0, 26, 26)
    header_icon.topleft = (content.left, content.top)
    draw_icon(screen, cat_id, header_icon, CYAN)
    draw_text(screen, fonts["header"], cat_label, (content.left + 40, content.top - 4), TEXT)
    pygame.draw.line(screen, BORDER, (content.left, content.top + 42), (content.right, content.top + 42), 1)

    row_area = pygame.Rect(content.left, content.top + 58, content.width, content.height - 58)
    row_rects = []
    if state:
        rows = CATEGORY_ROWS[cat_id](state)
        if APP.content_index >= len(rows):
            APP.content_index = max(0, len(rows) - 1)
        focus_idx = APP.content_index if (not APP.submenu_stack and APP.focus_zone == "content") else None
        row_rects = draw_row_list(screen, fonts, rows, row_area, focus_idx)
    else:
        draw_text(screen, fonts["sub"], "Lade…", (row_area.left, row_area.top), DIM)

    submenu_row_rects = render_submenu(screen, fonts, size)
    if submenu_row_rects is not None:
        row_rects = submenu_row_rects

    # Hints
    pygame.draw.line(screen, BORDER, (0, h - HINTS_HEIGHT), (w, h - HINTS_HEIGHT), 1)
    if APP.submenu_stack:
        hint = "↑↓ Navigieren · A Wählen · B Zurück"
    elif APP.focus_zone == "sidebar":
        hint = "↑↓ Kategorie · → / A Öffnen · LB/RB Kategorie wechseln"
    else:
        hint = "↑↓ Navigieren · ←→ Wert ändern · A Auswählen/Umschalten · B Zurück · LB/RB Kategorie · B halten = Beenden"
    draw_text(screen, fonts["hint"], hint, (w // 2, h - HINTS_HEIGHT // 2), DIM, anchor="center")

    # Toast
    if APP.toast_message and time.monotonic() < APP.toast_until:
        surf = fonts["toast"].render(APP.toast_message, True, RED if not APP.toast_ok else TEXT)
        box = surf.get_rect()
        box.center = (w // 2, h - HINTS_HEIGHT - 50)
        bg_box = box.inflate(40, 24)
        pygame.draw.rect(screen, PANEL2, bg_box, border_radius=10)
        pygame.draw.rect(screen, RED if not APP.toast_ok else BORDER, bg_box, 1, border_radius=10)
        screen.blit(surf, box)

    return cat_rects, row_rects


def handle_mouse_click(pos, cat_rects, row_rects):
    """Maus-Faellback (funktioniert unabhaengig vom Controller-Thema) -
    Klick auf eine Sidebar-Kategorie wechselt/oeffnet sie, Klick auf eine
    Zeile aktiviert sie bzw. zykelt Farb-/Enum-Werte, je nachdem ob links
    oder rechts der Mitte geklickt wurde (Pendant zu den <>-Schaltflaechen
    in dashboard.html)."""
    if APP.submenu_stack:
        top = APP.submenu_stack[-1]
        for rect, i in row_rects:
            if rect.collidepoint(pos):
                top["index"] = i
                _activate_or_cycle(top["items"][i], rect, pos)
                return
        return

    for i, rect in enumerate(cat_rects):
        if rect.collidepoint(pos):
            if i == APP.category_index:
                APP.focus_zone = "content"
            else:
                change_category_to(i)
            return

    rows = current_rows()
    for rect, i in row_rects:
        if rect.collidepoint(pos):
            APP.focus_zone = "content"
            APP.content_index = i
            _activate_or_cycle(rows[i], rect, pos)
            return


def _activate_or_cycle(row, rect, pos):
    if row.on_cycle and not row.on_activate:
        row.on_cycle(-1 if pos[0] < rect.centerx else 1)
    elif row.on_activate:
        row.on_activate()


def change_category_to(index):
    global _tools_confirm_armed
    APP.category_index = index
    APP.content_index = 0
    APP.submenu_stack = []
    _tools_confirm_armed = False
    APP.focus_zone = "content"


# -- Eingabe: Tastatur + Maus + Controller -------------------------------
KEY_ACTIONS = {
    pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
    pygame.K_RETURN: "a", pygame.K_SPACE: "a",
    pygame.K_ESCAPE: "b", pygame.K_BACKSPACE: "b",
    pygame.K_q: "lb", pygame.K_e: "rb",
}

GP_DEADZONE = 0.5
GP_REPEAT_DELAY = 0.3
GP_REPEAT_RATE = 0.13


class GamepadRepeat:
    def __init__(self):
        self.last_dir = None
        self.last_move_time = 0.0
        self.first_repeat_done = False

    def poll(self, controller, now):
        direction = self._direction(controller)
        if direction:
            is_new = direction != self.last_dir
            threshold = 0 if is_new else (GP_REPEAT_RATE if self.first_repeat_done else GP_REPEAT_DELAY)
            if is_new or now - self.last_move_time >= threshold:
                dispatch(direction)
                self.last_move_time = now
                self.first_repeat_done = not is_new
            self.last_dir = direction
        else:
            self.last_dir = None
            self.first_repeat_done = False

    def _direction(self, controller):
        try:
            if controller.get_button(pygame.CONTROLLER_BUTTON_DPAD_LEFT):
                return "left"
            if controller.get_button(pygame.CONTROLLER_BUTTON_DPAD_RIGHT):
                return "right"
            if controller.get_button(pygame.CONTROLLER_BUTTON_DPAD_UP):
                return "up"
            if controller.get_button(pygame.CONTROLLER_BUTTON_DPAD_DOWN):
                return "down"
            ax = controller.get_axis(pygame.CONTROLLER_AXIS_LEFTX) / 32768.0
            ay = controller.get_axis(pygame.CONTROLLER_AXIS_LEFTY) / 32768.0
            if ax < -GP_DEADZONE:
                return "left"
            if ax > GP_DEADZONE:
                return "right"
            if ay < -GP_DEADZONE:
                return "up"
            if ay > GP_DEADZONE:
                return "down"
        except pygame.error:
            return None
        return None


BUTTON_ACTIONS = {
    pygame.CONTROLLER_BUTTON_A: "a",
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "lb",
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "rb",
}


def open_first_controller():
    try:
        sdl2_controller.init()
    except pygame.error:
        return None
    for i in range(sdl2_controller.get_count()):
        if sdl2_controller.is_controller(i):
            try:
                c = sdl2_controller.Controller(i)
                print(f"Controller erkannt: {c.name}", flush=True)
                return c
            except pygame.error:
                continue
    return None


def main():
    print(f"Warte auf gui_server.py unter {BASE_URL} ...", flush=True)
    if not wait_for_server():
        print(f"gui_server.py unter {BASE_URL} nicht erreichbar - laeuft steamos-gui.service?", file=sys.stderr)
        sys.exit(1)

    pygame.init()
    pygame.mouse.set_visible(True)
    # Bewusst kein echtes exklusives pygame.FULLSCREEN: SDL2s Wayland-
    # Backend (SteamOS/Bazzite) zeigt damit in der Praxis nur ein
    # schwarzes, nie aktualisiertes Fenster (bekannte SDL2/Wayland-
    # Einschraenkung bei echtem Modesetting-Vollbild). Ein randloses
    # Fenster in Bildschirmgroesse ("Fullscreen Desktop"-Idiom) ist unter
    # Wayland-Compositors zuverlaessiger.
    info = pygame.display.Info()
    screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.NOFRAME)
    pygame.display.set_caption("SteamOS Konsole")
    fonts = load_fonts()
    clock = pygame.time.Clock()

    # Direkt nach dem Verbinden (Start oder Hotplug) liefern manche
    # Controller kurzzeitig verrauschte/falsche Achsen-/Tasten-Werte,
    # bevor sich die Hardware auf den echten Ruhezustand einpendelt (in der
    # Praxis beobachtet: mehrere phantomhafte "runter"-Bewegungen direkt
    # beim Start, die das Menue ungewollt mehrere Kategorien nach unten
    # springen liessen). controller_ready_at sperrt Achsen-/D-Pad-Polling
    # sowie Tasten-Events fuer eine kurze Anlaufzeit nach jedem (Neu-)Verbinden.
    CONTROLLER_SETTLE_SECONDS = 0.6
    controller = open_first_controller()
    gp_repeat = GamepadRepeat()
    controller_ready_at = time.monotonic() + CONTROLLER_SETTLE_SECONDS if controller else 0.0
    back_held_since = None

    APP.state = fetch_state()
    APP.reload_requested = False
    last_poll = time.monotonic()

    while not APP.quit_requested:
        now = time.monotonic()
        size = screen.get_size()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                APP.quit_requested = True
            elif event.type == pygame.CONTROLLERDEVICEADDED and controller is None:
                controller = open_first_controller()
                gp_repeat = GamepadRepeat()
                controller_ready_at = now + CONTROLLER_SETTLE_SECONDS
            elif event.type == pygame.CONTROLLERDEVICEREMOVED:
                controller = None
            elif event.type == pygame.KEYDOWN:
                if event.key in KEY_ACTIONS:
                    dispatch(KEY_ACTIONS[event.key])
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                cat_rects, row_rects = render_frame(screen, fonts, size)
                handle_mouse_click(event.pos, cat_rects, row_rects)
            elif event.type == pygame.CONTROLLERBUTTONDOWN and now >= controller_ready_at:
                if event.button in BUTTON_ACTIONS:
                    dispatch(BUTTON_ACTIONS[event.button])
                elif event.button == pygame.CONTROLLER_BUTTON_B:
                    dispatch("b")
                elif event.button == pygame.CONTROLLER_BUTTON_BACK:
                    back_held_since = now
            elif event.type == pygame.CONTROLLERBUTTONUP:
                if event.button == pygame.CONTROLLER_BUTTON_BACK:
                    back_held_since = None

        if back_held_since is not None and now - back_held_since >= 1.0:
            APP.quit_requested = True

        if controller is not None and now >= controller_ready_at:
            gp_repeat.poll(controller, now)

        if now - last_poll >= 5.0 or APP.reload_requested:
            APP.state = fetch_state()
            APP.reload_requested = False
            last_poll = now

        render_frame(screen, fonts, size)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()


if __name__ == "__main__":
    main()
