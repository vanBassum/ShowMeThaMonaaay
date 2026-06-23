"""
auto_localize.py — Turn a "what is on screen" list into precise boxes by sliding
each KNOWN icon over the screenshot (OpenCV multi-scale masked matchTemplate).

Insight: a "what" detector (here: a ChatGPT-made labels.json) reliably names the
items present but places the boxes imprecisely. Template matching is the opposite
— useless for open-set ID (tried, failed), but excellent at LOCALISING an icon you
already hold. So: for each named item we resolve its reference icon, slide it
(several scales) within a window around the rough hint, and take the correlation
PEAK as the precise box. Output = auto-generated ground-truth (names + tight boxes).

  labels.json (what + rough where)  ->  per item: resolve icon -> slide -> peak
                                    ->  refined labels.json + overlay

Run:
  python auto_localize.py -i "test screenshot 1.png" -l "test screenshot 1.labels.json"
"""
import argparse
import difflib
import json
import os
import re

import numpy as np
import cv2
from PIL import Image

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")
SCALES = np.linspace(0.7, 1.3, 9)     # icon size relative to the hint box
PAD = 0.7                             # search window padding (fraction of hint size)
NAME_BAR = 0.16                       # blank the game's name strip in the icon mask


def norm_name(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load_items():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    out = []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if it.get("gridImageLink") and os.path.exists(p):
            out.append({"id": it["id"], "name": it.get("name", ""),
                        "short": it.get("shortName", ""), "path": p})
    return out


def resolve(gt_name, items):
    """Best item for a ChatGPT display name. Scores the query against BOTH the
    full name and the short name of every item (sequence ratio + token overlap),
    after stripping trailing instance counters ('Mag 1' -> 'Mag')."""
    raw = norm_name(gt_name)
    q = norm_name(re.sub(r"\b(\d+|stack)\b", " ", gt_name)) or raw
    qt = set(q.split())
    best, bscore = None, 0.0
    for it in items:
        cand = (norm_name(it["name"]), norm_name(it["short"]))
        s = 0.0
        for c in cand:
            if not c:
                continue
            ratio = difflib.SequenceMatcher(None, q, c).ratio()
            ct = set(c.split())
            overlap = len(qt & ct) / max(1, len(qt | ct))
            sub = 0.25 if (q in c or c in q) and len(c) >= 3 else 0.0
            s = max(s, 0.6 * ratio + 0.4 * overlap + sub)
        if s > bscore:
            bscore, best = s, it
    return (best, bscore) if bscore >= 0.34 else (None, bscore)


def localize(rgb_gray, icon_rgba, hint, W, H):
    """Slide the icon (multi-scale, alpha-masked) in a window around `hint`
    (x0,y0,x1,y1). Returns (score, box) or None."""
    hx0, hy0, hx1, hy1 = hint
    hw, hh = hx1 - hx0, hy1 - hy0
    wx0 = max(0, int(hx0 - PAD * hw)); wy0 = max(0, int(hy0 - PAD * hh))
    wx1 = min(W, int(hx1 + PAD * hw)); wy1 = min(H, int(hy1 + PAD * hh))
    win = rgb_gray[wy0:wy1, wx0:wx1]
    best = None
    for s in SCALES:
        tw, th = int(hw * s), int(hh * s)
        if tw < 8 or th < 8 or tw >= win.shape[1] or th >= win.shape[0]:
            continue
        ic = cv2.resize(icon_rgba, (tw, th), interpolation=cv2.INTER_AREA)
        tmpl = cv2.cvtColor(ic[..., :3], cv2.COLOR_RGB2GRAY)
        mask = ic[..., 3].copy()
        mask[:int(NAME_BAR * th), :] = 0           # ignore name-bar strip
        if mask.max() == 0:
            continue
        res = cv2.matchTemplate(win, tmpl, cv2.TM_CCORR_NORMED, mask=mask)
        res[~np.isfinite(res)] = 0
        _, mx, _, mxloc = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, (wx0 + mxloc[0], wy0 + mxloc[1],
                         wx0 + mxloc[0] + tw, wy0 + mxloc[1] + th))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="test screenshot 1.png")
    ap.add_argument("-l", "--labels", default="test screenshot 1.labels.json")
    ap.add_argument("-o", "--out", default="out/auto_localize.png")
    ap.add_argument("--save", help="write refined labels json here")
    args = ap.parse_args()

    items = load_items()
    print(f"{len(items)} reference icons")

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img); W, H = img.size
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    d = json.load(open(args.labels, encoding="utf-8"))
    sx = W / d["image"]["width"]; sy = H / d["image"]["height"]

    over = cv2.cvtColor(rgb.copy(), cv2.COLOR_RGB2BGR)
    refined = []
    print(f"\n{'GT name':<20}{'resolved icon':<22}{'nm':>4}{'score':>7}{'shift':>9}")
    print("-" * 72)
    for it in d["items"]:
        hint = (it["x"] * sx, it["y"] * sy, (it["x"] + it["w"]) * sx, (it["y"] + it["h"]) * sy)
        cv2.rectangle(over, (int(hint[0]), int(hint[1])), (int(hint[2]), int(hint[3])),
                      (0, 0, 200), 1)                       # faint red = ChatGPT hint
        item, nm = resolve(it["name"], items)
        if not item:
            print(f"{it['name'][:19]:<20}{'(unresolved)':<22}{nm:>4.2f}")
            continue
        ico = np.asarray(Image.open(item["path"]).convert("RGBA"))
        loc = localize(gray, ico, hint, W, H)
        if not loc:
            continue
        score, box = loc
        cx0 = (hint[0] + hint[2]) / 2; cy0 = (hint[1] + hint[3]) / 2
        ncx = (box[0] + box[2]) / 2; ncy = (box[1] + box[3]) / 2
        shift = int(((ncx - cx0) ** 2 + (ncy - cy0) ** 2) ** 0.5)
        print(f"{it['name'][:19]:<20}{item['short'][:21]:<22}{nm:>4.2f}{score:>7.3f}{shift:>7}px")
        col = (0, 220, 0) if score >= 0.6 else (0, 180, 255)
        cv2.rectangle(over, (box[0], box[1]), (box[2], box[3]), col, 2)
        cv2.putText(over, item["short"][:14], (box[0] + 2, box[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 255, 255), 1, cv2.LINE_AA)
        refined.append({"name": it["name"], "icon": item["short"], "score": round(score, 3),
                        "x": box[0], "y": box[1], "w": box[2] - box[0], "h": box[3] - box[1]})

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cv2.imwrite(args.out, over)
    print("-" * 72)
    print(f"{len(refined)}/{len(d['items'])} localized -> {args.out}  "
          f"(green=score>=0.6, red=ChatGPT hint)")
    if args.save:
        json.dump({"image": {"width": W, "height": H}, "items": refined},
                  open(args.save, "w"), indent=1)
        print(f"refined labels -> {args.save}")


if __name__ == "__main__":
    main()
