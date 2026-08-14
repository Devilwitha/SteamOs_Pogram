"""
Cover Maker - fuegt 4 Bilder zu einem Cover zusammen (Front, Seite, Rueckseite, Seite).

Start: python cover_maker.py
Benoetigt: Pillow (pip install pillow)
"""

import filecmp
import json
import sqlite3
import subprocess
import sys
import time
import uuid
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageDraw, ImageTk, ImageOps

import cover_render
from cover_render import (
    MODE_CROP,
    MODE_STRETCH,
    MODE_CONTAIN,
    FIT_MODES,
    DEFAULT_REQUIREMENTS_TEXT,
    DEFAULT_MIN_TITLE,
    DEFAULT_REC_TITLE,
    RATING_OPTIONS,
    RATING_COLORS,
    CONSOLE_OPTIONS,
    cm_to_px,
    load_font,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "covers.db"
ASSIGN_SCRIPT = SCRIPT_DIR / "assign_game.py"

# Masse bleiben wie urspruenglich angefragt: Front/Rueckseite 6cm breit,
# beide Seiten 1cm breit, gemeinsame Hoehe 10cm (in der GUI einstellbar).
# Reihenfolge: Seite 1 | Front | Seite 2 | Rueckseite, damit das Banner
# ueber Seite1+Front+Seite2 durchgehend bleibt (Rueckseite liegt am Ende,
# nicht mehr in der Mitte -> kein abgetrenntes Banner-Fragment mehr).
PANEL_DEFAULTS = [
    {"name": "Seite 1", "width_cm": 1.0},
    {"name": "Front", "width_cm": 6.0},
    {"name": "Seite 2", "width_cm": 1.0},
    {"name": "Rueckseite", "width_cm": 6.0},
]
FRONT_PANEL_INDEX = 1
BACK_PANEL_INDEX = 3  # "Rueckseite" ist standardmaessig im Rueckseiten-Modus
WRAP_FRONT_DEFAULT_INDEX = 2  # "Seite 2" zeigt standardmaessig die Fortsetzung des Frontbilds

PREVIEW_MAX_W = 900
PREVIEW_MAX_H = 400

BANNER_TEMPLATES_DIR = SCRIPT_DIR / "banner_templates"

# Einheitliches Dark-/HUD-("Game-Style")-Design, uebernommen aus den
# HTML-Oberflaechen des Projekts (steamOs/gui/index.html, Pico/*.html):
# dieselben Hex-Werte wie dort in den CSS-Variablen --bg/--panel/--cyan/
# --magenta/... sowie dieselbe Sprache (dunkler Grund, Cyan als Primaer-,
# Magenta als Sekundaer-/Abbrechen-Akzent, GROSSGESCHRIEBENE HUD-Titel,
# feines Raster im Hintergrund), damit Desktop-Tool und Web-GUI optisch
# einheitlich wirken.
THEME = {
    "bg": "#080b10",
    "panel": "#11151d",
    "panel2": "#161c27",
    "border": "#232c3d",
    "input_bg": "#0c1017",
    "cyan": "#00e5ff",
    "cyan_dim": "#0891a8",
    "magenta": "#ff2e97",
    "magenta_dim": "#a8125f",
    "green": "#39ff8c",
    "amber": "#ffb238",
    "red": "#ff4d6d",
    "text": "#e8edf5",
    "dim": "#7686a0",
    "on_cyan": "#04141a",
    "grid_line": "#161c27",
}
FONT_BASE = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_HUD = ("Segoe UI", 8, "bold")


def apply_theme(root):
    """Faerbt die gesamte Tk/ttk-Oberflaeche im selben Dark-/HUD-Stil wie
    die HTML-Seiten des Projekts (dunkler Grund, Cyan als Primaer-, Magenta
    als Sekundaer-/Abbrechen-Akzent)."""
    t = THEME
    root.configure(bg=t["panel"])

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=t["panel"], foreground=t["text"],
                     fieldbackground=t["input_bg"], bordercolor=t["border"],
                     darkcolor=t["panel"], lightcolor=t["panel2"],
                     troughcolor=t["panel2"], font=FONT_BASE)

    style.configure("TFrame", background=t["panel"])
    style.configure("TLabel", background=t["panel"], foreground=t["text"])
    style.configure("Dim.TLabel", background=t["panel"], foreground=t["dim"])
    style.configure("Hud.TLabel", background=t["panel"], foreground=t["cyan_dim"], font=FONT_HUD)
    style.configure("Field.TLabel", background=t["panel"], foreground=t["dim"], font=FONT_HUD)

    style.configure("TLabelframe", background=t["panel"], bordercolor=t["border"],
                     relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=t["panel"], foreground=t["cyan"], font=FONT_BOLD)

    style.configure("TSeparator", background=t["border"])

    style.configure("TCheckbutton", background=t["panel"], foreground=t["text"], focuscolor=t["panel"])
    style.map("TCheckbutton",
              background=[("active", t["panel"])],
              foreground=[("disabled", t["dim"])])

    style.configure("TEntry", fieldbackground=t["input_bg"], foreground=t["text"],
                     bordercolor=t["border"], insertcolor=t["cyan"], padding=4)
    style.map("TEntry", bordercolor=[("focus", t["cyan"])])

    style.configure("TCombobox", fieldbackground=t["input_bg"], background=t["input_bg"],
                     foreground=t["text"], arrowcolor=t["cyan"], bordercolor=t["border"], padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", t["input_bg"])],
              foreground=[("readonly", t["text"])],
              bordercolor=[("focus", t["cyan"])])
    root.option_add("*TCombobox*Listbox.background", t["input_bg"])
    root.option_add("*TCombobox*Listbox.foreground", t["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", t["cyan_dim"])
    root.option_add("*TCombobox*Listbox.selectForeground", t["on_cyan"])

    # Primaerknopf: Cyan, GROSSGESCHRIEBEN und fett - analog zu <button> in
    # den HTML-Seiten (dort per text-transform:uppercase/font-weight:700).
    style.configure("TButton", background=t["cyan_dim"], foreground=t["on_cyan"],
                     bordercolor=t["cyan"], focuscolor=t["panel"], font=FONT_BOLD,
                     padding=(10, 6), relief="flat")
    style.map("TButton",
              background=[("active", t["cyan"]), ("disabled", t["border"])],
              foreground=[("disabled", t["dim"])])

    # Sekundaer-/Abbrechen-/Loeschen-Knopf: Magenta, analog zu button.secondary.
    style.configure("Secondary.TButton", background=t["magenta_dim"], foreground=t["text"],
                     bordercolor=t["magenta"], focuscolor=t["panel"], font=FONT_BOLD,
                     padding=(10, 6), relief="flat")
    style.map("Secondary.TButton",
              background=[("active", t["magenta"]), ("disabled", t["border"])],
              foreground=[("disabled", t["dim"])])

    return style


def draw_hud_grid(canvas, width=None, height=None):
    """Zeichnet ein feines Punkt-/Linienraster auf einen Canvas-Hintergrund,
    als Anlehnung an das repeating-linear-gradient-Rasterpattern hinter dem
    body-Element der HTML-Seiten. Rein dekorativ, liegt hinter allen anderen
    Canvas-Inhalten."""
    step = 26
    w = width if width is not None else canvas.winfo_width()
    h = height if height is not None else canvas.winfo_height()
    if w <= 1 or h <= 1:
        return
    canvas.delete("hud_grid")
    for x in range(0, w, step):
        canvas.create_line(x, 0, x, h, fill=THEME["grid_line"], tags="hud_grid")
    for y in range(0, h, step):
        canvas.create_line(0, y, w, y, fill=THEME["grid_line"], tags="hud_grid")
    canvas.tag_lower("hud_grid")


def _localize_asset(src_path, dest_dir: Path):
    """Kopiert eine referenzierte Datei (Panel-/Banner-/Logo-Bild) nach
    dest_dir, falls sie nicht schon dort liegt, und gibt den neuen,
    lokalen Pfad zurueck. Bei einem Namenskonflikt mit einer anderen
    (inhaltlich abweichenden) Datei wird ein Zaehler an den Dateinamen
    angehaengt. Fehlt die Quelldatei, wird der urspruengliche Pfad
    unveraendert zurueckgegeben (bestehende Fehlerbehandlung beim
    Projekt-Laden faengt das dann als "fehlende Datei" ab)."""
    if not src_path:
        return src_path
    src = Path(src_path)
    if not src.is_file():
        return src_path

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        if src.resolve().parent == dest_dir.resolve():
            return str(src.resolve())
    except OSError:
        pass

    dest = dest_dir / src.name
    if dest.exists() and not filecmp.cmp(src, dest, shallow=False):
        i = 2
        while True:
            candidate = dest_dir / f"{src.stem}_{i}{src.suffix}"
            if not candidate.exists() or filecmp.cmp(src, candidate, shallow=False):
                dest = candidate
                break
            i += 1

    if not dest.exists():
        shutil.copyfile(src, dest)
    return str(dest.resolve())


def ensure_covers_db(conn):
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
    # Migration fuer aeltere covers.db-Dateien: theme_name/author_name kamen
    # erst mit dem Web-Store/Admin-Tool dazu (siehe tools/cover_maker/server).
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(covers)")}
    for col in ("theme_name", "author_name"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE covers ADD COLUMN {col} TEXT")
    conn.commit()


class BackCoverDialog(tk.Toplevel):
    """Bearbeitet Bildanteil, Minimum-/Empfohlen-Text und Firmenlogos einer Rueckseite."""

    def __init__(self, parent, panel, app):
        super().__init__(parent)
        self.configure(bg=THEME["panel"])
        self.panel = panel
        self.app = app
        self.title(f"Rueckseiten-Inhalt - {panel.name()}")
        self.geometry("600x760")
        self.transient(parent)

        ratio_row = ttk.Frame(self)
        ratio_row.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(ratio_row, text="BILDANTEIL OBEN (%):", style="Field.TLabel").pack(side="left")
        self.ratio_var = tk.StringVar(value=str(panel.art_ratio_percent))
        ttk.Entry(ratio_row, textvariable=self.ratio_var, width=6).pack(side="left", padx=5)
        ttk.Label(ratio_row, text="(Rest = Anforderungen + Kompatibilitaet + Logos)", style="Dim.TLabel").pack(side="left")

        text_row = ttk.Frame(self)
        text_row.pack(fill="both", expand=True, padx=10, pady=4)
        text_row.columnconfigure(0, weight=1)
        text_row.columnconfigure(1, weight=1)
        text_row.rowconfigure(0, weight=1)

        min_col = ttk.LabelFrame(text_row, text="MINIMUM-SPALTE")
        min_col.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        min_title_row = ttk.Frame(min_col)
        min_title_row.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(min_title_row, text="TITEL:", style="Field.TLabel").pack(side="left")
        self.min_title_var = tk.StringVar(value=panel.min_title)
        ttk.Entry(min_title_row, textvariable=self.min_title_var).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.min_text = tk.Text(
            min_col, width=28, height=8, bg=THEME["input_bg"], fg=THEME["text"],
            insertbackground=THEME["cyan"], selectbackground=THEME["cyan_dim"],
            selectforeground=THEME["on_cyan"], relief="flat",
            highlightthickness=1, highlightbackground=THEME["border"], highlightcolor=THEME["cyan"],
        )
        self.min_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.min_text.insert("1.0", panel.min_text_content)

        rec_col = ttk.LabelFrame(text_row, text="EMPFOHLEN-SPALTE")
        rec_col.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        rec_title_row = ttk.Frame(rec_col)
        rec_title_row.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(rec_title_row, text="TITEL:", style="Field.TLabel").pack(side="left")
        self.rec_title_var = tk.StringVar(value=panel.rec_title)
        ttk.Entry(rec_title_row, textvariable=self.rec_title_var).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.rec_text = tk.Text(
            rec_col, width=28, height=8, bg=THEME["input_bg"], fg=THEME["text"],
            insertbackground=THEME["cyan"], selectbackground=THEME["cyan_dim"],
            selectforeground=THEME["on_cyan"], relief="flat",
            highlightthickness=1, highlightbackground=THEME["border"], highlightcolor=THEME["cyan"],
        )
        self.rec_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.rec_text.insert("1.0", panel.rec_text_content)

        compat_frame = ttk.LabelFrame(self, text="STEAM-KOMPATIBILITAET & EINGABEGERAETE")
        compat_frame.pack(fill="x", padx=10, pady=(4, 4))

        self.show_compat_var = tk.BooleanVar(value=panel.show_compat)
        ttk.Checkbutton(
            compat_frame, text="Auf dem Cover anzeigen", variable=self.show_compat_var
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=(4, 2))

        ttk.Label(compat_frame, text="STEAM DECK:", style="Field.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.steamdeck_var = tk.StringVar(value=panel.steamdeck_rating)
        ttk.Combobox(
            compat_frame, textvariable=self.steamdeck_var, values=RATING_OPTIONS, state="readonly", width=18
        ).grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(compat_frame, text="STEAM MACHINE:", style="Field.TLabel").grid(row=1, column=2, sticky="w", padx=4, pady=2)
        self.steammachine_var = tk.StringVar(value=panel.steammachine_rating)
        ttk.Combobox(
            compat_frame, textvariable=self.steammachine_var, values=RATING_OPTIONS, state="readonly", width=18
        ).grid(row=1, column=3, sticky="w", padx=4, pady=2)

        self.input_kbm_var = tk.BooleanVar(value=panel.input_kbm)
        ttk.Checkbutton(compat_frame, text="Maus & Tastatur noetig/empfohlen", variable=self.input_kbm_var).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 4)
        )
        self.input_controller_var = tk.BooleanVar(value=panel.input_controller)
        ttk.Checkbutton(compat_frame, text="Controller noetig/empfohlen", variable=self.input_controller_var).grid(
            row=2, column=2, columnspan=2, sticky="w", padx=4, pady=(2, 4)
        )

        logos_frame = ttk.LabelFrame(self, text="FIRMENLOGOS (werden unten in einer Reihe angezeigt)")
        logos_frame.pack(fill="x", padx=10, pady=(4, 10))
        self.logos_list = tk.Listbox(
            logos_frame, height=4, bg=THEME["input_bg"], fg=THEME["text"],
            selectbackground=THEME["cyan_dim"], selectforeground=THEME["on_cyan"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"],
        )
        self.logos_list.pack(side="left", fill="both", expand=True, padx=(4, 4), pady=4)
        for logo_path in panel.logo_paths:
            self.logos_list.insert("end", Path(logo_path).name)

        logos_btns = ttk.Frame(logos_frame)
        logos_btns.pack(side="left", padx=(0, 4), pady=4)
        ttk.Button(logos_btns, text="HINZUFUEGEN...", command=self.add_logos).pack(fill="x", pady=2)
        ttk.Button(logos_btns, text="ENTFERNEN", style="Secondary.TButton", command=self.remove_selected_logo).pack(fill="x", pady=2)
        ttk.Button(logos_btns, text="ALLE LOESCHEN", style="Secondary.TButton", command=self.clear_logos).pack(fill="x", pady=2)

        self._logos = list(zip(panel.logo_paths, panel.logos))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="UEBERNEHMEN", command=self.apply).pack(side="right")
        ttk.Button(btn_row, text="ABBRECHEN", style="Secondary.TButton", command=self.destroy).pack(side="right", padx=10)

    def add_logos(self):
        paths = filedialog.askopenfilenames(
            title="Logos waehlen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Alle Dateien", "*.*")],
        )
        for p in paths:
            try:
                img = Image.open(p)
                img.load()
            except Exception as exc:
                messagebox.showerror("Fehler", f"Logo konnte nicht geladen werden:\n{exc}")
                continue
            self._logos.append((p, img))
            self.logos_list.insert("end", Path(p).name)

    def remove_selected_logo(self):
        sel = self.logos_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.logos_list.delete(idx)
        del self._logos[idx]

    def clear_logos(self):
        self.logos_list.delete(0, "end")
        self._logos = []

    def apply(self):
        try:
            ratio = max(1.0, min(99.0, float(self.ratio_var.get().replace(",", "."))))
        except ValueError:
            ratio = 50.0

        self.panel.art_ratio_percent = ratio
        self.panel.min_title = self.min_title_var.get().strip() or DEFAULT_MIN_TITLE
        self.panel.rec_title = self.rec_title_var.get().strip() or DEFAULT_REC_TITLE
        self.panel.min_text_content = self.min_text.get("1.0", "end-1c")
        self.panel.rec_text_content = self.rec_text.get("1.0", "end-1c")
        self.panel.show_compat = self.show_compat_var.get()
        self.panel.steamdeck_rating = self.steamdeck_var.get()
        self.panel.steammachine_rating = self.steammachine_var.get()
        self.panel.input_kbm = self.input_kbm_var.get()
        self.panel.input_controller = self.input_controller_var.get()
        self.panel.logo_paths = [p for p, _ in self._logos]
        self.panel.logos = [img for _, img in self._logos]
        self.destroy()
        self.app.update_preview()


