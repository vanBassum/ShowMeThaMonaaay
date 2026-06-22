"""
read_inventory.py — Read an EFT gear screenshot end to end.

Combines the two identifiers:
  - TEXT: OCR the item names the game prints, match to the tarkov.dev DB.
  - ICON: flood each panel to isolate item blobs, perceptual-hash match each
          against the icon DB (catches items with no readable text).

  screenshot
    -> detect 3 panels (vertical low-density gaps)
    -> per panel: border flood -> foreground blobs (items)
    -> per blob: estimate footprint, icon-match
    -> OCR text -> name-match
    -> merge (dedupe overlapping), value, annotate

Outputs out/inventory.png + a priced list. Needs data/ built (build_hashes.py).

Usage:
  python read_inventory.py
  python read_inventory.py --icon-max 260   # icon-match distance cutoff
"""
import argparse
import os

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

import tarkov
import identify
from ocr import read_lines
from scan import is_noise
from flood_background import flood_background

PITCH = 84
WORK_Y = (150, 1090)   # gear-panel band (exclude top tabs + bottom quick-use)


def panel_bounds(rgb, n=3):
    """Split the work area into n panels at the widest interior low-density
    vertical gaps (the empty bands between panels)."""
    g = np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.float32)
    col = np.abs(np.diff(g, axis=1)).mean(axis=0)
    col = np.convolve(col, np.ones(21) / 21, mode="same")
    low = col < col.max() * 0.12
    # interior low-runs
    runs, s = [], None
    for x in range(len(low)):
        if low[x] and s is None:
            s = x
        elif not low[x] and s is not None:
            runs.append((s, x)); s = None
    runs = [(a, b) for (a, b) in runs if a > 5 and b < len(low) - 5]
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    seps = sorted((a + b) // 2 for (a, b) in runs[:n - 1])
    edges = [0] + seps + [rgb.shape[1]]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def blobs(crop, threshold=22):
    """Foreground (item) connected components within a panel crop, as
    (x, y, w, h) relative to the crop."""
    h, w, _ = crop.shape
    seeds = ([(x, 1) for x in range(0, w, 4)] + [(x, h - 2) for x in range(0, w, 4)]
             + [(1, y) for y in range(0, h, 4)] + [(w - 2, y) for y in range(0, h, 4)])
    bg = flood_background(crop, seeds, threshold, 4)
    fg = (~bg).astype(np.uint8) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    num, _, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    out = []
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if (bw >= PITCH * 0.5 and bh >= PITCH * 0.5 and area >= (PITCH * 0.5) ** 2
                and bw < w * 0.96 and bh < h * 0.96):
            out.append((int(x), int(y), int(bw), int(bh)))
    return out


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = min(ax + aw, bx + bw) - max(ax, bx)
    iy = min(ay + ah, by + bh) - max(ay, by)
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    return inter / min(aw * ah, bw * bh)


def load_font(size):
    for n in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="test screenshot 1.png")
    ap.add_argument("-o", "--output", default="out/inventory.png")
    ap.add_argument("--icon-max", type=float, default=110.0,
                    help="Max icon-match distance to accept a blob as an item. "
                         "Strict by default: only very confident icon matches "
                         "(catches icon-only items like grenades that OCR can't "
                         "read). Raise it to recover more, at the cost of false "
                         "positives (the grid icons don't match the gear-screen "
                         "renderings well past ~115).")
    ap.add_argument("--text-min", type=float, default=0.82,
                    help="Min OCR text match score.")
    ap.add_argument("--no-icons", action="store_true",
                    help="Disable the icon pass (text only).")
    args = ap.parse_args()

    matcher = tarkov.Matcher(tarkov.load())
    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    H, W, _ = rgb.shape

    found = []  # {source, name, short, price, box, score}
    y0w, y1w = WORK_Y

    # ---- TEXT pass (restricted to the gear-panel band: excludes the top tabs
    # and the bottom quick-use bar, which would double-count equipped items) ----
    for text, x, y, w, h in read_lines(img):
        if y < y0w or y > y1w or is_noise(text):
            continue
        item, score = matcher.match(text, threshold=args.text_min)
        if item:
            found.append({"src": "text", "name": item["name"],
                          "short": item["shortName"], "price": tarkov.best_price(item),
                          "box": (x, y, max(w, PITCH), max(h, PITCH)), "score": score})

    # ---- ICON pass (strict by default; catches icon-only items OCR misses) ----
    if not args.no_icons:
        for (px0, px1) in panel_bounds(rgb[y0w:y1w]):
            crop = rgb[y0w:y1w, px0:px1]
            for (bx, by, bw, bh) in blobs(crop):
                ax, ay = px0 + bx, y0w + by
                sub = Image.fromarray(rgb[ay:ay + bh, ax:ax + bw])
                fw, fh = max(1, round(bw / PITCH)), max(1, round(bh / PITCH))
                res = identify.identify(sub, fw, fh, topn=1)
                if res and res[0][0] <= args.icon_max:
                    dist, it = res[0]
                    found.append({"src": "icon", "name": it["name"],
                                  "short": it["shortName"],
                                  "price": tarkov.best_price(it),
                                  "box": (ax, ay, bw, bh), "score": dist})

    # ---- merge: drop icon hits that overlap a text hit (text wins) ----
    merged = []
    text_boxes = [f["box"] for f in found if f["src"] == "text"]
    for f in found:
        if f["src"] == "icon" and any(overlaps(f["box"], tb) > 0.3 for tb in text_boxes):
            continue
        merged.append(f)

    # ---- annotate ----
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    draw = ImageDraw.Draw(img)
    font = load_font(max(13, W // 110))
    for f in merged:
        x, y, w, h = f["box"]
        col = (0, 255, 0) if f["src"] == "text" else (255, 200, 0)
        draw.rectangle([x, y, x + w, y + h], outline=col, width=2)
        draw.text((x + 2, y + 2), f"{f['short']} {f['price']:,}", fill=col, font=font)
    img.save(args.output)

    merged.sort(key=lambda f: -f["price"])
    total = sum(f["price"] for f in merged)
    print(f"{'SRC':5}{'ITEM':40} {'CONF':>7} {'PRICE':>12}")
    print("-" * 70)
    for f in merged:
        conf = f"{f['score']:.2f}" if f["src"] == "text" else f"d{f['score']:.0f}"
        print(f"{f['src']:5}{f['name'][:40]:40} {conf:>7} {f['price']:>12,}")
    print("-" * 70)
    print(f"{len(merged)} items | total {total:,} RUB")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
