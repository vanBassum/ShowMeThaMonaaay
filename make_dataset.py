"""
make_dataset.py — build a YOLO detector dataset from a calibrated template.

For each sample: blank the real items out of every grid (paint empty cells +
grid lines), fill cells with footprint-packed random items + variant overlays,
then cut 960px tiles ONLY from the gridded region (so no unlabeled real items —
the left equipment panel never enters training). Tiles inherit the real UI chrome
around the containers, at the true ~84px cell scale that matches tiled inference.

Output: data/yolo_real/{images,labels}/{train,val} + data.yaml

Run:  python make_dataset.py [--n 100] [--imgsz 960] [--template DIR] [--no-variants]
"""
import json
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

import gen_screenshot as gs

ROOT = os.path.dirname(__file__)


def augment(rgb, rng):
    """Mild per-sample variation so the single static background isn't memorized:
    brightness/contrast/colour jitter + light gaussian sensor noise."""
    rgb = ImageEnhance.Brightness(rgb).enhance(rng.uniform(0.88, 1.12))
    rgb = ImageEnhance.Contrast(rgb).enhance(rng.uniform(0.92, 1.10))
    rgb = ImageEnhance.Color(rgb).enhance(rng.uniform(0.90, 1.10))
    a = np.asarray(rgb).astype(np.int16)
    a += rng_noise(a.shape, rng)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def rng_noise(shape, rng):
    return (np.random.default_rng(rng.randint(0, 2**32 - 1))
            .normal(0, 4.0, shape)).astype(np.int16)


def _save(img, tx, ty, T, OUTD, sub, name, lab):
    img.crop((tx, ty, tx + T, ty + T)).save(
        os.path.join(OUTD, "images", sub, name + ".jpg"), quality=92)
    open(os.path.join(OUTD, "labels", sub, name + ".txt"), "w").write(lab)


def noise_bg(T, rng):
    """Pure noise + soft blobs + random UNLABELED clutter shapes (lines, rects,
    circles) at non-cell sizes — hard negatives so the detector learns a real item
    isn't just any rectangle/edge."""
    g = np.random.default_rng(rng.randint(0, 2**32 - 1))
    a = np.clip(g.normal(g.integers(6, 50), g.uniform(6, 18), (T, T, 3)), 0, 255).astype(np.uint8)
    img = Image.fromarray(a, "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(int(g.integers(0, 5))):       # soft blobs
        cx, cy, r = g.integers(0, T), g.integers(0, T), int(g.integers(40, 200))
        col = tuple(int(v) for v in g.integers(10, 90, 3)) + (int(g.integers(20, 80)),)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    for _ in range(int(g.integers(3, 12))):       # clutter shapes (unlabeled)
        col = tuple(int(v) for v in g.integers(20, 170, 3)) + (int(g.integers(50, 210)),)
        wd = int(g.integers(1, 5)); kind = int(g.integers(0, 3))
        if kind == 0:
            d.line([int(g.integers(0, T)) for _ in range(4)], fill=col, width=wd)
        elif kind == 1:
            x0, y0 = int(g.integers(0, T)), int(g.integers(0, T))
            x1, y1 = x0 + int(g.integers(15, 280)), y0 + int(g.integers(15, 280))
            if g.random() < 0.5:
                d.rectangle([x0, y0, x1, y1], fill=col)
            else:
                d.rectangle([x0, y0, x1, y1], outline=col, width=wd)
        else:
            cx, cy, r = int(g.integers(0, T)), int(g.integers(0, T)), int(g.integers(8, 140))
            (d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col) if g.random() < 0.5
             else d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=wd))
    return img.convert("RGBA")


def noise_tile(pool, rng, T, variants):
    """Items scattered (non-overlapping, ~real scale) over pure noise + clutter —
    teaches the detector to find items independent of background. (Items keep their
    catalog cell-bg for now; true-alpha icons from gamedata are a later step.)"""
    img = noise_bg(T, rng); cell = rng.uniform(70, 92); placed = []
    for _ in range(rng.randint(4, 16)):
        iid, fw, fh = rng.choice(pool)
        w, h = int(fw * cell), int(fh * cell)
        if not (8 <= w <= T and 8 <= h <= T):
            continue
        x, y = rng.randint(0, T - w), rng.randint(0, T - h)
        if any(x < px+pw and x+w > px and y < py+ph and y+h > py for px, py, pw, ph in placed):
            continue
        icon = Image.open(os.path.join(gs.ICONS, iid + ".webp")).convert("RGBA").resize((w, h))
        if variants:
            icon = gs.stamp_variant(icon, rng)
        img.alpha_composite(icon, (x, y))
        placed.append((x, y, w, h))
    labs = [f"0 {(x+w/2)/T:.6f} {(y+h/2)/T:.6f} {w/T:.6f} {h/T:.6f}" for x, y, w, h in placed]
    return img.convert("RGB"), "\n".join(labs)
EMPTY = (30, 38, 42, 255)      # measured empty-cell fill
BORDER = (55, 73, 77, 255)     # measured cell border