class Panel:
    THUMB_MAX = 130

    def __init__(self, parent, index, app):
        self.index = index
        self.app = app
        self.image_path = None
        self.pil_image = None
        self.center_x = 0.5
        self.center_y = 0.5
        self._drag_start = None
        self._thumb_w = self.THUMB_MAX
        self._thumb_h = self.THUMB_MAX
        self._thumb_art_h = self.THUMB_MAX
        self._thumb_photo = None

        # Rueckseiten-Modus: oben Artwork, unten Systemanforderungen + Logos.
        self.art_ratio_percent = 50.0
        self.min_title = DEFAULT_MIN_TITLE
        self.rec_title = DEFAULT_REC_TITLE
        self.min_text_content = DEFAULT_REQUIREMENTS_TEXT
        self.rec_text_content = DEFAULT_REQUIREMENTS_TEXT
        self.logo_paths = []
        self.logos = []
        self.show_compat = True
        self.steamdeck_rating = RATING_OPTIONS[0]
        self.steammachine_rating = RATING_OPTIONS[0]
        self.input_kbm = False
        self.input_controller = False

        # Merkt sich unabhaengig von der aktuellen Sortierung, welches Panel
        # das "Front"-Bild liefert (fuer den Wrap-Effekt auf Nachbarpanels).
        self.is_front = (index == FRONT_PANEL_INDEX)

        self.frame = ttk.LabelFrame(parent, text=PANEL_DEFAULTS[index]["name"])
        self.frame.grid(row=0, column=index, padx=5, pady=5, sticky="nsew")

        self.drag_handle = ttk.Label(
            self.frame, text="☰ ZIEHEN ZUM SORTIEREN", style="Dim.TLabel", cursor="fleur", anchor="center"
        )
        self.drag_handle.grid(row=0, column=0, columnspan=2, pady=(2, 4), sticky="ew")
        self.drag_handle.bind("<ButtonPress-1>", self._on_drag_handle_press)
        self.drag_handle.bind("<ButtonRelease-1>", self._on_drag_handle_release)

        self.name_var = tk.StringVar(value=PANEL_DEFAULTS[index]["name"])
        ttk.Entry(self.frame, textvariable=self.name_var, width=14).grid(
            row=1, column=0, columnspan=2, pady=2
        )
        self.name_var.trace_add("write", lambda *_: self._on_name_change())

        self.path_label = ttk.Label(self.frame, text="kein Bild", width=20, anchor="w")
        self.path_label.grid(row=2, column=0, columnspan=2, pady=2)

        ttk.Button(self.frame, text="BILD WAEHLEN", command=self.choose_image).grid(
            row=3, column=0, columnspan=2, pady=2
        )

        width_row = ttk.Frame(self.frame)
        width_row.grid(row=4, column=0, columnspan=2, pady=2)
        ttk.Label(width_row, text="BREITE (CM):", style="Field.TLabel").pack(side="left")
        self.width_var = tk.StringVar(value=str(PANEL_DEFAULTS[index]["width_cm"]))
        ttk.Entry(width_row, textvariable=self.width_var, width=6).pack(side="left")
        self.width_var.trace_add("write", lambda *_: self.app.update_preview())

        ttk.Label(self.frame, text="MODUS:", style="Field.TLabel").grid(row=5, column=0, columnspan=2)
        self.mode_var = tk.StringVar(value=FIT_MODES[0])
        mode_combo = ttk.Combobox(
            self.frame, textvariable=self.mode_var, values=FIT_MODES, state="readonly", width=22
        )
        mode_combo.grid(row=6, column=0, columnspan=2, pady=2)
        mode_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_mode_change())

        self.canvas = tk.Canvas(
            self.frame, width=self.THUMB_MAX, height=self.THUMB_MAX, bg=THEME["input_bg"],
            highlightthickness=1, highlightbackground=THEME["border"], highlightcolor=THEME["cyan"],
            cursor="fleur",
        )
        self.canvas.grid(row=7, column=0, columnspan=2, pady=4)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)

        self.hint_label = ttk.Label(self.frame, text="", style="Dim.TLabel", wraplength=120, justify="center")
        self.hint_label.grid(row=8, column=0, columnspan=2)
        self._update_hint()

        self.back_mode_var = tk.BooleanVar(value=(index == BACK_PANEL_INDEX))
        ttk.Checkbutton(
            self.frame, text="Ist Rueckseite", variable=self.back_mode_var, command=self._on_back_mode_change
        ).grid(row=9, column=0, columnspan=2, pady=(6, 0))

        self.back_edit_btn = ttk.Button(
            self.frame,
            text="RUECKSEITEN-INHALT...",
            command=self.open_back_dialog,
            state=("normal" if self.back_mode_var.get() else "disabled"),
        )
        self.back_edit_btn.grid(row=10, column=0, columnspan=2, pady=(2, 4))

        self.wrap_front_var = tk.BooleanVar(value=(index == WRAP_FRONT_DEFAULT_INDEX))
        if not self.is_front:
            ttk.Checkbutton(
                self.frame,
                text="Frontbild fortsetzen (Wrap)",
                variable=self.wrap_front_var,
                command=self.app.update_preview,
            ).grid(row=11, column=0, columnspan=2, pady=(0, 4))

    def _on_name_change(self):
        self.frame.configure(text=self.name_var.get() or f"Panel {self.index + 1}")
        self.app.update_preview()

    def _on_mode_change(self):
        self._update_hint()
        self.app.update_preview()

    def _on_drag_handle_press(self, _event):
        self.app.drag_panel = self

    def _on_drag_handle_release(self, event):
        dragged = self.app.drag_panel
        self.app.drag_panel = None
        if dragged is None:
            return
        target_index = self.app.panel_index_at_x(event.x_root)
        if target_index is not None:
            self.app.reorder_panels(dragged, target_index)

    def _on_back_mode_change(self):
        self.back_edit_btn.configure(state="normal" if self.back_mode_var.get() else "disabled")
        self.app.update_preview()

    def open_back_dialog(self):
        BackCoverDialog(self.app.root, self, self.app)

    def _update_hint(self):
        if self.mode_var.get() == MODE_CROP:
            self.hint_label.configure(text="Bild oben ziehen, um Ausschnitt zu verschieben")
        else:
            self.hint_label.configure(text="")

    def choose_image(self):
        path = filedialog.askopenfilename(
            title="Bild waehlen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Fehler", f"Bild konnte nicht geladen werden:\n{exc}")
            return
        self.pil_image = image
        self.image_path = path
        self.center_x = 0.5
        self.center_y = 0.5
        self.path_label.configure(text=Path(path).name)
        self.app.update_preview()

    @property
    def width_cm(self) -> float:
        try:
            return max(0.1, float(self.width_var.get().replace(",", ".")))
        except ValueError:
            return PANEL_DEFAULTS[self.index]["width_cm"]

    # -- Duenne Adapter-Properties: reichen die Tkinter-Var-Werte als reine
    # Python-Werte durch, damit cover_render.py (framework-unabhaengig,
    # kein Tkinter) diese Panel-Instanzen direkt entgegennehmen kann.
    @property
    def mode(self) -> str:
        return self.mode_var.get()

    @property
    def is_back(self) -> bool:
        return self.back_mode_var.get()

    @property
    def wrap_front(self) -> bool:
        return self.wrap_front_var.get()

    def art_ratio_frac(self) -> float:
        return max(0.01, min(0.99, self.art_ratio_percent / 100.0))

    def name(self) -> str:
        return self.name_var.get() or f"Panel {self.index + 1}"

    def redraw_thumbnail(self):
        w_cm = self.width_cm
        h_cm = self.app.get_height_cm()
        aspect = (w_cm / h_cm) if h_cm else 1.0

        if aspect >= 1:
            tw = self.THUMB_MAX
            th = max(1, round(self.THUMB_MAX / aspect))
        else:
            th = self.THUMB_MAX
            tw = max(1, round(self.THUMB_MAX * aspect))

        image = self.app.render_panel(self, tw, th)
        self._thumb_w, self._thumb_h = tw, th
        self._thumb_art_h = max(1, round(th * self.art_ratio_frac())) if self.back_mode_var.get() else th
        self._thumb_photo = ImageTk.PhotoImage(image)

        self.canvas.delete("all")
        x0 = (self.THUMB_MAX - tw) // 2
        y0 = (self.THUMB_MAX - th) // 2
        self.canvas.create_image(x0, y0, anchor="nw", image=self._thumb_photo)

    def _on_drag_start(self, event):
        if self.mode_var.get() != MODE_CROP or self.pil_image is None:
            self._drag_start = None
            return
        self._drag_start = (event.x, event.y, self.center_x, self.center_y)

    def _on_drag_move(self, event):
        if not self._drag_start:
            return
        start_x, start_y, start_cx, start_cy = self._drag_start
        dx = event.x - start_x
        dy = event.y - start_y
        # Im Rueckseiten-Modus bezieht sich der Ausschnitt nur auf den
        # oberen Artwork-Bereich, nicht auf die gesamte Panel-Hoehe.
        drag_h = self._thumb_art_h if self.back_mode_var.get() else self._thumb_h
        new_cx = min(1.0, max(0.0, start_cx - dx / max(self._thumb_w, 1)))
        new_cy = min(1.0, max(0.0, start_cy - dy / max(drag_h, 1)))
        self.center_x, self.center_y = new_cx, new_cy
        self.redraw_thumbnail()
        self.app.update_preview(skip_thumbnails=True)


