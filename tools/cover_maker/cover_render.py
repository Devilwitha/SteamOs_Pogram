"""Framework-unabhaengige Bildkomposition fuer Cover (reines PIL, kein
Tkinter). Enthaelt die komplette Rendering-Logik von cover_maker.py
(Panel-Zuschnitt, Banner, Rueckseite mit Systemanforderungen/Kompatibilitaets-
Badges/Eingabegeraete-Icons/Firmenlogos, Gesamtkomposition).

cover_maker.py (Desktop-GUI) und tools/cover_maker/server/ (Web-Variante)
nutzen beide ausschliesslich diese Funktionen, damit ein Cover in beiden
Varianten exakt dasselbe Ergebnisbild erzeugt - keine zweite, potenziell
abweichende Implementierung.

Erwartet fuer alle "panel"-Parameter unten ein Objekt (egal ob Tkinter-
gebundene Panel-Instanz mit duenner Property-Fassade oder eine reine
Datenklasse) mit den Attributen:
    pil_image, mode, center_x, center_y, width_cm, is_front, is_back,
    wrap_front, art_ratio_percent, min_title, rec_title,
    min_text_content, rec_text_content, logos (Liste PIL.Image),
    show_compat, steamdeck_rating, steammachine_rating,
    input_kbm, input_controller
"""
from PIL import Image, ImageDraw, ImageFont, ImageOps

MODE_CROP = "Zuschneiden (Ausschnitt waehlen)"
MODE_STRETCH = "Fuellen (Groesse anpassen)"
MODE_CONTAIN = "Einpassen (mit Rand)"
FIT_MODES = [MODE_CROP, MODE_STRETCH, MODE_CONTAIN]

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

_FONT_CACHE = {}


def cm_to_px(cm: float, dpi: int) -> int:
    return max(1, round(cm / 2.54 * dpi))


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


def fit_source(src_image, mode, w_px, h_px, center_x=0.5, center_y=0.5):
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


