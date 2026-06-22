"""
slot_mask.py — Per-slot-type background masking.

Each slot type (EARPIECE, HEADWEAR, FACE COVER, ...) gets its own masking
algorithm + settings, tuned independently in SLOT_MASK_CONFIG below. The layout
(div rectangle per slot) comes from cut_squares.build_layout; for each div we
crop the region, run that slot's configured masker, and mark the background.

Pipeline:
  cut_squares layout -> per-div crop -> per-slot-type algorithm -> background mask

Algorithms (registry ALGOS):
  "flood"      region-grow from seed pixels; flooded area = background.
                 params: threshold, seeds ("corners"|"edges"|"topleft"), connectivity
  "brightness" pixels with luminance <= dark (uniform dark panel) = background.
                 params: dark
  "none"       mask nothing (keep the whole div).

Tune a slot by editing its entry in SLOT_MASK_CONFIG. Unlisted slots use DEFAULT.

Outputs to out/:
  masks/<NAME>_<panel>.png  per-slot crop, background tinted magenta (for tuning)
  04_masked.png             full screen with every slot's background tinted magenta
  04_mask.png               full binary background mask (white = background)

Usage:
  python slot_mask.py
  python slot_mask.py --only EARPIECE          # process just one slot type
  python slot_mask.py --only HEADWEAR --set threshold=14   # quick override
"""
import argparse
import os

from PIL import Image
import numpy as np

from cut_squares import build_layout
from flood_background import flood_background

# ----------------------------------------------------------------------------
# Per-slot-type masking config. Edit freely to tune each slot independently.
# Each entry overrides DEFAULT for that slot; missing keys fall back to DEFAULT.
# ----------------------------------------------------------------------------
DEFAULT = {"algo": "flood", "threshold": 22, "seeds": "corners", "connectivity": 4}

SLOT_MASK_CONFIG = {
    "EARPIECE":    {"algo": "flood", "threshold": 22},
    "HEADWEAR":    {"algo": "flood", "threshold": 22},
    "FACE COVER":  {"algo": "flood", "threshold": 22},
    "ARMBAND":     {"algo": "flood", "threshold": 22},
    "BODY ARMOR":  {"algo": "flood", "threshold": 22},
    "EYEWEAR":     {"algo": "flood", "threshold": 22},
    "DOGTAG":      {"algo": "flood", "threshold": 22},
    "ON SLING":    {"algo": "flood", "threshold": 22},
    "ON BACK":     {"algo": "flood", "threshold": 22},
    "HOLSTER":     {"algo": "flood", "threshold": 22},
    "SHEATH":      {"algo": "flood", "threshold": 22},
    # Inventory grids: flood from the border (edge seeds spread along all sides
    # so the fill reaches the gaps between cells, not just the outer margin).
    "TACTICAL RIG":  {"algo": "flood", "threshold": 22, "seeds": "edges"},
    "POCKETS":       {"algo": "flood", "threshold": 22, "seeds": "edges"},
    "BACKPACK":      {"algo": "flood", "threshold": 22, "seeds": "edges"},
    "SPECIAL SLOTS": {"algo": "flood", "threshold": 22, "seeds": "edges"},
}


def config_for(name):
    return {**DEFAULT, **SLOT_MASK_CONFIG.get(name.upper(), {})}


# ----------------------------------------------------------------------------
# Algorithms: each takes a crop (H,W,3 uint8) + cfg, returns bool mask (H,W),
# True = background.
# ----------------------------------------------------------------------------
def seed_points(h, w, mode):
    if mode == "topleft":
        return [(1, 1)]
    if mode == "edges":
        pts = []
        for x in range(0, w, 4):
            pts += [(x, 1), (x, h - 2)]
        for y in range(0, h, 4):
            pts += [(1, y), (w - 2, y)]
        return pts
    # default: four corners
    return [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]


def algo_flood(crop, cfg):
    h, w, _ = crop.shape
    seeds = seed_points(h, w, cfg.get("seeds", "corners"))
    return flood_background(crop, seeds, cfg.get("threshold", 22),
                            cfg.get("connectivity", 4))


def algo_brightness(crop, cfg):
    lum = (0.299 * crop[:, :, 0] + 0.587 * crop[:, :, 1]
           + 0.114 * crop[:, :, 2])
    return lum <= cfg.get("dark", 60)


def algo_none(crop, cfg):
    return np.zeros(crop.shape[:2], dtype=bool)


ALGOS = {"flood": algo_flood, "brightness": algo_brightness, "none": algo_none}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--only", default=None,
                   help="Process only this slot type (name), for tuning.")
    p.add_argument("--set", dest="overrides", action="append", default=[],
                   help="Override a cfg key for this run, e.g. --set threshold=14. "
                        "Repeatable. Applies to all processed slots.")
    args = p.parse_args()

    overrides = {}
    for kv in args.overrides:
        k, _, v = kv.partition("=")
        try:
            v = int(v)
        except ValueError:
            try:
                v = float(v)
            except ValueError:
                pass
        overrides[k.strip()] = v

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    H, W, _ = rgb.shape

    layout = build_layout(img, verbose=False)
    divs = layout["divs"]

    os.makedirs(args.outdir, exist_ok=True)
    masks_dir = os.path.join(args.outdir, "masks")
    os.makedirs(masks_dir, exist_ok=True)

    full_mask = np.zeros((H, W), dtype=bool)
    magenta = np.array([255, 0, 255], dtype=np.uint8)

    print(f"{'SLOT':<14} {'ALGO':<10} settings")
    print("-" * 50)
    for d in divs:
        name = d["name"]
        if args.only and name.upper() != args.only.upper():
            continue
        x0, y0, x1, y1 = d["rect"]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue

        cfg = {**config_for(name), **overrides}
        algo = ALGOS.get(cfg["algo"], algo_none)
        crop = rgb[y0:y1, x0:x1]
        mask = algo(crop, cfg)
        full_mask[y0:y1, x0:x1] |= mask

        settings = {k: v for k, v in cfg.items() if k != "algo"}
        print(f"{name:<14} {cfg['algo']:<10} {settings}")

        # per-slot tuning image: crop with background tinted magenta
        tile = crop.copy()
        tile[mask] = (tile[mask] * 0.35 + magenta * 0.65).astype(np.uint8)
        safe = name.replace(" ", "_")
        Image.fromarray(tile, "RGB").save(
            os.path.join(masks_dir, f"{safe}_{d['panel']}.png"))

    # full composite
    preview = rgb.copy()
    preview[full_mask] = (preview[full_mask] * 0.35 + magenta * 0.65).astype(np.uint8)
    Image.fromarray(preview, "RGB").save(os.path.join(args.outdir, "04_masked.png"))
    Image.fromarray((full_mask * 255).astype(np.uint8), "L").save(
        os.path.join(args.outdir, "04_mask.png"))

    print(f"\nBackground = {100.0 * full_mask.mean():.1f}% of image")
    print(f"Wrote masks/, 04_masked.png, 04_mask.png to {args.outdir}/")


if __name__ == "__main__":
    main()
