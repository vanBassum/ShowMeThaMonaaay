"""
variants.py — Render in-game appearance VARIANTS of a clean grid icon, so the
generator can teach the detector/identifier what the game actually draws (not
just the bare icon). Overlays are parameterised and composited onto any icon.

Confident overlays (well-documented EFT UI):
  - cell background + rarity tint
  - stack/count number (bottom-right)
  - durability / resource bar
  - name strip (top)
GUESSES pending a real reference crop (calibrate these against a screenshot):
  - Found-in-Raid marker
  - search / pinned highlight

Usage:
  python variants.py --id 5448be9a4bdc2dfd2f8b456a    # contact sheet -> out/_variants.png
  python variants.py --id <id> --compare crop.png     # my render beside a real crop
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")
CELL = 128

RARITY = {  # cell background tints (approx EFT)
    "common": (62, 62, 62), "rare": (40, 53, 78), "epic": (60, 44, 78),
    "legendary": (78, 64, 40),
}
HIGHLIGHT_BG = (120, 104, 74)   # warm tan cell when pinned/search-highlighted (calibrated vs manuel/)


def font(sz):
    for n in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(n, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def cell_bg(w, h, rarity="common", highlight=False):
    """Cell with a subtle top-left lit gradient. Search/pinned highlight repaints
    the cell a warm tan and adds a lighter border (per manuel/ references)."""
    base = np.array(HIGHLIGHT_BG if highlight else RARITY.get(rarity, RARITY["common"]), np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = 1.0 - 0.35 * ((xx / w + yy / h) / 2.0)        # lighter top-left
    arr = (base[None, None, :] * g[..., None]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    d = ImageDraw.Draw(img)
    edge = (165, 150, 110, 200) if highlight else (0, 0, 0, 120)
    d.rectangle([0, 0, w - 1, h - 1], outline=edge, width=1)
    return img


def place(icon, w, h, rarity="common", pad=0.06, highlight=False, rotate=False):
    """Composite the icon over a cell background, padded like the game. rotate=
    True rotates the icon 90 deg (an item turned in the grid)."""
    if rotate:
        icon = icon.rotate(90, expand=True)
    bg = cell_bg(w, h, rarity, highlight)
    iw, ih = int(w * (1 - 2 * pad)), int(h * (1 - 2 * pad))
    ic = icon.convert("RGBA").resize((iw, ih))
    bg.alpha_composite(ic, ((w - iw) // 2, (h - ih) // 2))
    return bg


def add_count(img, n):
    d = ImageDraw.Draw(img); f = font(max(11, img.height // 7))
    t = str(n); tw = d.textlength(t, font=f)
    d.text((img.width - tw - 3, img.height - f.size - 2), t, font=f, fill=(230, 230, 220, 255))
    return img


def add_durability(img, frac=0.6, color=(120, 200, 120)):
    d = ImageDraw.Draw(img); bw = max(3, img.width // 26)
    d.rectangle([2, 2, 2 + bw, 2 + int((img.height - 4) * frac)], fill=color + (235,))
    return img


def add_name(img, text):
    d = ImageDraw.Draw(img); f = font(max(10, img.height // 11))
    bar = Image.new("RGBA", (img.width, f.size + 4), (8, 8, 8, 150))
    img.alpha_composite(bar, (0, 0))
    d.text((3, 1), text[:max(1, img.width // 7)], font=f, fill=(205, 205, 195, 255))
    return img


def add_fir(img):
    """Found-in-Raid: a small light-gray check mark in the BOTTOM-RIGHT corner
    (calibrated vs manuel/ GPhone, MTape, cord)."""
    d = ImageDraw.Draw(img); s = max(9, img.width // 8); m = max(2, img.width // 40)
    x, y = img.width - m, img.height - m
    d.line([(x - s, y - s * 0.45), (x - s * 0.55, y), (x, y - s)],
           fill=(225, 225, 215, 240), width=max(2, img.width // 55))
    return img


SEARCH_GLYPHS = ("circle", "square", "triangle", "bars")


def add_search_icon(img, kind="circle"):
    """Search-category badge in the BOTTOM-LEFT, shown during a category search
    (the glyph differs per category — generic placeholders here). Per manuel/
    MTape, Toolset, cord."""
    s = max(12, img.width // 6); m = max(2, img.width // 40)
    x0, y0, x1, y1 = m, img.height - s - m, m + s, img.height - m
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x1, y1], radius=s // 5, fill=(18, 18, 20, 185))
    cx, cy, r, col = (x0 + x1) // 2, (y0 + y1) // 2, s // 3, (205, 205, 210, 240)
    if kind == "circle":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=2)
    elif kind == "square":
        d.rectangle([cx - r, cy - r, cx + r, cy + r], outline=col, width=2)
    elif kind == "triangle":
        d.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], outline=col)
    else:
        for k in range(3):
            yy = cy - r + k * r
            d.line([(cx - r, yy), (cx + r, yy)], fill=col, width=2)
    return img


def contact_sheet(icon, short):
    variants = [
        ("clean icon", place(icon, CELL, CELL)),
        ("+ count", add_count(place(icon, CELL, CELL), 42)),
        ("+ durability", add_durability(place(icon, CELL, CELL))),
        ("+ name", add_name(place(icon, CELL, CELL), short)),
        ("rare tint", place(icon, CELL, CELL, "rare")),
        ("found-in-raid", add_fir(place(icon, CELL, CELL))),
        ("rotated 90", place(icon, CELL, CELL, rotate=True)),
        ("highlight", place(icon, CELL, CELL, highlight=True)),
        ("hl + search o", add_search_icon(place(icon, CELL, CELL, highlight=True), "circle")),
        ("hl + search []", add_search_icon(place(icon, CELL, CELL, highlight=True), "square")),
        ("hl + FiR + search", add_fir(add_search_icon(place(icon, CELL, CELL, highlight=True), "triangle"))),
        ("combined", add_fir(add_search_icon(add_count(add_name(place(icon, CELL, CELL, highlight=True), short), 42), "bars"))),
    ]
    cols = 4
    rows = (len(variants) + cols - 1) // cols
    pad, lab = 14, 18
    sheet = Image.new("RGB", (cols * (CELL + pad) + pad, rows * (CELL + lab + pad) + pad), (24, 26, 30))
    d = ImageDraw.Draw(sheet); f = font(13)
    for i, (name, im) in enumerate(variants):
        cx = pad + (i % cols) * (CELL + pad)
        cy = pad + (i // cols) * (CELL + lab + pad)
        sheet.paste(im.convert("RGB"), (cx, cy))
        d.text((cx, cy + CELL + 2), name, font=f, fill=(200, 205, 210))
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="5448be9a4bdc2dfd2f8b456a")  # RGD-5 grenade
    ap.add_argument("--compare", help="real crop to show beside the rendered variants")
    ap.add_argument("-o", "--out", default="out/_variants.png")
    args = ap.parse_args()

    items = {it["id"]: it for it in json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))}
    it = items.get(args.id)
    p = os.path.join(ICONS, args.id + ".webp")
    if not it or not os.path.exists(p):
        print("no such icon:", args.id); return
    icon = Image.open(p).convert("RGBA")
    sheet = contact_sheet(icon, it.get("shortName", "?"))
    if args.compare and os.path.exists(args.compare):
        real = Image.open(args.compare).convert("RGB").resize((CELL, CELL))
        combo = Image.new("RGB", (sheet.width, sheet.height + CELL + 30), (24, 26, 30))
        combo.paste(sheet, (0, 0)); combo.paste(real, (14, sheet.height + 10))
        ImageDraw.Draw(combo).text((14 + CELL + 10, sheet.height + 10), "<- REAL crop (target)",
                                   font=font(14), fill=(255, 210, 60))
        sheet = combo
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    sheet.save(args.out)
    print(f"-> {args.out}  ({it.get('shortName')})  "
          f"[FiR/highlight/search calibrated vs manuel/; exact category glyphs are placeholders]")


if __name__ == "__main__":
    main()
