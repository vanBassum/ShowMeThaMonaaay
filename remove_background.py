"""
remove_background.py — Remove the fuzzy in-game background from the gear screen.

Pipeline:
  1. OCR the slot labels (find_items.find_labels) — EARPIECE, ON SLING, ...
  2. For each label, place a flood seed a little to the LEFT of the text. The
     panel border sits between the text and the background, so a point just left
     of the text reliably lands on the background (verified by pixel sampling).
  3. Multi-seed region-grow flood (flood_background.flood_background): the fill
     spreads across the smooth background and stops at the sharp panel edges.
  4. Everything flooded = background -> removed; the UI panels/items are kept.

The original image is never modified. All outputs go to the --outdir folder
(default "out/"), numbered in pipeline order:
  01_labels.png   OCR'd slot labels, boxed
  02_seeds.png    flood seeds (left of each label) + label boxes
  03_mask.png     flood mask — white = background that was removed
  04_nobg.png     foreground kept, background transparent (RGBA)
  05_preview.png  removed background shown as magenta (easy to eyeball)

Usage:
  python remove_background.py
  python remove_background.py -i "test screenshot 1.png" -t 20 --offset 14
"""
import argparse
import os

from PIL import Image, ImageDraw
import numpy as np

from find_items import find_labels
from flood_background import flood_background


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--outdir", default="out",
                   help="Folder for all numbered outputs (default: out/).")
    p.add_argument("-t", "--threshold", type=float, default=20.0,
                   help="Max local RGB color step to keep flooding (default 20).")
    p.add_argument("--offset", type=int, default=14,
                   help="Pixels left of each label's text start to place the seed.")
    p.add_argument("--scale", type=int, default=2, help="OCR upscale factor.")
    p.add_argument("-c", "--connectivity", type=int, choices=(4, 8), default=4)
    p.add_argument("--corners", action="store_true",
                   help="Also seed from the four image corners.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    h, w, _ = rgb.shape

    labels = find_labels(img, scale=args.scale)

    # Seed = a little to the left of each label's text, at the text's mid-height.
    seeds = []
    for text, x, y, bw, bh in labels:
        sx = int(x - args.offset)
        sy = int(y + bh / 2)
        sx = max(0, min(w - 1, sx))
        sy = max(0, min(h - 1, sy))
        seeds.append((sx, sy))

    if args.corners:
        seeds += [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]

    print(f"OCR found {len(labels)} labels -> {len(seeds)} flood seeds")

    os.makedirs(args.outdir, exist_ok=True)

    def out(name):
        return os.path.join(args.outdir, name)

    # --- Step 01: OCR'd labels, boxed ---
    labels_img = img.copy()
    dl = ImageDraw.Draw(labels_img)
    for text, x, y, bw, bh in labels:
        dl.rectangle([x, y, x + bw, y + bh], outline=(0, 255, 0), width=2)
    labels_img.save(out("01_labels.png"))

    # --- Step 02: seeds (left of each label) + label boxes ---
    seeds_img = img.copy()
    ds = ImageDraw.Draw(seeds_img)
    for (text, x, y, bw, bh), (sx, sy) in zip(labels, seeds):
        ds.rectangle([x, y, x + bw, y + bh], outline=(0, 255, 0), width=2)
        r = 5
        ds.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 0, 0),
                   outline=(255, 255, 255))
    seeds_img.save(out("02_seeds.png"))

    # --- Step 03: flood mask ---
    mask = flood_background(rgb, seeds, args.threshold, args.connectivity)
    print(f"Background = {100.0 * mask.mean():.1f}% of image (removed)")
    Image.fromarray((mask * 255).astype(np.uint8), mode="L").save(out("03_mask.png"))

    # --- Step 04: foreground with transparent background ---
    rgba = np.dstack([rgb, np.full((h, w), 255, dtype=np.uint8)])
    rgba[mask, 3] = 0
    Image.fromarray(rgba, mode="RGBA").save(out("04_nobg.png"))

    # --- Step 05: magenta preview (removed background = magenta) ---
    preview = rgb.copy()
    preview[mask] = (255, 0, 255)
    Image.fromarray(preview, "RGB").save(out("05_preview.png"))

    print(f"Wrote 01..05 to {args.outdir}/")


if __name__ == "__main__":
    main()
