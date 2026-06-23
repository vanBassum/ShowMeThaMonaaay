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


def font(sz):
    for n in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(n, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def cell_bg(w, h, rarity="common"):
    """Dark cell with a subtle top-left lit gradient + rarity tint."""
    base = np.array(RARITY.get(rarity, RARITY["common"]), np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = 1.0 - 0.35 * ((xx / w + yy / h) / 2.0)        # lighter top-left
    arr = (base[None, None, :] * g[..., None]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0, 120), width=1)
    return img


def place(icon, w, h, rarity="common", pad=0.06):
    """Composite the icon over a cell background, padded like the game."""
    bg = cell_bg(w, h, rarity)
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


# ---- GUESSES — calibrate against a real crop ----
def add_fir(img):
    """GUESS: Found-in-Raid marker (small mark, top-right)."""
    d = ImageDraw.Draw(img); s = max(10, img.width // 8)
    d.ellipse([img.width - s - 3, 3, img.width - 3, 3 + s], fill=(70, 170, 90, 235))
    d.text((img.width - s + 1, 2), "✓", font=font(s), fill=(255, 255, 255, 255))
    return img


def add_highlight(img, color=(255, 210, 60)):
    """GUESS: search / pinned highlight (glow border + tint)."""
    d = ImageDraw.Draw(img)
    for i, a in enumerate((90, 150, 220)):
        d.rectangle([i, i, img.width - 1 - i, img.height - 1 - i], outline=color + (a,), width=1)
    return img


def contact_sheet(icon, short):
    variants = [
        ("clean icon", place(icon, CELL, CELL)),
        ("+ count", add_count(place(icon, CELL, CELL), 42)),
        ("+ durability", add_durability(place(icon, CELL, CELL))),
        ("+ name", add_name(place(icon, CELL, CELL), short)),
        ("rare tint", place(icon, CELL, CELL, "rare")),
        ("FiR (GUESS)", add_fir(place(icon, CELL, CELL))),
        ("highlight (GUESS)", add_highlight(place(icon, CELL, CELL))),
        ("combined", add_highlight(add_count(add_name(place(icon, CELL, CELL, "rare"), short), 42))),
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
    print(f"-> {args.out}  ({it.get('shortName')})  [FiR + highlight are GUESSES]")


if __name__ == "__main__":
    main()