def pitch(g):
    return g.get("cell", g["w"] / g["cols"])


def blank_grid(d, g):
    p = pitch(g); cols, rows = int(g["cols"]), int(g["rows"])
    x0, y0, w, h = g["x"], g["y"], cols * p, rows * p
    d.rectangle([x0, y0, x0 + w, y0 + h], fill=EMPTY)
    for c in range(cols + 1):
        x = round(x0 + c * p); d.line([x, y0, x, y0 + h], fill=BORDER)
    for r in range(rows + 1):
        y = round(y0 + r * p); d.line([x0, y, x0 + w, y], fill=BORDER)


def origins(lo, hi, T, S):
    xs, x = [], lo
    while x + T <= hi:
        xs.append(int(x)); x += S
    xs.append(max(int(lo), int(hi - T)))
    return sorted(set(xs))


def main():
    N = gs.arg("--n", 100, int)
    T = gs.arg("--imgsz", 960, int)
    S = int(T * 0.8)
    variants = "--no-variants" not in sys.argv
    tdir = gs.arg("--template", os.path.join(ROOT, "templates", "screen1"))
    OUTD = os.path.join(ROOT, "data", "yolo_real")
    VAL = max(1, N // 8)

    bg = Image.open(os.path.join(tdir, "background.png")).convert("RGBA")
    grids = json.load(open(os.path.join(tdir, "grids.json"), encoding="utf-8"))
    pool = gs.item_pool()
    minx = min(g["x"] for g in grids); miny = min(g["y"] for g in grids)
    maxx = max(g["x"] + g["cols"] * pitch(g) for g in grids)
    maxy = max(g["y"] + g["rows"] * pitch(g) for g in grids)
    txs, tys = origins(minx, maxx, T, S), origins(miny, maxy, T, S)
    print(f"{len(pool)} items, {len(grids)} grids, region {int(maxx-minx)}x{int(maxy-miny)}, "
          f"tiles {len(txs)}x{len(tys)}/sample, variants={variants}")

    for sub in ("train", "val"):
        os.makedirs(os.path.join(OUTD, "images", sub), exist_ok=True)
        os.makedirs(os.path.join(OUTD, "labels", sub), exist_ok=True)

    ntiles = nneg = 0
    for i in range(N):
        rng = random.Random(i + 1)
        img = bg.copy(); d = ImageDraw.Draw(img)
        for g in grids:
            blank_grid(d, g)
        empty_sample = (i % 6 == 0)        # ~1 in 6 = fully empty inventory (negatives)
        fill = 0.0 if empty_sample else rng.uniform(0.10, 0.80)
        boxes = []
        for g in grids:
            for iid, x, y, w, h in gs.fill_grid(g, pool, rng, fill):
                icon = Image.open(os.path.join(gs.ICONS, iid + ".webp")).convert("RGBA")
                icon = icon.resize((max(1, round(w)), max(1, round(h))))
                if variants:
                    icon = gs.stamp_variant(icon, rng)
                img.alpha_composite(icon, (round(x), round(y)))
                boxes.append((x, y, w, h))
        rgb = augment(img.convert("RGB"), rng)
        sub = "val" if i < VAL else "train"
        for tx in txs:
            for ty in tys:
                labs = []
                for (x, y, w, h) in boxes:
                    ix0, iy0 = max(x, tx), max(y, ty)
                    ix1, iy1 = min(x + w, tx + T), min(y + h, ty + T)
                    iw, ih = ix1 - ix0, iy1 - iy0
                    if iw <= 2 or ih <= 2 or iw * ih < 0.4 * w * h:
                        continue
                    labs.append(f"0 {((ix0+ix1)/2-tx)/T:.6f} {((iy0+iy1)/2-ty)/T:.6f} {iw/T:.6f} {ih/T:.6f}")
                if not labs:
                    # empty grid tile = empty-inventory negative (always on fully-empty
                    # samples, occasionally on sparse ones) so the model learns blank cells
                    if empty_sample or rng.random() < 0.3:
                        _save(rgb, tx, ty, T, OUTD, sub, f"e{i:04d}_{tx}_{ty}", "")
                        nneg += 1
                    continue
                _save(rgb, tx, ty, T, OUTD, sub, f"s{i:04d}_{tx}_{ty}", "\n".join(labs))
                ntiles += 1
    # noise-background tiles: items scattered on pure noise (background-independent)
    NOISE = gs.arg("--noise", N, int)
    nnoise = 0
    for j in range(NOISE):
        rng = random.Random(10_000 + j)
        timg, lab = noise_tile(pool, rng, T, variants)
        if not lab:
            continue
        sub = "val" if j < max(1, NOISE // 8) else "train"
        _save(timg, 0, 0, T, OUTD, sub, f"noise{j:04d}", lab)
        nnoise += 1

    open(os.path.join(OUTD, "data.yaml"), "w").write(
        f"path: {OUTD}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [item]\n")
    print(f"{ntiles} item tiles + {nneg} background tiles + {nnoise} noise tiles -> {OUTD}")


if __name__ == "__main__":
    main()
