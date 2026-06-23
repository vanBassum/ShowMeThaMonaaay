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
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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


def _label(rng):
    """A short uppercase pseudo-label like the game's slot/tab captions."""
    n = int(rng.integers(3, 9))
    return "".join(chr(int(c)) for c in rng.integers(65, 91, n))


def draw_equipment_slots(img, items, rng, occupied):
    """Draw EMPTY equipment slots: a bordered box with a faint placeholder
    silhouette + a caption, getting NO box. These are the dominant real-world
    false positive (the detector boxes empty EARPIECE/HOLSTER/EYEWEAR slots),
    so teaching them explicitly as negatives is the key fix. Skips any slot that
    would cover a real (labelled) item."""
    for _ in range(int(rng.integers(0, 6))):
        sw, sh = int(rng.integers(70, 170)), int(rng.integers(70, 170))
        x, y = int(rng.integers(0, max(1, TILE - sw))), int(rng.integers(0, max(1, TILE - sh)))
        slot = (x, y, x + sw, y + sh)
        if _hits_any(slot, occupied):
            continue
        occupied.append(slot)                       # later slots avoid this one too
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle(slot, fill=(int(rng.integers(24, 36)),) * 3 + (180,),
                    outline=(int(rng.integers(60, 84)),) * 3 + (200,), width=1)
        if rng.random() < 0.85:                     # faint placeholder silhouette
            p, iw, ih, sn = items[rng.integers(0, len(items))]
            try:
                ic = Image.open(p).convert("RGBA")
            except Exception:
                continue
            m = int(min(sw, sh) * 0.18)
            ic.thumbnail((max(1, sw - 2 * m), max(1, sh - 2 * m)))
            a = ic.split()[3].point(lambda v: int(v * 0.4))      # ~40% opacity
            g = ImageOps.grayscale(ic).point(lambda v: int(v * 0.4))  # dim grey
            sil = Image.merge("RGBA", (g, g, g, a))
            img.alpha_composite(sil, (x + (sw - sil.width) // 2, y + (sh - sil.height) // 2))
        if rng.random() < 0.9:                      # caption (EARPIECE, HOLSTER...)
            d.text((x + 4, y + 3), _label(rng), font=font(), fill=(140, 140, 140, 255))


def draw_chrome(img, rng, occupied):
    """Paste fake UI chrome (header bars, button strips, a vertical toolbar of
    icon buttons, preset-preview thumbnails) that is NOT an item and gets NO box
    -- teaches the detector to ignore panels/tabs/toolbars instead of boxing
    them. Skips placements that would cover a real (labelled) item."""
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(int(rng.integers(1, 5))):
        kind = rng.integers(0, 5)
        if kind == 0:                                   # header/text bar
            w, h = int(rng.integers(120, 240)), int(rng.integers(14, 26))
            x, y = int(rng.integers(0, TILE - w)), int(rng.integers(0, TILE - h))
            if _hits_any((x, y, x + w, y + h), occupied):
                continue
            d.rectangle([x, y, x + w, y + h], fill=(15, 16, 18, 220))
            d.text((x + 6, y + 3), _label(rng) + " " + _label(rng),
                   font=font(), fill=(150, 150, 150, 255))
        elif kind == 1:                                 # horizontal button strip
            x, y = int(rng.integers(0, TILE - 220)), int(rng.integers(0, TILE - 40))
            for k in range(int(rng.integers(4, 9))):
                bx = (x + k * 34, y, x + k * 34 + 30, y + 30)
                if not _hits_any(bx, occupied):
                    d.rectangle(list(bx), outline=(80, 80, 80, 200), width=1)
        elif kind == 2:                                 # solid dark side gutter
            x = int(rng.integers(0, TILE - 30))
            d.rectangle([x, 0, x + int(rng.integers(8, 26)), TILE], fill=(8, 8, 9, 200))
        elif kind == 3:                                 # vertical toolbar of icon buttons
            bs = int(rng.integers(26, 40))              # button size
            x = int(rng.choice([rng.integers(0, 20), TILE - bs - int(rng.integers(0, 20))]))
            y0 = int(rng.integers(0, TILE // 3))
            for k in range(int(rng.integers(6, 16))):
                by = y0 + k * (bs + 2)
                if by + bs > TILE:
                    break
                bx = (x, by, x + bs, by + bs)
                if _hits_any(bx, occupied):
                    continue
                d.rectangle(list(bx), fill=(22, 24, 27, 200), outline=(70, 74, 80, 220), width=1)
                d.line([x + 6, by + bs // 2, x + bs - 6, by + bs // 2],
                       fill=(110, 114, 120, 220), width=2)   # faint glyph
        else:                                           # preset-preview thumbnails row
            tw, th = int(rng.integers(80, 140)), int(rng.integers(40, 70))
            x, y = int(rng.integers(0, max(1, TILE - 5 * tw))), int(rng.integers(0, TILE - th))
            for k in range(int(rng.integers(2, 6))):
                bx = (x + k * (tw + 4), y, x + k * (tw + 4) + tw, y + th)
                if bx[2] > TILE or _hits_any(bx, occupied):
                    continue
                d.rectangle(list(bx), fill=(18, 20, 22, 210), outline=(60, 64, 70, 200), width=1)
                d.line([bx[0] + 8, y + th // 2, bx[2] - 8, y + th // 2],
                       fill=(90, 94, 100, 200), width=3)


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


def _intersects(a, b):
    """True if pixel boxes a,b (x0,y0,x1,y1) overlap at all."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _hits_any(box, rects):
    return any(_intersects(box, r) for r in rects)


def gen_image(items, rng):
    img = background(rng).convert("RGBA")
    boxes = []
    panel_rects = []                  # panels must not overlap each other
    cell = int(rng.integers(*CELL_RANGE))
    # 1-3 grid panels, densely filled
    for _ in range(rng.integers(1, 4)):
        cols = int(rng.integers(2, max(3, TILE // cell)))
        rows = int(rng.integers(2, max(3, TILE // cell)))
        x0 = int(rng.integers(0, max(1, TILE - cols * cell)))
        y0 = int(rng.integers(0, max(1, TILE - rows * cell)))
        if x0 + cols * cell > TILE or y0 + rows * cell > TILE:
            continue
        prect = (x0, y0, x0 + cols * cell, y0 + rows * cell)
        if _hits_any(prect, panel_rects):     # Tarkov panels never overlap
            continue
        panel_rects.append(prect)
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
    # free-floating "equipment slot" items, some deliberately clipped at edges.
    # Like real inventories these never overlap panels or each other, so reject
    # any candidate that collides with an already-placed box/panel.
    for _ in range(rng.integers(0, 4)):
        p, iw, ih, sn = items[rng.integers(0, len(items))]
        pw, ph = iw * cell, ih * cell
        if pw >= TILE or ph >= TILE:
            continue
        if rng.random() < 0.3:                # partial: hang off an edge
            x = int(rng.choice([-pw // 3, TILE - pw + pw // 3, rng.integers(0, TILE - pw)]))
            y = int(rng.choice([-ph // 3, TILE - ph + ph // 3, rng.integers(0, TILE - ph)]))
        else:
            x, y = int(rng.integers(0, TILE - pw)), int(rng.integers(0, TILE - ph))
        cand = (max(0, x), max(0, y), min(TILE, x + pw), min(TILE, y + ph))
        if _hits_any(cand, panel_rects) or _hits_any(cand, boxes):
            continue
        bb = paste_item(img, p, iw, ih, x, y, cell, rng, sn)
        if bb:
            boxes.append(bb)
    # unboxed negatives -- must not cover labelled items, so share an occupancy
    # list seeded with the panels + every placed item box.
    occupied = panel_rects + list(boxes)
    draw_equipment_slots(img, items, rng, occupied)  # empty slots (main FP fix)
    draw_chrome(img, rng, occupied)                  # tabs, toolbars, thumbnails
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
