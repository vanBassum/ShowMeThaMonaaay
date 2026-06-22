"""
YOLO-detect every item on screen, then hash-identify each detected box.

Detection and identification are decoupled (the lesson from the baseline):
  * YOLO finds item rectangles ANYWHERE -- equipment slots, rigs, backpacks --
    and ignores empty cells. Run tiled at native scale so cells stay ~84 px,
    matching the training scale (best accuracy on CPU).
  * The existing perceptual-hash DB NAMES each crop (footprint estimated from
    the box size in cells).

Run:  python detect_items.py "test screenshot 1.png" [--conf 0.25]
"""
import os
import sys
import json
import difflib
import numpy as np
import torch
from PIL import Image, ImageOps
from ultralytics import YOLO

import identify
import cls
try:
    import ocr as ocrmod
except Exception:
    ocrmod = None

PROB_OK = 0.40   # classifier softmax prob above this == trust the name

ROOT = os.path.dirname(__file__)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")
WEIGHTS = os.path.join(ROOT, "runs", "detect", "items", "weights", "best.pt")
CELL = 84            # native cell pitch @ 2560x1440
TILE, STRIDE = 640, 512   # overlapping tiles (128 px overlap)


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def tiled_detect(model, pil, conf):
    """Run the detector over overlapping native-scale tiles; return boxes in
    full-image coords as an (N,5) array [x0,y0,x1,y1,score]."""
    W, H = pil.size
    dets = []
    xs = list(range(0, max(1, W - TILE) + 1, STRIDE)) + [max(0, W - TILE)]
    ys = list(range(0, max(1, H - TILE) + 1, STRIDE)) + [max(0, H - TILE)]
    for y in sorted(set(ys)):
        for x in sorted(set(xs)):
            tile = pil.crop((x, y, min(x + TILE, W), min(y + TILE, H)))
            res = model.predict(tile, conf=conf, imgsz=TILE, verbose=False)[0]
            for b in res.boxes.xyxy.cpu().numpy():
                x0, y0, x1, y1 = b
                dets.append([x0 + x, y0 + y, x1 + x, y1 + y])
            scores = res.boxes.conf.cpu().numpy() if len(res.boxes) else []
            for i, s in enumerate(scores):
                dets[-len(scores) + i].append(float(s))
    if not dets:
        return np.zeros((0, 5))
    return np.array([d for d in dets if len(d) == 5], dtype=np.float32)


def nms(dets, iou_thr=0.45):
    if len(dets) == 0:
        return dets
    boxes = torch.tensor(dets[:, :4])
    scores = torch.tensor(dets[:, 4])
    from torchvision.ops import nms as tvnms
    keep = tvnms(boxes, scores, iou_thr).numpy()
    return dets[keep]


def footprint(x0, y0, x1, y1):
    w = max(1, int(round((x1 - x0) / CELL)))
    h = max(1, int(round((y1 - y0) / CELL)))
    return w, h


# the detector over-triggers on empty cells, whole panels and UI chrome; these
# post-filters drop those before identification. Calibrated @ 2560x1440.
OCC_STD = 12.0          # crop interior std below this == empty cell
MAX_CELLS_W, MAX_CELLS_H = 6, 5   # bigger than any single item == a panel
INV_TOP, INV_BOTTOM = 40, 1095    # ignore top tabs + bottom quick-use bar


def keep_box(gray, x0, y0, x1, y1):
    """Reject empty cells, panel-sized boxes, degenerate slivers, and chrome."""
    bw, bh = x1 - x0, y1 - y0
    if bw < CELL * 0.6 or bh < CELL * 0.6:        # sub-cell sliver
        return False
    if bw > CELL * (MAX_CELLS_W + 0.5) or bh > CELL * (MAX_CELLS_H + 0.5):
        return False                               # whole-panel detection
    cy = (y0 + y1) / 2
    if cy < INV_TOP or cy > INV_BOTTOM:            # tabs / quick-use bar
        return False
    m = 6
    patch = gray[int(y0) + m:int(y1) - m, int(x0) + m:int(x1) - m]
    return bool(patch.size) and patch.std() > OCC_STD   # has real content


CONFIDENT = 170    # match distance below this = name we trust; above = uncertain


def refine(pil, x0, y0, x1, y1):
    """Slide a small offset/footprint window and keep the alignment that
    MINIMIZES match distance -- corrects loose YOLO boxes before naming.
    Returns (dist, item, w, h)."""
    we = max(1, int(round((x1 - x0) / CELL)))
    he = max(1, int(round((y1 - y0) / CELL)))
    best = None
    for w in range(max(1, we - 1), we + 2):
        for h in range(max(1, he - 1), he + 2):
            for dx in range(-14, 15, 7):
                for dy in range(-14, 15, 7):
                    cx0, cy0 = int(x0) + dx, int(y0) + dy
                    crop = pil.crop((cx0, cy0, cx0 + w * CELL, cy0 + h * CELL))
                    r = identify.identify(crop, w, h, topn=8)
                    if r and (best is None or r[0][0] < best[0][0][0]):
                        best = (r, w, h, cx0, cy0)
    cands, w, h, cx0, cy0 = best
    return cands, w, h, cx0, cy0


