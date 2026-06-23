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
# wide cell-pitch range -> scale-invariant detector (works at any resolution,
# no rescaling at inference). 84px is the 2560x1440 reference; we span well
# above and below so 1080p / 1440p / ultrawide all fall inside the range.
CELL_RANGE = (44, 124)
PROJ = os.path.dirname(__file__)

_FONT = None
_REAL_BG = None


def font():
    global _FONT
    if _FONT is None:
        try:
            _FONT = ImageFont.truetype("arial.ttf", 11)
        except Exception:
            _FONT = ImageFont.load_default()
    return _FONT


def real_bg_pool():
    """Heavily-blurred crops of real screenshots, used as background texture so
    synthetic tiles look like the real game world behind the panels. Blurred
    hard enough that real items dissolve into texture (won't be learned as
    detectable objects). Empty if no screenshots present."""
    global _REAL_BG
    if _REAL_BG is None:
        _REAL_BG = []
        import glob
        for p in glob.glob(os.path.join(PROJ, "*.png")) + \
                 glob.glob(os.path.join(PROJ, "*.jpg")):
            try:
                _REAL_BG.append(Image.open(p).convert("RGB")
                                .filter(ImageFilter.GaussianBlur(24)))
            except Exception:
                pass
    return _REAL_BG


def load_items():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    out = []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if it.get("gridImageLink") and os.path.exists(p):
            out.append((p, it["width"], it["height"], it.get("shortName", "")))
    return out


def background(rng):
    """A dark textured canvas mimicking the blurred game world. Half the time
    seeded from a heavily-blurred real screenshot crop (better domain match)."""
    pool = real_bg_pool()
    if pool and rng.random() < 0.5:
        src = pool[int(rng.integers(0, len(pool)))]
        W, H = src.size
        s = int(rng.integers(TILE, max(TILE + 1, min(W, H))))
        x, y = int(rng.integers(0, W - s + 1)), int(rng.integers(0, H - s + 1))
        return src.crop((x, y, x + s, y + s)).resize((TILE, TILE))
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


def draw_chrome(img, rng):
    """Paste fake UI chrome (header bars, button strips, text) that is NOT an
    item and gets NO box -- teaches the detector to ignore panels/tabs/quick-use
    bars instead of boxing them."""
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(int(rng.integers(0, 4))):
        kind = rng.integers(0, 3)
        if kind == 0:                                   # header/text bar
            x, y = rng.integers(0, TILE - 200), rng.integers(0, TILE - 20)
            d.rectangle([x, y, x + rng.integers(120, 240), y + rng.integers(14, 26)],
                        fill=(15, 16, 18, 220))
            d.text((x + 6, y + 3), "ABCDEF GHIJ", font=font(), fill=(150, 150, 150, 255))
        elif kind == 1:                                 # button / icon strip
            x, y = rng.integers(0, TILE - 220), rng.integers(0, TILE - 40)
            for k in range(int(rng.integers(4, 9))):
                d.rectangle([x + k * 34, y, x + k * 34 + 30, y + 30],
                            outline=(80, 80, 80, 200), width=1)
        else:                                           # solid dark gutter
            x = rng.integers(0, TILE - 30)
            d.rectangle([x, 0, x + rng.integers(8, 26), TILE], fill=(8, 8, 9, 200))


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
    """Paste an item icon scaled to its footprint at (x,y), CLIPPED to the tile
    (so items at edges become partial/half items). Adds name bar + count
    overlay. Returns the visible bbox clipped to the tile, or None if <40%
    visible."""
    pw, ph = w_cells * cell, h_cells * cell
    ic = Image.open(icon_path).convert("RGBA").resize((pw, ph))
    d = ImageDraw.Draw(ic)
    if rng.random() < 0.7 and label:      # name bar (top), as the game prints
        bar = Image.new("RGBA", (pw, max(10, int(ph * 0.16))), (10, 10, 10, 150))
        ic.alpha_composite(bar, (0, 0))
        d.text((2, 1), label[:max(1, int(pw / 6))], font=font(), fill=(210, 210, 200, 255))
    if rng.random() < 0.5:                # count / durability (bottom-right)
        d.text((pw - 16, ph - 14), str(rng.integers(1, 60)), font=font(),
               fill=(220, 210, 120, 255))
    # clip to tile bounds (supports partial items at edges)
    vx0, vy0 = max(0, x), max(0, y)
    vx1, vy1 = min(TILE, x + pw), min(TILE, y + ph)
    if vx1 - vx0 < 0.4 * pw or vy1 - vy0 < 0.4 * ph:
        return None
    img.alpha_composite(ic.crop((vx0 - x, vy0 - y, vx1 - x, vy1 - y)), (vx0, vy0))
    return (vx0, vy0, vx1, vy1)