def fit_font(draw, text, bold, max_size, max_width):
    size = max_size
    while size > 6:
        font = load_font(bold, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 1
    return load_font(bold, 6)


def draw_requirements(draw, panel, x, y, w, h):
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


def draw_rating_badge(draw, cx, cy, w, h, label, rating):
    if w <= 4 or h <= 4:
        return
    color = RATING_COLORS.get(rating, RATING_COLORS["Nicht bewertet"])
    radius = max(3, round(h * 0.18))
    draw.rounded_rectangle([cx, cy, cx + w, cy + h], radius=radius, fill=color)

    pad = max(2, round(h * 0.08))
    avail_text_w = max(4, w - pad * 2)
    label_size = max(7, round(h * 0.32))
    value_size = max(6, round(h * 0.26))
    font_label = fit_font(draw, label, True, label_size, avail_text_w)
    font_value = fit_font(draw, rating, False, value_size, avail_text_w)

    label_h = font_label.getbbox(label)[3] - font_label.getbbox(label)[1] if hasattr(font_label, "getbbox") else label_size
    draw.text((cx + pad, cy + pad), label, font=font_label, fill="white")
    draw.text((cx + pad, cy + pad + label_h + max(1, round(h * 0.04))), rating, font=font_value, fill="white")


def draw_kbm_icon(draw, x, y, size, color="#333333"):
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


def draw_controller_icon(draw, x, y, size, color="#333333"):
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


def draw_compat(canvas, draw, panel, x, y, w, h):
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
            draw_rating_badge(draw, cursor_x, y + pad, slot_w, slot_h, label, value)
        elif kind == "kbm":
            icon_size = min(slot_w, slot_h)
            draw_kbm_icon(draw, cursor_x + (slot_w - icon_size) / 2, y + pad + (slot_h - icon_size) / 2, icon_size)
        elif kind == "controller":
            icon_size = min(slot_w, slot_h)
            draw_controller_icon(
                draw, cursor_x + (slot_w - icon_size) / 2, y + pad + (slot_h - icon_size) / 2, icon_size
            )
        cursor_x += slot_w + pad


def draw_logos(canvas, panel, x, y, w, h):
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


def art_ratio_frac(panel) -> float:
    return max(0.01, min(0.99, panel.art_ratio_percent / 100.0))


def render_back_panel(panel, w_px: int, h_px: int) -> Image.Image:
    ratio = art_ratio_frac(panel)
    art_h = max(0, min(h_px, round(h_px * ratio)))
    lower_h = h_px - art_h

    canvas = Image.new("RGB", (w_px, h_px), "white")

    if panel.pil_image is not None and art_h > 0:
        art_img = fit_source(panel.pil_image, panel.mode, w_px, art_h, panel.center_x, panel.center_y)
        canvas.paste(art_img, (0, 0))

    has_compat = panel.show_compat or panel.input_kbm or panel.input_controller
    logos_h = min(lower_h, max(round(lower_h * 0.22), 0)) if panel.logos else 0
    compat_h = min(lower_h - logos_h, max(round(lower_h * 0.22), 0)) if has_compat else 0
    req_h = lower_h - logos_h - compat_h

    draw = ImageDraw.Draw(canvas)
    draw_requirements(draw, panel, 0, art_h, w_px, req_h)
    draw_compat(canvas, draw, panel, 0, art_h + req_h, w_px, compat_h)
    draw_logos(canvas, panel, 0, art_h + req_h + compat_h, w_px, logos_h)

    return canvas


def banner_reserved_px(banner_image, banner_height_cm, height_cm, h_px: int) -> int:
    """Wie viele Pixel oben fuer das Banner freigehalten werden muessen,
    damit es das Artwork nicht ueberdeckt/abschneidet."""
    if banner_image is None or banner_height_cm <= 0 or height_cm <= 0:
        return 0
    ratio = min(0.9, banner_height_cm / height_cm)
    return round(h_px * ratio)


def render_panel(panel, w_px: int, h_px: int, *, panels, banner_image, banner_height_cm, height_cm) -> Image.Image:
    if panel.is_back:
        return render_back_panel(panel, w_px, h_px)

    banner_h = banner_reserved_px(banner_image, banner_height_cm, height_cm, h_px)
    content_h = max(1, h_px - banner_h)

    front_panel = next((p for p in panels if p.is_front), None)
    if (
        panel.wrap_front
        and front_panel is not None
        and front_panel is not panel
        and front_panel.pil_image is not None
        and not front_panel.is_back
    ):
        # Naeherung fuer Einzel-Thumbnails: eigener Ausschnitt des
        # Frontbilds. Im Gesamtcover wird stattdessen ein gemeinsamer,
        # nahtlos zusammenhaengender Ausschnitt verwendet (siehe unten).
        content = fit_source(
            front_panel.pil_image, front_panel.mode, w_px, content_h, front_panel.center_x, front_panel.center_y
        )
    elif panel.pil_image is None:
        content = Image.new("RGB", (w_px, content_h), "white")
    else:
        content = fit_source(panel.pil_image, panel.mode, w_px, content_h, panel.center_x, panel.center_y)

    if banner_h <= 0:
        return content

    canvas = Image.new("RGB", (w_px, h_px), "white")
    if banner_image is not None:
        banner_preview = fit_source(banner_image, MODE_STRETCH, w_px, banner_h)
        canvas.paste(banner_preview, (0, 0))
    canvas.paste(content, (0, banner_h))
    return canvas


def build_combined_image(panels, height_cm, dpi, banner_image, banner_height_cm) -> Image.Image:
    height_px = cm_to_px(height_cm, dpi)
    widths_px = [cm_to_px(p.width_cm, dpi) for p in panels]
    total_width_px = sum(widths_px)

    canvas = Image.new("RGB", (total_width_px, height_px), "white")

    # Panels, die "Frontbild fortsetzen" aktiviert haben und direkt neben
    # dem Front-Panel liegen, bekommen keinen eigenen Ausschnitt, sondern
    # ein Stueck eines gemeinsam berechneten, nahtlosen Ausschnitts - so
    # wirkt es wie ein umlaufendes (Wrap-)Cover statt zweier Einzelbilder.
    wrap_slices = {}
    wrap_image = None
    front_panel = next((p for p in panels if p.is_front), None)
    if front_panel is not None and front_panel.pil_image is not None and not front_panel.is_back:
        front_idx = panels.index(front_panel)
        left_idx = front_idx - 1
        right_idx = front_idx + 1
        left_panel = panels[left_idx] if left_idx >= 0 else None
        right_panel = panels[right_idx] if right_idx < len(panels) else None
        left_wraps = bool(left_panel and left_panel.wrap_front and not left_panel.is_back)
        right_wraps = bool(right_panel and right_panel.wrap_front and not right_panel.is_back)
        if left_wraps or right_wraps:
            left_w = widths_px[left_idx] if left_wraps else 0
            right_w = widths_px[right_idx] if right_wraps else 0
            total_w = left_w + widths_px[front_idx] + right_w

            # Gleiche Banner-Reservierung wie in render_panel, aber auf
            # den gesamten Wrap-Ausschnitt angewendet, damit die Naht
            # zwischen den Panels weiterhin nahtlos bleibt.
            banner_h = banner_reserved_px(banner_image, banner_height_cm, height_cm, height_px)
            wrap_content_h = max(1, height_px - banner_h)
            wrap_content = fit_source(
                front_panel.pil_image, front_panel.mode, total_w, wrap_content_h,
                front_panel.center_x, front_panel.center_y,
            )
            if banner_h > 0:
                wrap_image = Image.new("RGB", (total_w, height_px), "white")
                if banner_image is not None:
                    banner_preview = fit_source(banner_image, MODE_STRETCH, total_w, banner_h)
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
    for i, (panel, w_px) in enumerate(zip(panels, widths_px)):
        if wrap_image is not None and i in wrap_slices:
            sx, sw = wrap_slices[i]
            piece = wrap_image.crop((sx, 0, sx + sw, height_px))
        else:
            piece = render_panel(
                panel, w_px, height_px, panels=panels,
                banner_image=banner_image, banner_height_cm=banner_height_cm, height_cm=height_cm,
            )
        canvas.paste(piece, (x_offset, 0))
        if not panel.is_back:
            banner_segments.append((x_offset, w_px))
        x_offset += w_px

    if banner_image is not None:
        banner_h_px = cm_to_px(banner_height_cm, dpi) if banner_height_cm > 0 else 0
        total_banner_w = sum(w for _, w in banner_segments)
        if banner_h_px > 0 and total_banner_w > 0:
            banner_resized = fit_source(banner_image, MODE_STRETCH, total_banner_w, banner_h_px)
            cursor = 0
            for seg_x, seg_w in banner_segments:
                slice_img = banner_resized.crop((cursor, 0, cursor + seg_w, banner_h_px))
                canvas.paste(slice_img, (seg_x, 0))
                cursor += seg_w

    return canvas