def name_box(pil, x0, y0, x1, y1):
    """Classify a detected box. Tries the estimated footprint and its neighbours
    (loose YOLO boxes mis-estimate cell count) and keeps the highest-prob name.
    Returns (item, prob, w, h)."""
    crop = pil.crop((int(x0) + 2, int(y0) + 2, int(x1) - 2, int(y1) - 2))
    we = max(1, int(round((x1 - x0) / CELL)))
    he = max(1, int(round((y1 - y0) / CELL)))
    best = None
    for w in sorted({max(1, we - 1), we, we + 1}):
        for h in sorted({max(1, he - 1), he, he + 1}):
            it, p = cls.classify(crop, w, h, topn=1)[0]
            if best is None or p > best[1]:
                best = (it, p, w, h)
    return best


def ocr_prep(crop, scale=6, thr=115):
    """Enhance a small in-game text strip for OCR (same recipe as analyze.py)."""
    g = ImageOps.autocontrast(ImageOps.grayscale(crop), cutoff=2)
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    return g.point(lambda p: 255 if p > thr else 0).convert("RGBA")


def ocr_rerank(candidates, ocr_text):
    """Re-rank (dist,item) candidates by fuzzy match of OCR text to item names.
    The game prints the item name on the box -> reliable disambiguation."""
    q = "".join(ch for ch in ocr_text.lower() if ch.isalnum())
    if len(q) < 2:
        return candidates[0]
    best, best_score = candidates[0], -1
    for dist, it in candidates:
        for field in (it["shortName"], it["name"]):
            t = "".join(ch for ch in field.lower() if ch.isalnum())
            if not t:
                continue
            ratio = difflib.SequenceMatcher(None, q, t).ratio()
            if q in t or t in q:
                ratio = max(ratio, 0.85)
            score = ratio - dist / 2000.0
            if score > best_score:
                best, best_score = (dist, it), score
    return best if best_score > 0.45 else candidates[0]


def read_name(pil, x0, y0, x1):
    """OCR the name the game prints along the top of an item box."""
    if ocrmod is None:
        return ""
    strip = pil.crop((x0 + 1, y0 + 1, x1 - 1, y0 + 22))
    try:
        return ocrmod.ocr(ocr_prep(strip))
    except Exception:
        return ""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else "test screenshot 1.png"
    conf = arg("--conf", 0.25)
    if not os.path.exists(WEIGHTS):
        print(f"no weights at {WEIGHTS} -- train first (python train_yolo.py)")
        return
    pil = Image.open(path).convert("RGB")
    import cv2
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
    model = YOLO(WEIGHTS)

    dets = nms(tiled_detect(model, pil, conf))
    n_raw = len(dets)
    dets = np.array([d for d in dets if keep_box(gray, *d[:4])]) if len(dets) else dets
    print(f"{n_raw} raw boxes -> {len(dets)} after filtering "
          f"(empty cells / panels / chrome removed)\n")

    raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("lastLowPrice")
                           or it.get("basePrice") or 0) for it in raw}

    found = []
    for x0, y0, x1, y1, score in dets:
        it, prob, w, h = name_box(pil, x0, y0, x1, y1)
        sure = prob >= PROB_OK
        found.append((it["shortName"] if sure else "?", w, h, prob, float(score),
                      price_of.get(it["id"], 0) if sure else 0, sure,
                      (int(x0), int(y0), int(x1), int(y1))))

    found.sort(key=lambda r: (r[6], r[5]), reverse=True)
    named = [r for r in found if r[6]]
    print(f"{'item':<18}{'WxH':<6}{'prob':>6}{'yolo':>6}{'price':>11}")
    print("-" * 47)
    total = 0
    for sn, w, h, prob, sc, price, sure, _ in found:
        total += price
        print(f"{sn:<18}{f'{w}x{h}':<6}{prob:>6.2f}{sc:>6.2f}{price:>11,}")
    print("-" * 47)
    print(f"{len(found)} item boxes ({len(named)} named, "
          f"{len(found) - len(named)} uncertain) | est. total ~{total:,} RUB "
          f"(named only)")

    import cv2
    overlay = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    for sn, w, h, prob, sc, price, sure, (x0, y0, x1, y1) in found:
        col = (0, 220, 0) if sure else (0, 140, 255)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), col, 2)
        cv2.putText(overlay, sn[:14] if sure else "?", (x0 + 2, y0 + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 255, 255), 1, cv2.LINE_AA)
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, "detect_items.png"), overlay)
    print(f"-> {OUT}/detect_items.png  (green=named, orange=uncertain)")


if __name__ == "__main__":
    main()
