"""
extract_overlays.py — derive the game's cell-overlay assets by pixel-diffing the
SAME item neutral vs each state, from Examples/.

The game draws state markers ON TOP of the neutral cell: Found-in-Raid adds a
small ✓ (bottom-right, no border change); a "marked"/search-category state
repaints the cell border + warm tint AND adds a category glyph (bottom-left):
Barter=swap-arrows, Equipment=bar-chart, Hideout=house, Other=star, Task=floppy.

We align each flavour to the neutral (captures differ by ~1px) via template
match, take the per-pixel diff, and save the changed pixels (border + glyph) on a
transparent background — ready to (a) paste as random augmentations in gen_synth
and (b) mask at identify time so the corners don't corrupt matching.

Output: assets/overlays/{fir,marked_barter,marked_equipment,marked_hideout,
marked_other,marked_task}.png

Run:  python extract_overlays.py
"""
import os
import numpy as np
import cv2
from PIL import Image

ROOT = os.path.dirname(__file__)
EX = os.path.join(ROOT, "Examples")
OUT = os.path.join(ROOT, "assets", "overlays")

NEUTRAL = "Nuts.png"
FLAVOURS = [("fir", "Nuts_foundInRaid"),
            ("marked_barter", "Nuts_Marked_Barter"),
            ("marked_equipment", "Nuts_Marked_Equipment"),
            ("marked_hideout", "Nuts_Marked_Hideout"),
            ("marked_other", "Nuts_Marked_Other"),
            ("marked_task", "Nuts_Marked_Task")]
BORDER = 1        # crop 1px to allow ±1px alignment while keeping the cell border
NOISE = 5         # per-channel delta below this is capture noise, not a real change


def main():
    os.makedirs(OUT, exist_ok=True)
    base = np.asarray(Image.open(os.path.join(EX, NEUTRAL)).convert("RGB"))
    tmpl = base[BORDER:-BORDER, BORDER:-BORDER]
    th, tw, _ = tmpl.shape
    for name, fn in FLAVOURS:
        opt = np.asarray(Image.open(os.path.join(EX, fn + ".png")).convert("RGB"))
        # locate the neutral cell inside the (slightly offset) flavour capture
        _, _, loc, _ = cv2.minMaxLoc(cv2.matchTemplate(opt, tmpl, cv2.TM_SQDIFF))
        x, y = loc
        reg = opt[y:y + th, x:x + tw]
        dmax = np.abs(reg.astype(int) - tmpl.astype(int)).max(axis=2)
        alpha = np.clip((dmax - NOISE) * 6, 0, 255).astype(np.uint8)
        rgba = np.dstack([reg, alpha]).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(os.path.join(OUT, name + ".png"))
        print(f"{name:18} {tw}x{th}  changed_px={int((alpha > 0).sum())}")
    print("->", OUT)


if __name__ == "__main__":
    main()
