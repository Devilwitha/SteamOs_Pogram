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

from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageOps

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

MODE_CROP = "Zuschneiden (Ausschnitt waehlen)"
MODE_STRETCH = "Fuellen (Groesse anpassen)"
MODE_CONTAIN = "Einpassen (mit Rand)"
FIT_MODES = [MODE_CROP, MODE_STRETCH, MODE_CONTAIN]

PREVIEW_MAX_W = 900
PREVIEW_MAX_H = 400

DEFAULT_REQUIREMENTS_TEXT = "OS: \nProcessor: \nMemory: \nGraphics: \nStorage: "
DEFAULT_MIN_TITLE = "Minimum"
DEFAULT_REC_TITLE = "Empfohlen"

RATING_OPTIONS = ["Nicht bewertet", "Verifiziert", "Spielbar", "Nicht unterstuetzt"]
RATING_COLORS = {
    "Nicht bewertet": "#8a8a8a",
    "Verifiziert": "#1a9c4b",
    "Spielbar": "#c9a227",
    "Nicht unterstuetzt": "#b3261e",
}

CONSOLE_OPTIONS = ["Steam Deck", "Steam Machine", "Beide", "Allgemein"]
BANNER_TEMPLATES_DIR = SCRIPT_DIR / "banner_templates"

_FONT_CACHE = {}


def cm_to_px(cm: float, dpi: int) -> int:
    return max(1, round(cm / 2.54 * dpi))


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


