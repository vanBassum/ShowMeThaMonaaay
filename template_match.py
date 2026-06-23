"""
template_match.py — Identify item crops by matching them against the reference
grid icons (OpenCV / masked normalized cross-correlation).

The tarkov.dev grid icons ARE the in-game icons, so a well-aligned crop should
correlate strongly with its own icon. We exploit that and neutralise the
confounders:
  - use the icon's ALPHA as a mask -> compare only the item silhouette, ignoring
    the cell background / rarity tint the game draws behind it;
  - blank the top name-bar strip the game prints (the clean icon lacks it);
  - prefilter candidates by aspect ratio (scale-free footprint proxy) so we only
    score icons of a plausible shape.

This is the "what is it" stage (an alternative to the CNN), NOT detection. It
needs item boxes as input -- here we read the GT labels so we can measure it.

Run:
  python template_match.py -i "test screenshot 1.png" -l "test screenshot 1.labels.json"
"""
import argparse
import json
import os

import numpy as np
import cv2
from PIL import Image

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")
NAME_BAR = 0.16        # top fraction the game overlays the item name on -> ignore
ASPECT_TOL = 1.45      # candidate kept if aspect within this factor of the crop's

_ICON_CACHE = {}


def load_items():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    out = []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if it.get("gridImageLink") and os.path.exists(p):
            w, h = it.get("width", 1), it.get("height", 1)
            out.append({"id": it["id"], "short": it.get("shortName", it["id"]),
                        "name": it.get("name", it["id"]), "w": w, "h": h,
                        "aspect": w / max(1, h), "path": p})
    return out


def icon_rgba(path):
    if path not in _ICON_CACHE:
        _ICON_CACHE[path] = np.asarray(Image.open(path).convert("RGBA"))
    return _ICON_CACHE[path]


def masked_ncc(crop_gray, icon_gray, mask):
    """Zero-mean normalised cross-correlation over masked pixels (range -1..1)."""
    m = mask > 0.3
    if m.sum() < 25:
        return -1.0
    a = crop_gray[m].astype(np.float32)
    b = icon_gray[m].astype(np.float32)
    a -= a.mean(); b -= b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6
    return float((a * b).sum() / denom)


def identify(crop_rgb, items, topn=5):
    ch, cw = crop_rgb.shape[:2]
    crop_gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    crop_ar = cw / max(1, ch)
    bar = int(NAME_BAR * ch)
    scores = []
    for it in items:
        if not (crop_ar / ASPECT_TOL <= it["aspect"] <= crop_ar * ASPECT_TOL):
            continue
        ic = icon_rgba(it["path"])
        ic = cv2.resize(ic, (cw, ch), interpolation=cv2.INTER_AREA)
        icon_gray = cv2.cvtColor(ic[..., :3], cv2.COLOR_RGB2GRAY)
        mask = (ic[..., 3].astype(np.float32) / 255.0)
        mask[:bar, :] = 0.0                       # ignore the name-bar strip
        scores.append((masked_ncc(crop_gray, icon_gray, mask), it))
    scores.sort(key=lambda s: -s[0])
    return scores[:topn]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="test screenshot 1.png")
    ap.add_argument("-l", "--labels", default="test screenshot 1.labels.json")
    ap.add_argument("-o", "--out", default="out/template_match.png")
    args = ap.parse_args()

    items = load_items()
    print(f"{len(items)} reference icons")
    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    W, H = img.size
    d = json.load(open(args.labels, encoding="utf-8"))
    sx = W / d["image"]["width"]; sy = H / d["image"]["height"]

    over = cv2.cvtColor(rgb.copy(), cv2.COLOR_RGB2BGR)
    print(f"\n{'GT name':<22}{'-> top-1 match':<22}{'score':>6}   top-3")
    print("-" * 92)
    for it in d["items"]:
        x0, y0 = int(it["x"] * sx), int(it["y"] * sy)
        x1, y1 = int((it["x"] + it["w"]) * sx), int((it["y"] + it["h"]) * sy)
        crop = rgb[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        res = identify(crop, items)
        top = res[0] if res else (0.0, {"short": "?", "name": "?"})
        s, best = top
        top3 = ", ".join(f"{r[1]['short']}({r[0]:.2f})" for r in res[:3])
        print(f"{it['name'][:21]:<22}{best['short'][:21]:<22}{s:>6.2f}   {top3}")
        col = (0, 220, 0) if s >= 0.5 else (0, 165, 255)
        cv2.rectangle(over, (x0, y0), (x1, y1), col, 2)
        cv2.putText(over, f"{best['short'][:14]} {s:.2f}", (x0 + 2, y0 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 255, 255), 1, cv2.LINE_AA)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cv2.imwrite(args.out, over)
    print("-" * 92)
    print(f"-> {args.out}  (green = score>=0.5)")


if __name__ == "__main__":
    main()
