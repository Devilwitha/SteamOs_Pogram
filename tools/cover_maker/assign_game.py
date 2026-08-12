"""
Ordnet ein mit cover_maker.py erstelltes Cover einem Spiel aus games.db zu.

Start: python assign_game.py [--cover-id N]
Wird auch automatisch von cover_maker.py ueber den Button
"Spiel zuweisen..." mit dem zuletzt gespeicherten Cover geoeffnet.
"""

import argparse
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
COVERS_DB = SCRIPT_DIR / "covers.db"
GAMES_DB = SCRIPT_DIR.parent.parent / "steamOs" / "games.db"

PREVIEW_MAX = 240


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
    conn.commit()


class AssignGameApp:
    def __init__(self, root, preselect_cover_id=None):
        self.root = root
        root.title("Cover einem Spiel zuweisen")
        root.geometry("820x480")

        self._preview_photo = None
        self.covers = []
        self.games = []
        self._visible_games = []

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True, padx=10, pady=10)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(2, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="Gespeicherte Cover").grid(row=0, column=0, sticky="w")
        self.cover_list = tk.Listbox(main, exportselection=False)
        self.cover_list.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.cover_list.bind("<<ListboxSelect>>", lambda *_: self.on_cover_select())

        preview_frame = ttk.Frame(main)
        preview_frame.grid(row=0, column=1, rowspan=2, padx=10)
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack()
        self.assigned_label = ttk.Label(preview_frame, text="", wraplength=200, justify="center")
        self.assigned_label.pack(pady=(10, 0))

        right = ttk.Frame(main)
        right.grid(row=0, column=2, rowspan=2, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Spiel suchen").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.search_var).grid(row=0, column=0, sticky="e")
        self.search_var.trace_add("write", lambda *_: self.refresh_game_list())

        self.game_list = tk.Listbox(right, exportselection=False)
        self.game_list.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        button_row = ttk.Frame(root)
        button_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(button_row, text="Zuweisen", command=self.assign_selected).pack(side="left")
        ttk.Button(button_row, text="Zuweisung entfernen", command=self.remove_assignment).pack(
            side="left", padx=10
        )

        self.load_games()
        self.load_covers(preselect_cover_id)

    # -- Daten laden ----------------------------------------------------
    def load_games(self):
        self.games = []
        if not GAMES_DB.exists():
            messagebox.showwarning(
                "games.db nicht gefunden",
                f"Spieledatenbank wurde nicht gefunden:\n{GAMES_DB}\n"
                "Bitte zuerst game_scanner.py ausfuehren.",
            )
        else:
            conn = sqlite3.connect(GAMES_DB)
            try:
                self.games = conn.execute(
                    "SELECT uid, appid, name FROM games ORDER BY name COLLATE NOCASE"
                ).fetchall()
            finally:
                conn.close()
        self.refresh_game_list()

    def refresh_game_list(self):
        query = self.search_var.get().strip().lower()
        self._visible_games = [g for g in self.games if query in g[2].lower()] if query else list(self.games)
        self.game_list.delete(0, "end")
        for _uid, _appid, name in self._visible_games:
            self.game_list.insert("end", name)

    def load_covers(self, preselect_cover_id):
        conn = sqlite3.connect(COVERS_DB)
        try:
            ensure_covers_db(conn)
            self.covers = conn.execute(
                "SELECT id, file_path, game_name, created_at FROM covers ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()

        self.cover_list.delete(0, "end")
        select_index = 0
        for i, (cid, file_path, game_name, _created_at) in enumerate(self.covers):
            label = f"#{cid} - {Path(file_path).name}"
            if game_name:
                label += f"  -> {game_name}"
            self.cover_list.insert("end", label)
            if preselect_cover_id is not None and cid == preselect_cover_id:
                select_index = i

        if self.covers:
            self.cover_list.selection_clear(0, "end")
            self.cover_list.selection_set(select_index)
            self.cover_list.see(select_index)
            self.on_cover_select()
        else:
            self.preview_label.configure(image="")
            self.assigned_label.configure(text="Noch keine Cover gespeichert.")

    # -- Auswahl ----------------------------------------------------
    def selected_cover(self):
        sel = self.cover_list.curselection()
        if not sel:
            return None
        return self.covers[sel[0]]

    def on_cover_select(self):
        cover = self.selected_cover()
        if not cover:
            return
        _cid, file_path, game_name, _created_at = cover
        try:
            image = Image.open(file_path)
            image.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self._preview_photo)
        except Exception:
            self.preview_label.configure(image="")
        self.assigned_label.configure(
            text=f"Aktuell zugewiesen: {game_name}" if game_name else "Noch keinem Spiel zugewiesen"
        )

    # -- Aktionen ----------------------------------------------------
    def assign_selected(self):
        cover = self.selected_cover()
        if not cover:
            messagebox.showinfo("Hinweis", "Bitte ein Cover auswaehlen.")
            return
        game_sel = self.game_list.curselection()
        if not game_sel:
            messagebox.showinfo("Hinweis", "Bitte ein Spiel auswaehlen.")
            return

        uid, appid, name = self._visible_games[game_sel[0]]
        cid = cover[0]

        conn = sqlite3.connect(COVERS_DB)
        try:
            ensure_covers_db(conn)
            conn.execute(
                "UPDATE covers SET game_uid=?, game_name=?, game_appid=? WHERE id=?",
                (uid, name, appid, cid),
            )
            conn.commit()
        finally:
            conn.close()

        messagebox.showinfo("Zugewiesen", f"Cover #{cid} wurde '{name}' zugewiesen.")
        self.load_covers(cid)

    def remove_assignment(self):
        cover = self.selected_cover()
        if not cover:
            return
        cid = cover[0]

        conn = sqlite3.connect(COVERS_DB)
        try:
            ensure_covers_db(conn)
            conn.execute(
                "UPDATE covers SET game_uid=NULL, game_name=NULL, game_appid=NULL WHERE id=?",
                (cid,),
            )
            conn.commit()
        finally:
            conn.close()

        self.load_covers(cid)


def main():
    parser = argparse.ArgumentParser(description="Cover einem Spiel zuweisen")
    parser.add_argument("--cover-id", type=int, default=None)
    args = parser.parse_args()

    root = tk.Tk()
    AssignGameApp(root, preselect_cover_id=args.cover_id)
    root.mainloop()


if __name__ == "__main__":
    main()
