#!/usr/bin/env python3
"""Erzeugt ein 600x900-Grid-Bild fuer den Steam-Bibliothekseintrag des
Controller-Einstellungsmenues (siehe launch_dashboard.py) - dieselbe
Aufloesung, die Steam fuer normale Spiele-Cover verwendet (siehe
game_scanner._LIBRARY_IMAGE_NAMES: 'library_600x900.jpg'), damit sich der
Eintrag optisch nahtlos zwischen die echten Spiele einreiht.

Nur zum einmaligen (Neu-)Erzeugen von dashboard_grid.png gedacht - fuer den
laufenden Betrieb wird ausschliesslich die fertige PNG-Datei gebraucht.
Braucht Pillow (bereits optionale Abhaengigkeit fuer die automatische
Cover-Farbermittlung, siehe game_scanner.py).

Start: python3 make_grid_art.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path(__file__).resolve().parent / "dashboard_grid.png"
WIDTH, HEIGHT = 600, 900

BG = (8, 11, 16)
PANEL = (17, 21, 29)
BORDER = (35, 44, 61)
CYAN = (0, 229, 255)
CYAN_DIM = (8, 145, 168)
MAGENTA = (255, 46, 151)
TEXT = (232, 237, 245)
DIM = (118, 134, 160)

_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _centered_text(draw, cx, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def main():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Dezente HUD-Rasterlinien, wie im CSS-Hintergrund des Dashboards.
    for x in range(0, WIDTH, 26):
        draw.line([(x, 0), (x, HEIGHT)], fill=(255, 255, 255, 6))
    for y in range(0, HEIGHT, 26):
        draw.line([(0, y), (WIDTH, y)], fill=(255, 255, 255, 6))

    # Radiale Akzente (grob nachgebildet - PIL kennt keine CSS-Gradients).
    accent = Image.new("RGB", (WIDTH, HEIGHT), BG)
    accent_draw = ImageDraw.Draw(accent)
    accent_draw.ellipse([-260, -420, 460, 260], fill=(20, 45, 55))
    accent_draw.ellipse([300, 640, 900, 1180], fill=(50, 20, 45))
    img = Image.blend(img, accent, 0.35)
    draw = ImageDraw.Draw(img)

    # Zentrale Panel-Karte im HUD-Stil.
    panel_box = [70, 300, WIDTH - 70, 620]
    draw.rectangle(panel_box, fill=PANEL, outline=BORDER, width=2)
    draw.rectangle([panel_box[0], panel_box[1], panel_box[2], panel_box[1] + 4], fill=CYAN)

    title_font = _font(58)
    sub_font = _font(30)
    small_font = _font(22)

    _centered_text(draw, WIDTH / 2, 350, "STEAMOS", title_font, TEXT)
    _centered_text(draw, WIDTH / 2, 420, "KONSOLE", title_font, CYAN)
    _centered_text(draw, WIDTH / 2, 500, "⚙  EINSTELLUNGEN  ⚙", sub_font, MAGENTA)
    _centered_text(draw, WIDTH / 2, 555, "LEDs · Sound · Tags · Spiele", small_font, DIM)

    # Duenner Rahmen aussen, passend zur Cyan-Akzentfarbe der GUI.
    draw.rectangle([4, 4, WIDTH - 5, HEIGHT - 5], outline=CYAN_DIM, width=3)

    img.save(OUT_PATH)
    print(f"Geschrieben: {OUT_PATH}")


if __name__ == "__main__":
    main()