class SaveBannerTemplateDialog(tk.Toplevel):
    """Speichert das aktuelle Banner-Bild als wiederverwendbare Vorlage fuer eine Konsole."""

    def __init__(self, parent, banner_path):
        super().__init__(parent)
        self.configure(bg=THEME["panel"])
        self.banner_path = banner_path
        self.title("Banner als Vorlage speichern")
        self.geometry("360x180")
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="NAME DER VORLAGE:", style="Field.TLabel").pack(anchor="w", padx=10, pady=(10, 2))
        self.name_var = tk.StringVar(value=Path(banner_path).stem)
        ttk.Entry(self, textvariable=self.name_var).pack(fill="x", padx=10)

        ttk.Label(self, text="KONSOLE:", style="Field.TLabel").pack(anchor="w", padx=10, pady=(10, 2))
        self.console_var = tk.StringVar(value=CONSOLE_OPTIONS[0])
        ttk.Combobox(
            self, textvariable=self.console_var, values=CONSOLE_OPTIONS, state="readonly"
        ).pack(fill="x", padx=10)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=15)
        ttk.Button(btn_row, text="SPEICHERN", command=self.save).pack(side="right")
        ttk.Button(btn_row, text="ABBRECHEN", style="Secondary.TButton", command=self.destroy).pack(side="right", padx=10)

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showinfo("Hinweis", "Bitte einen Namen fuer die Vorlage angeben.")
            return

        BANNER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        src = Path(self.banner_path)
        dest = BANNER_TEMPLATES_DIR / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        try:
            shutil.copyfile(src, dest)
        except Exception as exc:
            messagebox.showerror("Fehler", f"Vorlage konnte nicht gespeichert werden:\n{exc}")
            return

        conn = sqlite3.connect(DB_PATH)
        try:
            ensure_covers_db(conn)
            conn.execute(
                "INSERT INTO banner_templates (name, file_path, console, created_at) VALUES (?, ?, ?, ?)",
                (name, str(dest.resolve()), self.console_var.get(), time.strftime("%Y-%m-%dT%H:%M:%S")),
            )
            conn.commit()
        finally:
            conn.close()

        messagebox.showinfo("Gespeichert", f"Banner-Vorlage '{name}' fuer {self.console_var.get()} gespeichert.")
        self.destroy()