def load_font(bold: bool, size: int):
    size = max(6, size)
    key = (bold, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    candidates = ["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]
    font = None
    for name in candidates:
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    _FONT_CACHE[key] = font
    return font


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
    conn.commit()


class BackCoverDialog(tk.Toplevel):
    """Bearbeitet Bildanteil, Minimum-/Empfohlen-Text und Firmenlogos einer Rueckseite."""

    def __init__(self, parent, panel, app):
        super().__init__(parent)
        self.panel = panel
        self.app = app
        self.title(f"Rueckseiten-Inhalt - {panel.name()}")
        self.geometry("600x760")
        self.transient(parent)

        ratio_row = ttk.Frame(self)
        ratio_row.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(ratio_row, text="Bildanteil oben (%):").pack(side="left")
        self.ratio_var = tk.StringVar(value=str(panel.art_ratio_percent))
        ttk.Entry(ratio_row, textvariable=self.ratio_var, width=6).pack(side="left", padx=5)
        ttk.Label(ratio_row, text="(Rest = Anforderungen + Kompatibilitaet + Logos)", foreground="#666").pack(side="left")

        text_row = ttk.Frame(self)
        text_row.pack(fill="both", expand=True, padx=10, pady=4)
        text_row.columnconfigure(0, weight=1)
        text_row.columnconfigure(1, weight=1)
        text_row.rowconfigure(0, weight=1)

        min_col = ttk.LabelFrame(text_row, text="Minimum-Spalte")
        min_col.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        min_title_row = ttk.Frame(min_col)
        min_title_row.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(min_title_row, text="Titel:").pack(side="left")
        self.min_title_var = tk.StringVar(value=panel.min_title)
        ttk.Entry(min_title_row, textvariable=self.min_title_var).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.min_text = tk.Text(min_col, width=28, height=8)
        self.min_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.min_text.insert("1.0", panel.min_text_content)

        rec_col = ttk.LabelFrame(text_row, text="Empfohlen-Spalte")
        rec_col.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        rec_title_row = ttk.Frame(rec_col)
        rec_title_row.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(rec_title_row, text="Titel:").pack(side="left")
        self.rec_title_var = tk.StringVar(value=panel.rec_title)
        ttk.Entry(rec_title_row, textvariable=self.rec_title_var).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.rec_text = tk.Text(rec_col, width=28, height=8)
        self.rec_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.rec_text.insert("1.0", panel.rec_text_content)

        compat_frame = ttk.LabelFrame(self, text="Steam-Kompatibilitaet & Eingabegeraete")
        compat_frame.pack(fill="x", padx=10, pady=(4, 4))

        self.show_compat_var = tk.BooleanVar(value=panel.show_compat)
        ttk.Checkbutton(
            compat_frame, text="Auf dem Cover anzeigen", variable=self.show_compat_var
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=(4, 2))

        ttk.Label(compat_frame, text="Steam Deck:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.steamdeck_var = tk.StringVar(value=panel.steamdeck_rating)
        ttk.Combobox(
            compat_frame, textvariable=self.steamdeck_var, values=RATING_OPTIONS, state="readonly", width=18
        ).grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(compat_frame, text="Steam Machine:").grid(row=1, column=2, sticky="w", padx=4, pady=2)
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

        logos_frame = ttk.LabelFrame(self, text="Firmenlogos (werden unten in einer Reihe angezeigt)")
        logos_frame.pack(fill="x", padx=10, pady=(4, 10))
        self.logos_list = tk.Listbox(logos_frame, height=4)
        self.logos_list.pack(side="left", fill="both", expand=True, padx=(4, 4), pady=4)
        for logo_path in panel.logo_paths:
            self.logos_list.insert("end", Path(logo_path).name)

        logos_btns = ttk.Frame(logos_frame)
        logos_btns.pack(side="left", padx=(0, 4), pady=4)
        ttk.Button(logos_btns, text="Hinzufuegen...", command=self.add_logos).pack(fill="x", pady=2)
        ttk.Button(logos_btns, text="Entfernen", command=self.remove_selected_logo).pack(fill="x", pady=2)
        ttk.Button(logos_btns, text="Alle loeschen", command=self.clear_logos).pack(fill="x", pady=2)

        self._logos = list(zip(panel.logo_paths, panel.logos))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="Uebernehmen", command=self.apply).pack(side="right")
        ttk.Button(btn_row, text="Abbrechen", command=self.destroy).pack(side="right", padx=10)

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
            self.frame, text="☰ Ziehen zum Sortieren", foreground="#888", cursor="fleur", anchor="center"
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

        ttk.Button(self.frame, text="Bild waehlen", command=self.choose_image).grid(
            row=3, column=0, columnspan=2, pady=2
        )

        width_row = ttk.Frame(self.frame)
        width_row.grid(row=4, column=0, columnspan=2, pady=2)
        ttk.Label(width_row, text="Breite (cm):").pack(side="left")
        self.width_var = tk.StringVar(value=str(PANEL_DEFAULTS[index]["width_cm"]))
        ttk.Entry(width_row, textvariable=self.width_var, width=6).pack(side="left")
        self.width_var.trace_add("write", lambda *_: self.app.update_preview())

        ttk.Label(self.frame, text="Modus:").grid(row=5, column=0, columnspan=2)
        self.mode_var = tk.StringVar(value=FIT_MODES[0])
        mode_combo = ttk.Combobox(
            self.frame, textvariable=self.mode_var, values=FIT_MODES, state="readonly", width=22
        )
        mode_combo.grid(row=6, column=0, columnspan=2, pady=2)
        mode_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_mode_change())

        self.canvas = tk.Canvas(
            self.frame, width=self.THUMB_MAX, height=self.THUMB_MAX, bg="#ddd", cursor="fleur"
        )
        self.canvas.grid(row=7, column=0, columnspan=2, pady=4)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)

        self.hint_label = ttk.Label(self.frame, text="", foreground="#666", wraplength=120, justify="center")
        self.hint_label.grid(row=8, column=0, columnspan=2)
        self._update_hint()

        self.back_mode_var = tk.BooleanVar(value=(index == BACK_PANEL_INDEX))
        ttk.Checkbutton(
            self.frame, text="Ist Rueckseite", variable=self.back_mode_var, command=self._on_back_mode_change
        ).grid(row=9, column=0, columnspan=2, pady=(6, 0))

        self.back_edit_btn = ttk.Button(
            self.frame,
            text="Rueckseiten-Inhalt...",
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

    def width_cm(self) -> float:
        try:
            return max(0.1, float(self.width_var.get().replace(",", ".")))
        except ValueError:
            return PANEL_DEFAULTS[self.index]["width_cm"]

    def art_ratio_frac(self) -> float:
        return max(0.01, min(0.99, self.art_ratio_percent / 100.0))

    def name(self) -> str:
        return self.name_var.get() or f"Panel {self.index + 1}"

    def redraw_thumbnail(self):
        w_cm = self.width_cm()
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
        self.banner_path = banner_path
        self.title("Banner als Vorlage speichern")
        self.geometry("360x180")
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="Name der Vorlage:").pack(anchor="w", padx=10, pady=(10, 2))
        self.name_var = tk.StringVar(value=Path(banner_path).stem)
        ttk.Entry(self, textvariable=self.name_var).pack(fill="x", padx=10)

        ttk.Label(self, text="Konsole:").pack(anchor="w", padx=10, pady=(10, 2))
        self.console_var = tk.StringVar(value=CONSOLE_OPTIONS[0])
        ttk.Combobox(
            self, textvariable=self.console_var, values=CONSOLE_OPTIONS, state="readonly"
        ).pack(fill="x", padx=10)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=15)
        ttk.Button(btn_row, text="Speichern", command=self.save).pack(side="right")
        ttk.Button(btn_row, text="Abbrechen", command=self.destroy).pack(side="right", padx=10)

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
        self.app = app
        self.title("Banner-Vorlage laden")
        self.geometry("480x360")
        self.transient(parent)
        self.grab_set()

        filter_row = ttk.Frame(self)
        filter_row.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(filter_row, text="Konsole filtern:").pack(side="left")
        self.filter_var = tk.StringVar(value="Alle")
        ttk.Combobox(
            filter_row, textvariable=self.filter_var, values=["Alle"] + CONSOLE_OPTIONS, state="readonly", width=16
        ).pack(side="left", padx=5)
        self.filter_var.trace_add("write", lambda *_: self.refresh_list())

        self.list_box = tk.Listbox(self)
        self.list_box.pack(fill="both", expand=True, padx=10, pady=4)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="Laden", command=self.load_selected).pack(side="left")
        ttk.Button(btn_row, text="Loeschen", command=self.delete_selected).pack(side="left", padx=10)
        ttk.Button(btn_row, text="Schliessen", command=self.destroy).pack(side="right")

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

        self.combined_image = None
        self.last_cover_id = None
        self.banner_image = None
        self.banner_path = None
        self.drag_panel = None

        settings_frame = ttk.Frame(root)
        settings_frame.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(settings_frame, text="Hoehe (cm):").pack(side="left")
        self.height_var = tk.StringVar(value="10")
        ttk.Entry(settings_frame, textvariable=self.height_var, width=6).pack(side="left", padx=(2, 15))
        self.height_var.trace_add("write", lambda *_: self.update_preview())

        ttk.Label(settings_frame, text="DPI:").pack(side="left")
        self.dpi_var = tk.StringVar(value="300")
        ttk.Entry(settings_frame, textvariable=self.dpi_var, width=6).pack(side="left", padx=(2, 15))
        self.dpi_var.trace_add("write", lambda *_: self.update_preview())

        self.info_label = ttk.Label(settings_frame, text="")
        self.info_label.pack(side="left", padx=15)

        banner_frame = ttk.LabelFrame(root, text="Banner (z. B. Steam-Leiste oben)")
        banner_frame.pack(fill="x", padx=10, pady=(10, 0))

        banner_row = ttk.Frame(banner_frame)
        banner_row.pack(fill="x", padx=5, pady=5)
        ttk.Button(banner_row, text="Banner-Bild waehlen...", command=self.choose_banner_image).pack(side="left")
        self.banner_path_label = ttk.Label(banner_row, text="kein Banner", width=30, anchor="w")
        self.banner_path_label.pack(side="left", padx=10)
        ttk.Button(banner_row, text="Entfernen", command=self.clear_banner).pack(side="left")

        ttk.Label(banner_row, text="Hoehe (cm):").pack(side="left", padx=(20, 2))
        self.banner_height_var = tk.StringVar(value="1.0")
        ttk.Entry(banner_row, textvariable=self.banner_height_var, width=6).pack(side="left")
        self.banner_height_var.trace_add("write", lambda *_: self.update_preview())

        banner_template_row = ttk.Frame(banner_frame)
        banner_template_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Button(
            banner_template_row, text="Als Vorlage speichern...", command=self.save_banner_template
        ).pack(side="left")
        ttk.Button(
            banner_template_row, text="Vorlage laden...", command=self.open_banner_template_dialog
        ).pack(side="left", padx=10)

        ttk.Label(
            banner_frame,
            text=(
                "Das Banner ueberlagert oben alle Panels ausser denen, die als \"Rueckseite\" markiert sind. "
                "Panels koennen per Ziehen am “☰”-Griff neu sortiert werden."
            ),
            foreground="#666",
        ).pack(fill="x", padx=5, pady=(0, 5))

        self.panels_frame = ttk.Frame(root)
        self.panels_frame.pack(fill="x", padx=10, pady=10)

        self.panels = [Panel(self.panels_frame, i, self) for i in range(4)]
        for i in range(4):
            self.panels_frame.columnconfigure(i, weight=1)

        preview_frame = ttk.LabelFrame(root, text="Gesamtvorschau")
        preview_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(padx=5, pady=5)

        button_frame = ttk.Frame(root)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(button_frame, text="Speichern als...", command=self.export_image).pack(side="right")
        self.assign_button = ttk.Button(
            button_frame, text="Spiel zuweisen...", command=self.open_assign_tool, state="disabled"
        )
        self.assign_button.pack(side="right", padx=(0, 10))
        ttk.Button(button_frame, text="Projekt laden...", command=self.open_project_dialog).pack(
            side="left"
        )

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
    def _render_source(self, src_image, mode, w_px, h_px, center_x=0.5, center_y=0.5):
        w_px = max(1, w_px)
        h_px = max(1, h_px)
        src = src_image.convert("RGB")

        if mode == MODE_STRETCH:
            return src.resize((w_px, h_px), Image.LANCZOS)

        if mode == MODE_CONTAIN:
            fitted = ImageOps.contain(src, (w_px, h_px), method=Image.LANCZOS)
            canvas = Image.new("RGB", (w_px, h_px), "white")
            canvas.paste(fitted, ((w_px - fitted.width) // 2, (h_px - fitted.height) // 2))
            return canvas

        # MODE_CROP (Standard)
        return ImageOps.fit(src, (w_px, h_px), method=Image.LANCZOS, centering=(center_x, center_y))

    def _draw_requirements(self, draw, panel, x, y, w, h):
        if h <= 10 or w <= 10:
            return
        pad = max(4, round(w * 0.02))
        col_w = max(1, (w - pad * 3) // 2)
        col1_x = x + pad
        col2_x = x + pad * 2 + col_w

        # Kleiner gehalten als Fliesstext, damit mehr Platz fuer
        # Kompatibilitaets-Infos und Logos bleibt.
        header_size = max(8, round(h * 0.085))
        body_size = max(6, round(h * 0.06))
        font_bold = load_font(True, header_size)
        font_reg = load_font(False, body_size)
        line_gap = max(2, round(body_size * 0.4))

        draw.text((col1_x, y + pad), panel.min_title, font=font_bold, fill="black")
        draw.text((col2_x, y + pad), panel.rec_title, font=font_bold, fill="black")

        line_y = y + pad + header_size + line_gap
        for line in panel.min_text_content.splitlines():
            draw.text((col1_x, line_y), line, font=font_reg, fill="black")
            line_y += body_size + line_gap

        line_y = y + pad + header_size + line_gap
        for line in panel.rec_text_content.splitlines():
            draw.text((col2_x, line_y), line, font=font_reg, fill="black")
            line_y += body_size + line_gap

    def _fit_font(self, draw, text, bold, max_size, max_width):
        size = max_size
        while size > 6:
            font = load_font(bold, size)
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_width:
                return font
            size -= 1
        return load_font(bold, 6)

    def _draw_rating_badge(self, draw, cx, cy, w, h, label, rating):
        if w <= 4 or h <= 4:
            return
        color = RATING_COLORS.get(rating, RATING_COLORS["Nicht bewertet"])
        radius = max(3, round(h * 0.18))
        draw.rounded_rectangle([cx, cy, cx + w, cy + h], radius=radius, fill=color)

        pad = max(2, round(h * 0.08))
        avail_text_w = max(4, w - pad * 2)
        label_size = max(7, round(h * 0.32))
        value_size = max(6, round(h * 0.26))
        font_label = self._fit_font(draw, label, True, label_size, avail_text_w)
        font_value = self._fit_font(draw, rating, False, value_size, avail_text_w)

        label_h = font_label.getbbox(label)[3] - font_label.getbbox(label)[1] if hasattr(font_label, "getbbox") else label_size
        draw.text((cx + pad, cy + pad), label, font=font_label, fill="white")
        draw.text((cx + pad, cy + pad + label_h + max(1, round(h * 0.04))), rating, font=font_value, fill="white")

    def _draw_kbm_icon(self, draw, x, y, size, color="#333333"):
        kb_w = size * 0.62
        kb_h = size * 0.55
        kb_y = y + (size - kb_h) / 2
        draw.rounded_rectangle([x, kb_y, x + kb_w, kb_y + kb_h], radius=max(1, size * 0.04), outline=color, width=2)
        rows, cols = 2, 4
        key_pad_x = kb_w * 0.1
        key_pad_y = kb_h * 0.18
        cell_w = (kb_w - key_pad_x * 2) / cols
        cell_h = (kb_h - key_pad_y * 2) / rows
        for r in range(rows):
            for c in range(cols):
                kx = x + key_pad_x + c * cell_w + cell_w * 0.15
                ky = kb_y + key_pad_y + r * cell_h + cell_h * 0.15
                draw.rectangle([kx, ky, kx + cell_w * 0.7, ky + cell_h * 0.7], outline=color, width=1)

        mouse_w = size * 0.26
        mouse_h = size * 0.8
        mouse_x = x + kb_w + size * 0.12
        mouse_y = y + (size - mouse_h) / 2
        draw.rounded_rectangle(
            [mouse_x, mouse_y, mouse_x + mouse_w, mouse_y + mouse_h], radius=mouse_w * 0.45, outline=color, width=2
        )
        draw.line([mouse_x + mouse_w / 2, mouse_y, mouse_x + mouse_w / 2, mouse_y + mouse_h * 0.35], fill=color, width=2)

    def _draw_controller_icon(self, draw, x, y, size, color="#333333"):
        body_h = size * 0.5
        body_y = y + (size - body_h) / 2
        draw.rounded_rectangle([x, body_y, x + size, body_y + body_h], radius=body_h * 0.45, outline=color, width=2)

        stick_r = size * 0.08
        draw.ellipse(
            [x + size * 0.16, body_y + body_h * 0.25, x + size * 0.16 + stick_r * 2, body_y + body_h * 0.25 + stick_r * 2],
            outline=color, width=2,
        )
        draw.ellipse(
            [x + size * 0.34, body_y + body_h * 0.45, x + size * 0.34 + stick_r * 2, body_y + body_h * 0.45 + stick_r * 2],
            outline=color, width=2,
        )
        btn_r = size * 0.06
        for dx, dy in [(0.68, 0.2), (0.8, 0.32), (0.68, 0.44), (0.56, 0.32)]:
            bx = x + size * dx
            by = body_y + body_h * dy
            draw.ellipse([bx, by, bx + btn_r * 2, by + btn_r * 2], outline=color, width=1)

    def _draw_compat(self, canvas, draw, panel, x, y, w, h):
        if h <= 4 or w <= 4:
            return
        items = []
        if panel.show_compat:
            items.append(("badge", "Steam Deck", panel.steamdeck_rating))
            items.append(("badge", "Steam Machine", panel.steammachine_rating))
        if panel.input_kbm:
            items.append(("kbm", None, None))
        if panel.input_controller:
            items.append(("controller", None, None))
        if not items:
            return

        pad = max(3, round(w * 0.015))
        n = len(items)
        avail_w = max(1, w - pad * (n + 1))
        slot_w = max(1, avail_w // n)
        slot_h = max(1, h - pad * 2)

        cursor_x = x + pad
        for kind, label, value in items:
            if kind == "badge":
                self._draw_rating_badge(draw, cursor_x, y + pad, slot_w, slot_h, label, value)
            elif kind == "kbm":
                icon_size = min(slot_w, slot_h)
                self._draw_kbm_icon(draw, cursor_x + (slot_w - icon_size) / 2, y + pad + (slot_h - icon_size) / 2, icon_size)
            elif kind == "controller":
                icon_size = min(slot_w, slot_h)
                self._draw_controller_icon(
                    draw, cursor_x + (slot_w - icon_size) / 2, y + pad + (slot_h - icon_size) / 2, icon_size
                )
            cursor_x += slot_w + pad

    def _draw_logos(self, canvas, panel, x, y, w, h):
        if not panel.logos or h <= 4 or w <= 4:
            return
        pad = max(3, round(w * 0.015))
        n = len(panel.logos)
        avail_w = max(1, w - pad * (n + 1))
        slot_w = max(1, avail_w // n)
        max_logo_h = max(1, h - pad * 2)

        cursor_x = x + pad
        for logo in panel.logos:
            logo_copy = logo.convert("RGBA")
            logo_copy.thumbnail((slot_w, max_logo_h), Image.LANCZOS)
            paste_x = cursor_x + (slot_w - logo_copy.width) // 2
            paste_y = y + pad + (max_logo_h - logo_copy.height) // 2
            canvas.paste(logo_copy, (paste_x, paste_y), logo_copy)
            cursor_x += slot_w + pad

    def render_back_panel(self, panel: Panel, w_px: int, h_px: int) -> Image.Image:
        ratio = panel.art_ratio_frac()
        art_h = max(0, min(h_px, round(h_px * ratio)))
        lower_h = h_px - art_h

        canvas = Image.new("RGB", (w_px, h_px), "white")

        if panel.pil_image is not None and art_h > 0:
            art_img = self._render_source(
                panel.pil_image, panel.mode_var.get(), w_px, art_h, panel.center_x, panel.center_y
            )
            canvas.paste(art_img, (0, 0))

        has_compat = panel.show_compat or panel.input_kbm or panel.input_controller
        logos_h = min(lower_h, max(round(lower_h * 0.22), 0)) if panel.logos else 0
        compat_h = min(lower_h - logos_h, max(round(lower_h * 0.22), 0)) if has_compat else 0
        req_h = lower_h - logos_h - compat_h

        draw = ImageDraw.Draw(canvas)
        self._draw_requirements(draw, panel, 0, art_h, w_px, req_h)
        self._draw_compat(canvas, draw, panel, 0, art_h + req_h, w_px, compat_h)
        self._draw_logos(canvas, panel, 0, art_h + req_h + compat_h, w_px, logos_h)

        return canvas

    def _front_panel(self):
        return next((p for p in self.panels if p.is_front), None)

    def _banner_reserved_px(self, h_px: int) -> int:
        """Wie viele Pixel oben fuer das Banner freigehalten werden muessen,
        damit es das Artwork nicht ueberdeckt/abschneidet."""
        if self.banner_image is None:
            return 0
        banner_cm = self._banner_height_cm()
        height_cm = self._height_cm()
        if banner_cm <= 0 or height_cm <= 0:
            return 0
        ratio = min(0.9, banner_cm / height_cm)
        return round(h_px * ratio)

    def render_panel(self, panel: Panel, w_px: int, h_px: int) -> Image.Image:
        if panel.back_mode_var.get():
            return self.render_back_panel(panel, w_px, h_px)

        # Das Banner ueberlagert spaeter den oberen Rand dieses Panels ->
        # Artwork um die Bannerhoehe nach unten schieben, damit oben nichts
        # vom eigentlichen Bild verdeckt/abgeschnitten wird. Der sichtbare
        # Bildausschnitt kann weiterhin per Ziehen (center_x/center_y) im
        # verbleibenden Bereich verschoben werden.
        banner_h = self._banner_reserved_px(h_px)
        content_h = max(1, h_px - banner_h)

        front_panel = self._front_panel()
        if (
            panel.wrap_front_var.get()
            and front_panel is not None
            and front_panel is not panel
            and front_panel.pil_image is not None
            and not front_panel.back_mode_var.get()
        ):
            # Naeherung fuer Einzel-Thumbnails: eigener Ausschnitt des
            # Frontbilds. Im Gesamtcover wird stattdessen ein gemeinsamer,
            # nahtlos zusammenhaengender Ausschnitt verwendet (siehe unten).
            content = self._render_source(
                front_panel.pil_image, front_panel.mode_var.get(), w_px, content_h,
                front_panel.center_x, front_panel.center_y,
            )
        elif panel.pil_image is None:
            content = Image.new("RGB", (w_px, content_h), "white")
        else:
            content = self._render_source(
                panel.pil_image, panel.mode_var.get(), w_px, content_h, panel.center_x, panel.center_y
            )

        if banner_h <= 0:
            return content

        canvas = Image.new("RGB", (w_px, h_px), "white")
        if self.banner_image is not None:
            banner_preview = self._render_source(self.banner_image, MODE_STRETCH, w_px, banner_h)
            canvas.paste(banner_preview, (0, 0))
        canvas.paste(content, (0, banner_h))
        return canvas

    def build_combined_image(self):
        dpi = self._dpi()
        height_px = cm_to_px(self._height_cm(), dpi)
        widths_px = [cm_to_px(p.width_cm(), dpi) for p in self.panels]
        total_width_px = sum(widths_px)

        canvas = Image.new("RGB", (total_width_px, height_px), "white")

        # Panels, die "Frontbild fortsetzen" aktiviert haben und direkt neben
        # dem Front-Panel liegen, bekommen keinen eigenen Ausschnitt, sondern
        # ein Stueck eines gemeinsam berechneten, nahtlosen Ausschnitts - so
        # wirkt es wie ein umlaufendes (Wrap-)Cover statt zweier Einzelbilder.
        wrap_slices = {}
        wrap_image = None
        front_panel = self._front_panel()
        if front_panel is not None and front_panel.pil_image is not None and not front_panel.back_mode_var.get():
            front_idx = self.panels.index(front_panel)
            left_idx = front_idx - 1
            right_idx = front_idx + 1
            left_panel = self.panels[left_idx] if left_idx >= 0 else None
            right_panel = self.panels[right_idx] if right_idx < len(self.panels) else None
            left_wraps = bool(left_panel and left_panel.wrap_front_var.get() and not left_panel.back_mode_var.get())
            right_wraps = bool(right_panel and right_panel.wrap_front_var.get() and not right_panel.back_mode_var.get())
            if left_wraps or right_wraps:
                left_w = widths_px[left_idx] if left_wraps else 0
                right_w = widths_px[right_idx] if right_wraps else 0
                total_w = left_w + widths_px[front_idx] + right_w

                # Gleiche Banner-Reservierung wie in render_panel, aber auf
                # den gesamten Wrap-Ausschnitt angewendet, damit die Naht
                # zwischen den Panels weiterhin nahtlos bleibt.
                banner_h = self._banner_reserved_px(height_px)
                wrap_content_h = max(1, height_px - banner_h)
                wrap_content = self._render_source(
                    front_panel.pil_image, front_panel.mode_var.get(), total_w, wrap_content_h,
                    front_panel.center_x, front_panel.center_y,
                )
                if banner_h > 0:
                    wrap_image = Image.new("RGB", (total_w, height_px), "white")
                    if self.banner_image is not None:
                        banner_preview = self._render_source(self.banner_image, MODE_STRETCH, total_w, banner_h)
                        wrap_image.paste(banner_preview, (0, 0))
                    wrap_image.paste(wrap_content, (0, banner_h))
                else:
                    wrap_image = wrap_content

                if left_wraps:
                    wrap_slices[left_idx] = (0, left_w)
                wrap_slices[front_idx] = (left_w, widths_px[front_idx])
                if right_wraps:
                    wrap_slices[right_idx] = (left_w + widths_px[front_idx], right_w)

        x_offset = 0
        banner_segments = []
        for i, (panel, w_px) in enumerate(zip(self.panels, widths_px)):
            if wrap_image is not None and i in wrap_slices:
                sx, sw = wrap_slices[i]
                piece = wrap_image.crop((sx, 0, sx + sw, height_px))
            else:
                piece = self.render_panel(panel, w_px, height_px)
            canvas.paste(piece, (x_offset, 0))
            if not panel.back_mode_var.get():
                banner_segments.append((x_offset, w_px))
            x_offset += w_px

        if self.banner_image is not None:
            banner_h_px = cm_to_px(self._banner_height_cm(), dpi) if self._banner_height_cm() > 0 else 0
            total_banner_w = sum(w for _, w in banner_segments)
            if banner_h_px > 0 and total_banner_w > 0:
                banner_resized = self._render_source(self.banner_image, MODE_STRETCH, total_banner_w, banner_h_px)
                cursor = 0
                for seg_x, seg_w in banner_segments:
                    slice_img = banner_resized.crop((cursor, 0, cursor + seg_w, banner_h_px))
                    canvas.paste(slice_img, (seg_x, 0))
                    cursor += seg_w

        return canvas

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

            widths_px = [cm_to_px(p.width_cm(), dpi) for p in self.panels]
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
                    sum(p.width_cm() for p in self.panels),
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
    CoverMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
