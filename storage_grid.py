"""
storage_grid.py — Detect storage-container cells from the flood MASK.

Key insight: the per-slot flood (seeds along the container border) fills the
gaps BETWEEN cells but is blocked by the cell borders from entering the cell
interiors. So in the mask, every cell is a clean foreground rectangle and the
grid lines are the flooded gaps. We just take the foreground connected
components — each is a cell (or a multi-cell compartment / a stored item).

  container crop -> border-seeded flood -> foreground = cells
                 -> connected components -> cell rectangles
                 -> (snap sizes to the ~84px pitch for clean rows/cols)

This sidesteps faint-line detection entirely and handles mixed compartment
sizes, empty vs filled cells, and grid extent in one shot.

Outputs to out/:
  05_containers.png   detected cells drawn per container
  05_containers.txt   per container: cell count + each cell rectangle (+ units)

Usage:
  python storage_grid.py
  python storage_grid.py --threshold 22 --pitch 84
"""
import argparse
import os

from PIL import Image, ImageDraw
import numpy as np
import cv2

from cut_squares import build_layout, load_font
from flood_background import flood_background

GRID_LABELS = {"TACTICAL RIG", "BACKPACK", "POCKETS", "SPECIAL SLOTS"}


def border_seeds(h, w):
    """Seed points spread along all four borders of the crop."""
    pts = []
    for x in range(0, w, 4):
        pts += [(x, 1), (x, h - 2)]
    for y in range(0, h, 4):
        pts += [(1, y), (w - 2, y)]
    return pts


def detect_cells(crop, threshold, pitch):
    """Flood the container background from its border, then return the
    foreground connected components (cells) as (x, y, w, h) within the crop."""
    h, w, _ = crop.shape
    bg = flood_background(crop, border_seeds(h, w), threshold, 4)
    fg = (~bg).astype(np.uint8) * 255

    # Tidy: close tiny gaps inside a cell, drop specks.
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    num, lbl, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    min_side = int(pitch * 0.45)
    min_area = int((pitch * 0.45) ** 2)
    cells = []
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if bw >= min_side and bh >= min_side and area >= min_area:
            cells.append((int(x), int(y), int(bw), int(bh)))
    return cells


def units(bw, bh, pitch):
    """Cell size in grid units (e.g. 1x2), rounded to the pitch."""
    return max(1, int(round(bw / pitch))), max(1, int(round(bh / pitch)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--threshold", type=float, default=22.0,
                   help="Flood color-step threshold (matches slot_mask).")
    p.add_argument("--pitch", type=int, default=84, help="Cell size in px.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    H, W, _ = rgb.shape

    layout = build_layout(img, verbose=False)
    containers = [d for d in layout["divs"] if d["name"].upper() in GRID_LABELS]

    os.makedirs(args.outdir, exist_ok=True)
    vis = img.copy()
    draw = ImageDraw.Draw(vis)
    font = load_font(max(11, W // 140))

    report = []
    for d in containers:
        x0, y0, x1, y1 = d["rect"]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        y0 += 28  # skip label header band
        crop = rgb[y0:y1, x0:x1]
        if crop.shape[0] < args.pitch or crop.shape[1] < args.pitch:
            continue

        cells = detect_cells(crop, args.threshold, args.pitch)
        abs_cells = [(x0 + cx, y0 + cy, bw, bh) for (cx, cy, bw, bh) in cells]

        for (ax, ay, bw, bh) in abs_cells:
            uw, uh = units(bw, bh, args.pitch)
            draw.rectangle([ax, ay, ax + bw, ay + bh], outline=(0, 255, 255), width=2)
            draw.text((ax + 2, ay + 2), f"{uw}x{uh}", fill=(0, 255, 255), font=font)
        if abs_cells:
            bx0 = min(c[0] for c in abs_cells)
            by0 = min(c[1] for c in abs_cells)
            bx1 = max(c[0] + c[2] for c in abs_cells)
            by1 = max(c[1] + c[3] for c in abs_cells)
            draw.rectangle([bx0, by0, bx1, by1], outline=(255, 160, 0), width=2)
            draw.text((bx0 + 2, by0 - 15), f"{d['name']} ({len(abs_cells)} cells)",
                      fill=(255, 160, 0), font=font)

        report.append((d, abs_cells))

    vis.save(os.path.join(args.outdir, "05_containers.png"))

    lines = []
    for d, cells in report:
        lines.append(f"{d['name']} (panel {d['panel']}): {len(cells)} cells")
        for i, (ax, ay, bw, bh) in enumerate(sorted(cells, key=lambda c: (c[1], c[0]))):
            uw, uh = units(bw, bh, args.pitch)
            lines.append(f"    cell {i:2d}: ({ax},{ay},{ax+bw},{ay+bh}) {uw}x{uh} units")
        lines.append("")
    with open(os.path.join(args.outdir, "05_containers.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(l for l in lines if not l.startswith("    ")))
    print(f"Wrote 05_containers.png, 05_containers.txt to {args.outdir}/")


if __name__ == "__main__":
    main()