class BannerTemplateDialog(tk.Toplevel):
    """Zeigt gespeicherte Banner-Vorlagen an und erlaubt das Laden/Loeschen je Konsole."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.configure(bg=THEME["panel"])
        self.app = app
        self.title("Banner-Vorlage laden")
        self.geometry("480x360")
        self.transient(parent)
        self.grab_set()

        filter_row = ttk.Frame(self)
        filter_row.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(filter_row, text="KONSOLE FILTERN:", style="Field.TLabel").pack(side="left")
        self.filter_var = tk.StringVar(value="Alle")
        ttk.Combobox(
            filter_row, textvariable=self.filter_var, values=["Alle"] + CONSOLE_OPTIONS, state="readonly", width=16
        ).pack(side="left", padx=5)
        self.filter_var.trace_add("write", lambda *_: self.refresh_list())

        self.list_box = tk.Listbox(
            self, bg=THEME["input_bg"], fg=THEME["text"],
            selectbackground=THEME["cyan_dim"], selectforeground=THEME["on_cyan"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"],
        )
        self.list_box.pack(fill="both", expand=True, padx=10, pady=4)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="LADEN", command=self.load_selected).pack(side="left")
        ttk.Button(btn_row, text="LOESCHEN", style="Secondary.TButton", command=self.delete_selected).pack(side="left", padx=10)
        ttk.Button(btn_row, text="SCHLIESSEN", command=self.destroy).pack(side="right")

        self._templates = []
        self.refresh_list()

    def refresh_list(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            ensure_covers_db(conn)
            rows = conn.execute(
                "SELECT id, name, file_path, console FROM banner_templates ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()

        console_filter = self.filter_var.get()
        if console_filter and console_filter != "Alle":
            rows = [r for r in rows if r[3] == console_filter]

        self._templates = rows
        self.list_box.delete(0, "end")
        for _tid, name, _file_path, console in rows:
            self.list_box.insert("end", f"{name}  [{console}]")

    def _selected_template(self):
        sel = self.list_box.curselection()
        if not sel:
            return None
        return self._templates[sel[0]]

    def load_selected(self):
        template = self._selected_template()
        if not template:
            messagebox.showinfo("Hinweis", "Bitte eine Vorlage auswaehlen.")
            return
        _tid, _name, file_path, _console = template
        self.app.load_banner_template(file_path)
        self.destroy()

    def delete_selected(self):
        template = self._selected_template()
        if not template:
            return
        tid, name, file_path, _console = template
        if not messagebox.askyesno("Loeschen", f"Vorlage '{name}' wirklich loeschen?"):
            return

        conn = sqlite3.connect(DB_PATH)
        try:
            ensure_covers_db(conn)
            conn.execute("DELETE FROM banner_templates WHERE id=?", (tid,))
            conn.commit()
        finally:
            conn.close()

        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass

        self.refresh_list()


class CoverMakerApp:
    def __init__(self, root):
        self.root = root
        root.title("Cover Maker")
        root.resizable(True, True)
        root.geometry("900x820")
        root.minsize(700, 480)

        self.combined_image = None
        self.last_cover_id = None
        self.banner_image = None
        self.banner_path = None
        self.drag_panel = None

        ttk.Label(
            root, text="◆  STEAM · COVER MAKER SYSTEM  ◆",
            style="Hud.TLabel", anchor="center",
        ).pack(side="top", fill="x", pady=(8, 4))
        ttk.Separator(root, orient="horizontal").pack(side="top", fill="x", padx=10, pady=(0, 4))

        # Aktionsleiste zuerst (und mit side="bottom") einhaengen, damit sie
        # immer sichtbar am unteren Fensterrand bleibt, auch wenn der Inhalt
        # darueber (Panels, Vorschau) mehr Platz braucht als das Fenster hoch
        # ist - der restliche Bereich wird dafuer scrollbar (siehe unten).
        button_frame = ttk.Frame(root)
        button_frame.pack(side="bottom", fill="x", padx=10, pady=10)
        ttk.Button(button_frame, text="SPEICHERN ALS...", command=self.export_image).pack(side="right")
        self.assign_button = ttk.Button(
            button_frame, text="SPIEL ZUWEISEN...", command=self.open_assign_tool, state="disabled"
        )
        self.assign_button.pack(side="right", padx=(0, 10))
        ttk.Button(button_frame, text="PROJEKT LADEN...", command=self.open_project_dialog).pack(
            side="left"
        )

        scroll_area = ttk.Frame(root)
        scroll_area.pack(side="top", fill="both", expand=True)

        scroll_canvas = tk.Canvas(scroll_area, bg=THEME["panel"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scroll_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        content = ttk.Frame(scroll_canvas)
        content_window = scroll_canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scrollregion(_event=None):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def _sync_content_width(event):
            scroll_canvas.itemconfig(content_window, width=event.width)
            draw_hud_grid(scroll_canvas, width=event.width, height=event.height)

        content.bind("<Configure>", _sync_scrollregion)
        scroll_canvas.bind("<Configure>", _sync_content_width)

        def _on_mousewheel(event):
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        root = content  # ab hier haengen alle Inhalts-Widgets im scrollbaren Bereich

        settings_frame = ttk.Frame(root)
        settings_frame.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(settings_frame, text="HOEHE (CM):", style="Field.TLabel").pack(side="left")
        self.height_var = tk.StringVar(value="10")
        ttk.Entry(settings_frame, textvariable=self.height_var, width=6).pack(side="left", padx=(2, 15))
        self.height_var.trace_add("write", lambda *_: self.update_preview())

        ttk.Label(settings_frame, text="DPI:", style="Field.TLabel").pack(side="left")
        self.dpi_var = tk.StringVar(value="300")
        ttk.Entry(settings_frame, textvariable=self.dpi_var, width=6).pack(side="left", padx=(2, 15))
        self.dpi_var.trace_add("write", lambda *_: self.update_preview())

        self.info_label = ttk.Label(settings_frame, text="")
        self.info_label.pack(side="left", padx=15)

        banner_frame = ttk.LabelFrame(root, text="BANNER (Z. B. STEAM-LEISTE OBEN)")
        banner_frame.pack(fill="x", padx=10, pady=(10, 0))

        banner_row = ttk.Frame(banner_frame)
        banner_row.pack(fill="x", padx=5, pady=5)
        ttk.Button(banner_row, text="BANNER-BILD WAEHLEN...", command=self.choose_banner_image).pack(side="left")
        self.banner_path_label = ttk.Label(banner_row, text="kein Banner", width=30, anchor="w")
        self.banner_path_label.pack(side="left", padx=10)
        ttk.Button(banner_row, text="ENTFERNEN", style="Secondary.TButton", command=self.clear_banner).pack(side="left")

        ttk.Label(banner_row, text="HOEHE (CM):", style="Field.TLabel").pack(side="left", padx=(20, 2))
        self.banner_height_var = tk.StringVar(value="1.0")
        ttk.Entry(banner_row, textvariable=self.banner_height_var, width=6).pack(side="left")
        self.banner_height_var.trace_add("write", lambda *_: self.update_preview())

        banner_template_row = ttk.Frame(banner_frame)
        banner_template_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Button(
            banner_template_row, text="ALS VORLAGE SPEICHERN...", command=self.save_banner_template
        ).pack(side="left")
        ttk.Button(
            banner_template_row, text="VORLAGE LADEN...", command=self.open_banner_template_dialog
        ).pack(side="left", padx=10)

        ttk.Label(
            banner_frame,
            text=(
                "Das Banner ueberlagert oben alle Panels ausser denen, die als \"Rueckseite\" markiert sind. "
                "Panels koennen per Ziehen am “☰”-Griff neu sortiert werden."
            ),
            style="Dim.TLabel",
        ).pack(fill="x", padx=5, pady=(0, 5))

        self.panels_frame = ttk.Frame(root)
        self.panels_frame.pack(fill="x", padx=10, pady=10)

        self.panels = [Panel(self.panels_frame, i, self) for i in range(4)]
        for i in range(4):
            self.panels_frame.columnconfigure(i, weight=1)

        preview_frame = ttk.LabelFrame(root, text="GESAMTVORSCHAU")
        preview_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(padx=5, pady=5)

        self._preview_photo = None
        self.update_preview()

    def _dpi(self) -> int:
        try:
            return max(1, int(float(self.dpi_var.get())))
        except ValueError:
            return 300

    def get_dpi(self) -> int:
        return self._dpi()

    def _height_cm(self) -> float:
        try:
            return max(0.1, float(self.height_var.get().replace(",", ".")))
        except ValueError:
            return 10.0

    def get_height_cm(self) -> float:
        return self._height_cm()

    def _banner_height_cm(self) -> float:
        try:
            return max(0.0, float(self.banner_height_var.get().replace(",", ".")))
        except ValueError:
            return 1.0

    # -- Banner -----------------------------------------------------
    def choose_banner_image(self):
        path = filedialog.askopenfilename(
            title="Banner-Bild waehlen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Fehler", f"Banner konnte nicht geladen werden:\n{exc}")
            return
        self.banner_image = image
        self.banner_path = path
        self.banner_path_label.configure(text=Path(path).name)
        self.update_preview()

    def clear_banner(self):
        self.banner_image = None
        self.banner_path = None
        self.banner_path_label.configure(text="kein Banner")
        self.update_preview()

    def save_banner_template(self):
        if self.banner_image is None or self.banner_path is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst ein Banner-Bild waehlen.")
            return
        SaveBannerTemplateDialog(self.root, self.banner_path)

    def open_banner_template_dialog(self):
        BannerTemplateDialog(self.root, self)

    def load_banner_template(self, file_path):
        try:
            image = Image.open(file_path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Fehler", f"Vorlage konnte nicht geladen werden:\n{exc}")
            return
        self.banner_image = image
        self.banner_path = file_path
        self.banner_path_label.configure(text=Path(file_path).name)
        self.update_preview()

    # -- Panel-Reihenfolge (Drag & Drop) --------------------------------
    def panel_index_at_x(self, x_root):
        """Ermittelt anhand einer Bildschirm-X-Koordinate, ueber welchem
        Panel (bzw. welcher Panel-Luecke) losgelassen wurde."""
        best_index = None
        best_dist = None
        for i, panel in enumerate(self.panels):
            fx = panel.frame.winfo_rootx()
            fw = panel.frame.winfo_width()
            center = fx + fw / 2
            dist = abs(x_root - center)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_index = i
        return best_index

    def reorder_panels(self, moved_panel, target_index):
        if moved_panel not in self.panels:
            return
        current_index = self.panels.index(moved_panel)
        if target_index is None or target_index == current_index:
            return
        self.panels.pop(current_index)
        self.panels.insert(target_index, moved_panel)
        for i, panel in enumerate(self.panels):
            panel.index = i
            panel.frame.grid_configure(column=i)
        self.update_preview()

    # -- Rendering -----------------------------------------------------
    # Die eigentliche Bildkomposition (Zuschnitt, Banner, Rueckseite mit
    # Systemanforderungen/Kompatibilitaet/Logos) lebt in cover_render.py
    # (framework-unabhaengig) - hier nur noch duenne Wrapper, die die
    # App-Einstellungen (Hoehe/DPI/Banner) durchreichen. Die Web-Variante
    # (tools/cover_maker/server/) nutzt dieselben cover_render-Funktionen
    # und erzeugt so garantiert dasselbe Ergebnisbild wie die Desktop-App.
    def render_back_panel(self, panel: "Panel", w_px: int, h_px: int) -> Image.Image:
        return cover_render.render_back_panel(panel, w_px, h_px)

    def _front_panel(self):
        return next((p for p in self.panels if p.is_front), None)

    def _banner_reserved_px(self, h_px: int) -> int:
        return cover_render.banner_reserved_px(
            self.banner_image, self._banner_height_cm(), self._height_cm(), h_px
        )

    def render_panel(self, panel: "Panel", w_px: int, h_px: int) -> Image.Image:
        return cover_render.render_panel(
            panel, w_px, h_px, panels=self.panels,
            banner_image=self.banner_image, banner_height_cm=self._banner_height_cm(), height_cm=self._height_cm(),
        )

    def build_combined_image(self):
        return cover_render.build_combined_image(
            self.panels, self._height_cm(), self._dpi(), self.banner_image, self._banner_height_cm()
        )

    def update_preview(self, skip_thumbnails=False):
        try:
            combined = self.build_combined_image()
        except Exception as exc:
            self.info_label.configure(text=f"Fehler: {exc}")
            return

        self.combined_image = combined
        w, h = combined.size
        scale = min(PREVIEW_MAX_W / w, PREVIEW_MAX_H / h, 1.0)
        preview = combined.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

        self._preview_photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self._preview_photo)
        self.info_label.configure(text=f"{w} x {h} px  ({w / self._dpi():.1f} x {h / self._dpi():.1f} in)")

        if not skip_thumbnails:
            for panel in self.panels:
                panel.redraw_thumbnail()

    def _draw_dashed_vline(self, draw, x, y0, y1, dash_len, gap_len, width, fill):
        y = y0
        while y < y1:
            y_end = min(y + dash_len, y1)
            draw.line([x, y, x, y_end], fill=fill, width=width)
            y += dash_len + gap_len

    def _localize_project_assets(self, cover_dir: Path):
        """Kopiert Banner-, Panel- und Logo-Bilder in cover_dir und
        aktualisiert die eigenen Pfad-Referenzen darauf, damit auch
        spaetere Aktionen (erneutes Speichern, Projekt-Export) die
        lokalen Kopien statt der urspruenglichen Quelldateien nutzen."""
        if self.banner_path:
            self.banner_path = _localize_asset(self.banner_path, cover_dir)
        for panel in self.panels:
            if panel.image_path:
                panel.image_path = _localize_asset(panel.image_path, cover_dir)
            panel.logo_paths = [_localize_asset(p, cover_dir) for p in panel.logo_paths]

    def export_image(self):
        combined = self.build_combined_image()
        path = filedialog.asksaveasfilename(
            title="Cover speichern",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return

        # Alles, was zu diesem Cover gehoert (PNG, Schneidelinien-Referenz,
        # Projektdatei und alle darin verwendeten Quellbilder), landet
        # gemeinsam in einem Unterordner mit dem Namen der PNG-Datei, damit
        # ein Cover-Projekt immer vollstaendig lokal und in sich
        # geschlossen bleibt (verschiebbar/kopierbar, ohne Referenzen auf
        # Dateien ausserhalb des Ordners).
        chosen = Path(path)
        cover_dir = chosen.parent / chosen.stem
        cover_dir.mkdir(parents=True, exist_ok=True)
        path = str(cover_dir / chosen.name)

        dpi = self._dpi()
        try:
            combined.save(path, dpi=(dpi, dpi))
        except Exception as exc:
            messagebox.showerror("Fehler", f"Speichern fehlgeschlagen:\n{exc}")
            return

        # Schneidelinien-Referenzbild separat speichern: das eigentliche
        # Cover wird spaeter 1:1 als Spiel-Cover verwendet und soll daher
        # sauber bleiben (kein eingebrannter Rahmen im echten Artwork).
        # Zusaetzlich zum durchgezogenen Schneiderand werden gestrichelte
        # Faltlinien an jeder Panel-Grenze eingezeichnet.
        info_extra = ""
        try:
            cutline_image = combined.copy()
            draw = ImageDraw.Draw(cutline_image)
            line_px = max(1, round(dpi / 300))
            draw.rectangle(
                [0, 0, cutline_image.width - 1, cutline_image.height - 1],
                outline="black",
                width=line_px,
            )

            widths_px = [cm_to_px(p.width_cm, dpi) for p in self.panels]
            dash_len = max(4, round(dpi / 300 * 10))
            gap_len = max(3, round(dpi / 300 * 6))
            fold_cursor = 0
            for w_px in widths_px[:-1]:
                fold_cursor += w_px
                self._draw_dashed_vline(
                    draw, fold_cursor, 0, cutline_image.height, dash_len, gap_len, line_px, "black"
                )

            cutline_path = Path(path).with_name(f"{Path(path).stem}_schneidelinien{Path(path).suffix}")
            cutline_image.save(cutline_path, dpi=(dpi, dpi))
            info_extra += f"\nSchneide-/Faltlinien-Referenz: {cutline_path.name}"
        except Exception as exc:
            messagebox.showwarning("Hinweis", f"Schneidelinien-Referenzbild konnte nicht gespeichert werden:\n{exc}")

        # Alle im Projekt verwendeten Quellbilder (Panel-Bilder, Banner,
        # Logos) in den Cover-Ordner kopieren und die eigenen Referenzen
        # darauf umbiegen, bevor die Projektdatei geschrieben wird - so
        # zeigt sie nur noch auf lokale Dateien im selben Ordner.
        self._localize_project_assets(cover_dir)

        # Projektdatei speichern, damit das Cover spaeter mit allen
        # Einstellungen (Bilder, Zuschnitt, Rueckseiten-Text, Banner, ...)
        # wieder geladen und weiterbearbeitet werden kann.
        try:
            project_path = Path(path).with_name(f"{Path(path).stem}.covermaker.json")
            self.save_project_file(project_path)
            info_extra += f"\nProjektdatei: {project_path.name}"
        except Exception as exc:
            messagebox.showwarning("Hinweis", f"Projektdatei konnte nicht gespeichert werden:\n{exc}")

        resolved_path = str(Path(path).resolve())
        conn = sqlite3.connect(DB_PATH)
        try:
            ensure_covers_db(conn)
            cursor = conn.execute(
                """
                INSERT INTO covers (file_path, width_cm, height_cm, dpi, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    resolved_path,
                    sum(p.width_cm for p in self.panels),
                    self._height_cm(),
                    dpi,
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                ),
            )
            conn.commit()
            self.last_cover_id = cursor.lastrowid
        finally:
            conn.close()

        self.assign_button.configure(state="normal")
        messagebox.showinfo(
            "Gespeichert", f"Cover gespeichert unter:\n{path}\n\n(In der Datenbank vermerkt.){info_extra}"
        )

    # -- Projekt speichern/laden ----------------------------------------
    def serialize_state(self) -> dict:
        return {
            "format": "cover_maker_project",
            "version": 1,
            "height_cm": self.height_var.get(),
            "dpi": self.dpi_var.get(),
            "banner_path": self.banner_path,
            "banner_height_cm": self.banner_height_var.get(),
            "panels": [self._serialize_panel(p) for p in self.panels],
        }

    def _serialize_panel(self, panel: Panel) -> dict:
        return {
            "name": panel.name_var.get(),
            "image_path": panel.image_path,
            "center_x": panel.center_x,
            "center_y": panel.center_y,
            "width_cm": panel.width_var.get(),
            "mode": panel.mode_var.get(),
            "is_front": panel.is_front,
            "back_mode": panel.back_mode_var.get(),
            "wrap_front": panel.wrap_front_var.get(),
            "art_ratio_percent": panel.art_ratio_percent,
            "min_title": panel.min_title,
            "rec_title": panel.rec_title,
            "min_text_content": panel.min_text_content,
            "rec_text_content": panel.rec_text_content,
            "logo_paths": list(panel.logo_paths),
            "show_compat": panel.show_compat,
            "steamdeck_rating": panel.steamdeck_rating,
            "steammachine_rating": panel.steammachine_rating,
            "input_kbm": panel.input_kbm,
            "input_controller": panel.input_controller,
        }

    def save_project_file(self, path):
        data = self.serialize_state()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def open_project_dialog(self):
        path = filedialog.askopenfilename(
            title="Projekt laden",
            filetypes=[("Cover-Maker-Projekt", "*.json"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        self.load_project_file(path)

    def load_project_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            messagebox.showerror("Fehler", f"Projekt konnte nicht geladen werden:\n{exc}")
            return

        panels_data = data.get("panels", [])
        if len(panels_data) != len(self.panels):
            messagebox.showerror("Fehler", "Projektdatei passt nicht zur Anzahl der Panels.")
            return

        self.height_var.set(str(data.get("height_cm", self.height_var.get())))
        self.dpi_var.set(str(data.get("dpi", self.dpi_var.get())))
        self.banner_height_var.set(str(data.get("banner_height_cm", self.banner_height_var.get())))

        missing_files = []
        banner_path = data.get("banner_path")
        if banner_path:
            try:
                image = Image.open(banner_path)
                image.load()
                self.banner_image = image
                self.banner_path = banner_path
                self.banner_path_label.configure(text=Path(banner_path).name)
            except Exception:
                self.banner_image = None
                self.banner_path = None
                self.banner_path_label.configure(text="kein Banner")
                missing_files.append(banner_path)
        else:
            self.banner_image = None
            self.banner_path = None
            self.banner_path_label.configure(text="kein Banner")

        for panel, pdata in zip(self.panels, panels_data):
            self._apply_panel_state(panel, pdata, missing_files)

        self.update_preview()

        if missing_files:
            messagebox.showwarning(
                "Hinweis",
                "Folgende Dateien wurden nicht gefunden und muessen neu ausgewaehlt werden:\n"
                + "\n".join(missing_files),
            )

    def _apply_panel_state(self, panel: Panel, pdata: dict, missing_files: list):
        panel.name_var.set(pdata.get("name", panel.name_var.get()))
        panel.width_var.set(str(pdata.get("width_cm", panel.width_var.get())))
        panel.mode_var.set(pdata.get("mode", panel.mode_var.get()))
        panel._update_hint()

        panel.is_front = bool(pdata.get("is_front", panel.is_front))
        panel.back_mode_var.set(bool(pdata.get("back_mode", panel.back_mode_var.get())))
        panel.back_edit_btn.configure(state="normal" if panel.back_mode_var.get() else "disabled")
        panel.wrap_front_var.set(bool(pdata.get("wrap_front", panel.wrap_front_var.get())))

        panel.center_x = float(pdata.get("center_x", panel.center_x))
        panel.center_y = float(pdata.get("center_y", panel.center_y))
        panel.art_ratio_percent = float(pdata.get("art_ratio_percent", panel.art_ratio_percent))
        panel.min_title = pdata.get("min_title", panel.min_title)
        panel.rec_title = pdata.get("rec_title", panel.rec_title)
        panel.min_text_content = pdata.get("min_text_content", panel.min_text_content)
        panel.rec_text_content = pdata.get("rec_text_content", panel.rec_text_content)
        panel.show_compat = bool(pdata.get("show_compat", panel.show_compat))
        panel.steamdeck_rating = pdata.get("steamdeck_rating", panel.steamdeck_rating)
        panel.steammachine_rating = pdata.get("steammachine_rating", panel.steammachine_rating)
        panel.input_kbm = bool(pdata.get("input_kbm", panel.input_kbm))
        panel.input_controller = bool(pdata.get("input_controller", panel.input_controller))

        panel.pil_image = None
        panel.image_path = None
        panel.path_label.configure(text="kein Bild")
        image_path = pdata.get("image_path")
        if image_path:
            try:
                image = Image.open(image_path)
                image.load()
                panel.pil_image = image
                panel.image_path = image_path
                panel.path_label.configure(text=Path(image_path).name)
            except Exception:
                missing_files.append(image_path)

        panel.logo_paths = []
        panel.logos = []
        for logo_path in pdata.get("logo_paths", []):
            try:
                logo_img = Image.open(logo_path)
                logo_img.load()
                panel.logo_paths.append(logo_path)
                panel.logos.append(logo_img)
            except Exception:
                missing_files.append(logo_path)

    def open_assign_tool(self):
        if self.last_cover_id is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst ein Cover speichern.")
            return
        try:
            subprocess.Popen([sys.executable, str(ASSIGN_SCRIPT), "--cover-id", str(self.last_cover_id)])
        except Exception as exc:
            messagebox.showerror("Fehler", f"Zuweisungs-Tool konnte nicht gestartet werden:\n{exc}")


def main():
    root = tk.Tk()
    apply_theme(root)
    CoverMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
