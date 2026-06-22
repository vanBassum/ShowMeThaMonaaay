"""
Generate a synthetic, auto-labelled detection dataset for a single-class
"item" YOLO detector.

Idea (cut-paste augmentation): we own ~5000 real item grid-icons. Paste them
into procedurally-drawn inventory panels (dark translucent grids + equipment
slots) at the SAME pixel scale the game uses (~84 px/cell @ 2560x1440), add
the name/count overlays the game prints, and record each item's box. Many
cells are left empty so the detector learns "empty cell != item".

Output (YOLO format):
  data/yolo/images/{train,val}/*.jpg
  data/yolo/labels/{train,val}/*.txt     # class cx cy w h  (normalized)
  data/yolo/data.yaml

Run:  python gen_synth.py --n 600 --val 100
"""
import os
import sys
import json
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")
ROOT = os.path.join(DATA, "yolo")
TILE = 640                      # training tile size
CELL_RANGE = (80, 90)           # real cell pitch @ 2560x1440 is ~84

_FONT = None


def font():
    global _FONT
    if _FONT is None:
        try:
            _FONT = ImageFont.truetype("arial.ttf", 11)
        except Exception:
            _FONT = ImageFont.load_default()
    return _FONT


def load_items():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    out = []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if it.get("gridImageLink") and os.path.exists(p):
            out.append((p, it["width"], it["height"], it.get("shortName", "")))
    return out


def background(rng):
    """A dark, faintly textured canvas with occasional blurred bright blobs,
    mimicking the blurred game world behind translucent inventory panels."""
    base = rng.integers(14, 38)
    arr = np.full((TILE, TILE, 3), base, np.uint8)
    arr = arr + rng.integers(-6, 7, (TILE, TILE, 3))
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    for _ in range(rng.integers(0, 3)):
        blob = Image.new("RGB", (TILE, TILE), (0, 0, 0))
        d = ImageDraw.Draw(blob)
        cx, cy = rng.integers(0, TILE), rng.integers(0, TILE)
        r = rng.integers(60, 220)
        col = tuple(int(v) for v in rng.integers(40, 130, 3))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        img = Image.blend(img, blob.filter(ImageFilter.GaussianBlur(60)), 0.35)
    return img


def draw_panel(img, x0, y0, cols, rows, cell):
    """Draw a translucent dark grid panel; return its cell origin + size."""
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    w, h = cols * cell, rows * cell
    d.rectangle([x0, y0, x0 + w, y0 + h], fill=(20, 22, 24, 180))
    line = (70, 74, 78, 160)
    for c in range(cols + 1):
        d.line([x0 + c * cell, y0, x0 + c * cell, y0 + h], fill=line, width=1)
    for r in range(rows + 1):
        d.line([x0, y0 + r * cell, x0 + w, y0 + r * cell], fill=line, width=1)
    img.alpha_composite(over)
    return x0, y0, cols, rows


def paste_item(img, icon_path, w_cells, h_cells, x, y, cell, rng, label=""):
    """Paste an item icon scaled to its cell footprint at (x,y). Adds the game's
    name bar + count overlay sometimes. Returns the pixel bbox (x0,y0,x1,y1)."""
    pw, ph = w_cells * cell, h_cells * cell
    ic = Image.open(icon_path).convert("RGBA").resize((pw, ph))
    img.alpha_composite(ic, (x, y))
    d = ImageDraw.Draw(img)
    if rng.random() < 0.7 and label:      # name bar (top), as the game prints
        bar = Image.new("RGBA", (pw, 14), (10, 10, 10, 150))
        img.alpha_composite(bar, (x, y))
        d.text((x + 2, y + 1), label[:int(pw / 6)], font=font(), fill=(210, 210, 200, 255))
    if rng.random() < 0.5:                # count / durability (bottom-right)
        d.text((x + pw - 16, y + ph - 14), str(rng.integers(1, 60)),
               font=font(), fill=(220, 210, 120, 255))
    return (x, y, x + pw, y + ph)


def gen_image(items, rng):
    img = background(rng).convert("RGBA")
    boxes = []
    cell = int(rng.integers(*CELL_RANGE))
    # 1-3 grid panels
    for _ in range(rng.integers(1, 4)):
        cols = int(rng.integers(2, max(3, TILE // cell)))
        rows = int(rng.integers(2, max(3, TILE // cell)))
        x0 = int(rng.integers(0, max(1, TILE - cols * cell)))
        y0 = int(rng.integers(0, max(1, TILE - rows * cell)))
        if x0 + cols * cell > TILE or y0 + rows * cell > TILE:
            continue
        draw_panel(img, x0, y0, cols, rows, cell)
        occ = np.zeros((rows, cols), bool)
        # fill a random fraction of the panel with items
        attempts = int(cols * rows * rng.uniform(0.4, 0.95))
        for _ in range(attempts):
            p, iw, ih, sn = items[rng.integers(0, len(items))]
            if iw > cols or ih > rows:
                continue
            c = int(rng.integers(0, cols - iw + 1))
            r = int(rng.integers(0, rows - ih + 1))
            if occ[r:r + ih, c:c + iw].any():
                continue
            occ[r:r + ih, c:c + iw] = True
            bb = paste_item(img, p, iw, ih, x0 + c * cell, y0 + r * cell, cell, rng, sn)
            boxes.append(bb)
    # a couple of free-floating "equipment slot" items (no grid)
    for _ in range(rng.integers(0, 3)):
        p, iw, ih, sn = items[rng.integers(0, len(items))]
        pw, ph = iw * cell, ih * cell
        if pw >= TILE or ph >= TILE:
            continue
        x = int(rng.integers(0, TILE - pw))
        y = int(rng.integers(0, TILE - ph))
        bb = paste_item(img, p, iw, ih, x, y, cell, rng, sn)
        boxes.append(bb)
    return img.convert("RGB"), boxes


def write_split(items, n, split, rng):
    idir = os.path.join(ROOT, "images", split)
    ldir = os.path.join(ROOT, "labels", split)
    os.makedirs(idir, exist_ok=True)
    os.makedirs(ldir, exist_ok=True)
    for i in range(n):
        img, boxes = gen_image(items, rng)
        img.save(os.path.join(idir, f"{split}_{i:05d}.jpg"), quality=88)
        with open(os.path.join(ldir, f"{split}_{i:05d}.txt"), "w") as f:
            for (x0, y0, x1, y1) in boxes:
                cx = (x0 + x1) / 2 / TILE
                cy = (y0 + y1) / 2 / TILE
                bw = (x1 - x0) / TILE
                bh = (y1 - y0) / TILE
                f.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
        if (i + 1) % 100 == 0:
            print(f"  {split}: {i + 1}/{n}")


def main():
    def arg(name, d):
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else d
    n_train, n_val, seed = arg("--n", 600), arg("--val", 100), arg("--seed", 0)
    rng = np.random.default_rng(seed)
    items = load_items()
    print(f"{len(items)} usable icons")
    os.makedirs(ROOT, exist_ok=True)
    write_split(items, n_train, "train", rng)
    write_split(items, n_val, "val", rng)
    with open(os.path.join(ROOT, "data.yaml"), "w") as f:
        f.write(f"path: {ROOT}\ntrain: images/train\nval: images/val\n"
                f"nc: 1\nnames: [item]\n")
    print(f"-> {ROOT}")


if __name__ == "__main__":
    main()
