"""
square_detect.py — Grid-seeded square growing + merging.

Algorithm (continues the grid pipeline that starts with grid.py):
  1. Seed a point at every 32px grid intersection.
  2. Each seed grows an axis-aligned rectangle outward. Each of the 4 sides
     keeps stepping out until the strip of pixels just beyond it is mostly
     "wall" (a UI border edge), then that side locks.
  3. Tiny boxes (seeds that started on a wall / couldn't grow) are dropped.
  4. Overlapping rectangles merge (union of bounding boxes) until stable, so
     many seeds inside one cell collapse to a single rectangle.

Walls come from a gradient-magnitude edge map: sharp UI borders = high gradient.

The original image is never modified. Outputs to out/:
  02_edges.png   the wall map (white = edge/wall)
  03_grown.png   every grown rectangle (pre-merge) + seed dots
  04_merged.png  merged rectangles (the detected squares)

Usage:
  python square_detect.py
  python square_detect.py -i "test screenshot cropped.png" --cell 32 \
      --grad 18 --wall-frac 0.30 --min 10 --max 220
"""
import argparse
import os

from PIL import Image, ImageDraw
import numpy as np


def edge_map(rgb, grad_thresh):
    """Boolean wall map from gradient magnitude of the grayscale image."""
    g = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1]
         + 0.114 * rgb[:, :, 2]).astype(np.float32)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    return mag >= grad_thresh


def grow_square(walls, sx, sy, max_size, wall_frac):
    """Grow a rectangle from (sx, sy); each side steps out until the strip just
    beyond it is mostly wall. The full-strip wall test ignores an item's local
    internal edges (they don't span the strip) and only latches onto a real
    cell border that spans the whole side.

    Returns (box, closed) where `closed` is True only if every side stopped on a
    wall (a fully enclosed cell) rather than on the image edge or the size cap
    (an open background region)."""
    h, w = walls.shape
    x0 = x1 = sx
    y0 = y1 = sy
    live = {"L": True, "R": True, "U": True, "D": True}
    closed = {"L": False, "R": False, "U": False, "D": False}

    while any(live.values()):
        # Right
        if live["R"]:
            if x1 + 1 >= w or (x1 - x0) >= max_size:
                live["R"] = False
            elif walls[y0:y1 + 1, x1 + 1].mean() > wall_frac:
                closed["R"] = True
                live["R"] = False
            else:
                x1 += 1
        # Left
        if live["L"]:
            if x0 - 1 < 0 or (x1 - x0) >= max_size:
                live["L"] = False
            elif walls[y0:y1 + 1, x0 - 1].mean() > wall_frac:
                closed["L"] = True
                live["L"] = False
            else:
                x0 -= 1
        # Down
        if live["D"]:
            if y1 + 1 >= h or (y1 - y0) >= max_size:
                live["D"] = False
            elif walls[y1 + 1, x0:x1 + 1].mean() > wall_frac:
                closed["D"] = True
                live["D"] = False
            else:
                y1 += 1
        # Up
        if live["U"]:
            if y0 - 1 < 0 or (y1 - y0) >= max_size:
                live["U"] = False
            elif walls[y0 - 1, x0:x1 + 1].mean() > wall_frac:
                closed["U"] = True
                live["U"] = False
            else:
                y0 -= 1
    return (x0, y0, x1, y1), all(closed.values())


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def overlap_frac(a, b):
    """Intersection area / smaller box area. ~1 for coincident boxes (same
    cell), ~0 for boxes that merely touch at a shared border (adjacent cells)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    smaller = min(area(a), area(b))
    return inter / smaller if smaller else 0.0


def union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def merge_boxes(boxes, merge_frac):
    """Merge two boxes only when their overlap fraction >= merge_frac, so
    same-cell boxes collapse but adjacent cells stay separate."""
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        result = []
        while boxes:
            b = boxes.pop()
            merged = True
            while merged:
                merged = False
                rest = []
                for o in boxes:
                    if overlap_frac(b, o) >= merge_frac:
                        b = union(b, o)
                        merged = True
                        changed = True
                    else:
                        rest.append(o)
                boxes = rest
            result.append(b)
        boxes = result
    return boxes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot cropped.png")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--cell", type=int, default=32, help="Grid spacing for seeds.")
    p.add_argument("--grad", type=float, default=18.0,
                   help="Gradient magnitude above which a pixel is a wall.")
    p.add_argument("--wall-frac", type=float, default=0.18,
                   help="Strip is a wall if this fraction of it is edge pixels.")
    p.add_argument("--merge-frac", type=float, default=0.5,
                   help="Merge two boxes when overlap/smaller-area >= this.")
    p.add_argument("--min", type=int, default=84,
                   help="Minimum square size = one item (~84px). Grown boxes "
                        "smaller than this on either side are discarded.")
    p.add_argument("--max", type=int, default=220,
                   help="Max half-not... max side length while growing.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    h, w, _ = rgb.shape

    walls = edge_map(rgb, args.grad)

    # Seeds at every interior grid intersection.
    seeds = [(x, y)
             for y in range(args.cell, h, args.cell)
             for x in range(args.cell, w, args.cell)]

    grown = []
    dropped_open = 0
    for sx, sy in seeds:
        box, enclosed = grow_square(walls, sx, sy, args.max, args.wall_frac)
        big_enough = (box[2] - box[0]) >= args.min and (box[3] - box[1]) >= args.min
        if not big_enough:
            continue
        if not enclosed:
            dropped_open += 1
            continue
        grown.append(box)

    merged = merge_boxes(grown, args.merge_frac)

    print(f"{len(seeds)} seeds -> {len(grown)} enclosed boxes "
          f"({dropped_open} open/background dropped) -> {len(merged)} merged")

    os.makedirs(args.outdir, exist_ok=True)

    def out(name):
        return os.path.join(args.outdir, name)

    # 02: edge/wall map
    Image.fromarray((walls * 255).astype(np.uint8), "L").save(out("02_edges.png"))

    # 03: grown boxes + seeds
    g_img = img.copy()
    dg = ImageDraw.Draw(g_img)
    for sx, sy in seeds:
        dg.point((sx, sy), fill=(255, 0, 0))
    for x0, y0, x1, y1 in grown:
        dg.rectangle([x0, y0, x1, y1], outline=(0, 200, 255), width=1)
    g_img.save(out("03_grown.png"))

    # 04: merged boxes
    m_img = img.copy()
    dm = ImageDraw.Draw(m_img)
    for x0, y0, x1, y1 in merged:
        dm.rectangle([x0, y0, x1, y1], outline=(0, 255, 0), width=2)
    m_img.save(out("04_merged.png"))

    print(f"Wrote 02_edges.png, 03_grown.png, 04_merged.png to {args.outdir}/")


if __name__ == "__main__":
    main()