def _overlaps(box, placed):
    """True if `box` (x0,y0,x1,y1) overlaps any rect in `placed`. Real inventory
    items never overlap, so we reject any placement that would (touching is fine:
    strict < keeps adjacent items, which the anti-merge pairs rely on)."""
    x0, y0, x1, y1 = box
    for (a, b, c, d) in placed:
        if x0 < c and a < x1 and y0 < d and b < y1:
            return True
    return False


def gen_image(items, rng):
    img = background(rng).convert("RGBA")
    boxes = []                 # labelled item boxes (also used for overlap tests)
    panels = []                # panel rects, kept non-overlapping
    cell = int(rng.integers(*CELL_RANGE))
    # 1-3 grid panels, densely filled, never overlapping each other
    for _ in range(rng.integers(1, 4)):
        cols = int(rng.integers(2, max(3, TILE // cell)))
        rows = int(rng.integers(2, max(3, TILE // cell)))
        x0 = int(rng.integers(0, max(1, TILE - cols * cell)))
        y0 = int(rng.integers(0, max(1, TILE - rows * cell)))
        prect = (x0, y0, x0 + cols * cell, y0 + rows * cell)
        if prect[2] > TILE or prect[3] > TILE or _overlaps(prect, panels):
            continue
        panels.append(prect)
        draw_panel(img, x0, y0, cols, rows, cell)
        occ = np.zeros((rows, cols), bool)
        attempts = int(cols * rows * rng.uniform(0.6, 1.1))   # denser packing
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
            if bb:
                boxes.append(bb)
            # adjacent IDENTICAL item (teaches the detector to split touching
            # items instead of merging them into one box)
            if rng.random() < 0.35 and c + 2 * iw <= cols and not occ[r:r + ih, c + iw:c + 2 * iw].any():
                occ[r:r + ih, c + iw:c + 2 * iw] = True
                bb2 = paste_item(img, p, iw, ih, x0 + (c + iw) * cell,
                                 y0 + r * cell, cell, rng, sn)
                if bb2:
                    boxes.append(bb2)
    # free-floating "equipment slot" items, some deliberately clipped at edges;
    # never overlapping an already-placed item (retry a few spots, then give up)
    for _ in range(rng.integers(0, 4)):
        p, iw, ih, sn = items[rng.integers(0, len(items))]
        pw, ph = iw * cell, ih * cell
        if pw >= TILE or ph >= TILE:
            continue
        for _try in range(6):
            if rng.random() < 0.3:            # partial: hang off an edge
                x = int(rng.choice([-pw // 3, TILE - pw + pw // 3, rng.integers(0, TILE - pw)]))
                y = int(rng.choice([-ph // 3, TILE - ph + ph // 3, rng.integers(0, TILE - ph)]))
            else:
                x, y = int(rng.integers(0, TILE - pw)), int(rng.integers(0, TILE - ph))
            cand = (max(0, x), max(0, y), min(TILE, x + pw), min(TILE, y + ph))
            if not _overlaps(cand, boxes):
                bb = paste_item(img, p, iw, ih, x, y, cell, rng, sn)
                if bb:
                    boxes.append(bb)
                break
    draw_chrome(img, rng)                      # unboxed UI negatives
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
