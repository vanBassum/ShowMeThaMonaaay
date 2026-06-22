"""
flood_background.py — Segment the fuzzy in-game background behind the UI overlay.

Idea: the background is a soft, blurry game-world image. It changes color only
gradually from pixel to pixel. The UI panels/slots sit on top of it with sharp,
high-contrast edges. So we region-grow (flood fill) starting at the bottom-left
corner and keep absorbing neighboring pixels as long as the *local* color change
(difference between a pixel and the already-filled neighbor it spreads from) stays
below a threshold. Sharp UI edges exceed the threshold and act as walls.

The original image is never modified — results are written to NEW files.

Usage:
    python flood_background.py
    python flood_background.py -i "test screenshot cropped.png" -t 18
    python flood_background.py --seed-x 0 --seed-y -1   # bottom-left (default)

Outputs (next to the input, suffixed):
    <name>_bg_mask.png     white = background, black = UI/foreground
    <name>_bg_overlay.png  original with background tinted, UI left intact
"""

import argparse
from collections import deque
import os

from PIL import Image
import numpy as np


def flood_background(img_rgb, seeds, threshold, connectivity=4):
    """Region-grow from one or more seeds. A pixel joins if the color step from
    the neighbor it spreads from is <= threshold (Euclidean distance in RGB).

    `seeds` may be a single (x, y) tuple or a list of them. Negative coords count
    from the right/bottom. Returns a boolean mask (H, W), True = background.
    """
    arr = img_rgb.astype(np.int32)
    h, w, _ = arr.shape

    # Accept a single (x, y) or a list of them.
    if len(seeds) == 2 and all(isinstance(v, (int, float)) for v in seeds):
        seeds = [seeds]

    visited = np.zeros((h, w), dtype=bool)
    mask = np.zeros((h, w), dtype=bool)

    t2 = float(threshold) * float(threshold)  # compare squared distance, skip sqrt

    if connectivity == 8:
        steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                 (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    q = deque()
    for sx, sy in seeds:
        sx, sy = int(sx), int(sy)
        if sx < 0:
            sx += w
        if sy < 0:
            sy += h
        if 0 <= sx < w and 0 <= sy < h and not visited[sy, sx]:
            visited[sy, sx] = True
            mask[sy, sx] = True
            q.append((sx, sy))

    while q:
        cx, cy = q.popleft()
        cr, cg, cb = arr[cy, cx]
        for dx, dy in steps:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            if visited[ny, nx]:
                continue
            nr, ng, nb = arr[ny, nx]
            d2 = (nr - cr) ** 2 + (ng - cg) ** 2 + (nb - cb) ** 2
            visited[ny, nx] = True
            if d2 <= t2:
                mask[ny, nx] = True
                q.append((nx, ny))
            # else: it's a wall; leave visited=True so we don't reprocess it
    return mask


def main():
    p = argparse.ArgumentParser(description="Flood-fill the fuzzy game background.")
    p.add_argument("-i", "--input", default="test screenshot cropped.png")
    p.add_argument("-o", "--output-prefix", default=None,
                   help="Output filename prefix (default: derived from input).")
    p.add_argument("-t", "--threshold", type=float, default=16.0,
                   help="Max local RGB color step to keep flooding (default 16).")
    p.add_argument("--seed-x", type=int, default=0,
                   help="Seed x (negative counts from right). Default 0 = left.")
    p.add_argument("--seed-y", type=int, default=-1,
                   help="Seed y (negative counts from bottom). Default -1 = bottom.")
    p.add_argument("-c", "--connectivity", type=int, choices=(4, 8), default=4)
    p.add_argument("--tint", default="255,0,0", help="Overlay tint R,G,B.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)

    mask = flood_background(rgb, (args.seed_x, args.seed_y),
                            args.threshold, args.connectivity)

    pct = 100.0 * mask.mean()
    print(f"Background covers {pct:.1f}% of the image "
          f"(threshold={args.threshold}, seed=({args.seed_x},{args.seed_y}))")

    base = args.output_prefix
    if base is None:
        root, _ = os.path.splitext(args.input)
        base = root

    # 1) Binary mask
    mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    mask_path = f"{base}_bg_mask.png"
    mask_img.save(mask_path)

    # 2) Overlay: tint the detected background so it's easy to eyeball.
    tint = np.array([int(c) for c in args.tint.split(",")], dtype=np.float32)
    over = rgb.astype(np.float32).copy()
    alpha = 0.55
    over[mask] = (1 - alpha) * over[mask] + alpha * tint
    overlay_path = f"{base}_bg_overlay.png"
    Image.fromarray(over.astype(np.uint8)).save(overlay_path)

    print(f"Wrote {mask_path}")
    print(f"Wrote {overlay_path}")


if __name__ == "__main__":
    main()
