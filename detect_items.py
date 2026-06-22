"""
Grid-free item finder: YOLO detects item boxes anywhere on screen, the CNN
classifier names each crop. No cell grid, no footprint math, no resolution
assumptions -- the detector is scale-invariant (trained across cell sizes) and
the classifier letterboxes each crop, so this works at any resolution.

  screenshot -> YOLO (tiled) -> boxes -> letterbox-crop -> classify -> list

Boxes whose name is below the confidence gate are reported as '?' rather than
guessed wrong. Sanity filters (relative size + region + occupancy) drop the few
non-item boxes (panels, UI chrome, empty space) and are expressed as fractions
of image size, so they hold at any resolution.

Run:  python detect_items.py "test screenshot 1.png" [--conf 0.25]
"""
import os
import sys
import json
import numpy as np
import torch
from PIL import Image
from ultralytics import YOLO

import cls

ROOT = os.path.dirname(__file__)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")
WEIGHTS = os.path.join(ROOT, "runs", "detect", "items", "weights", "best.pt")
TILE, STRIDE = 640, 512            # overlapping tiles (input resolution, not grid)

PROB_OK = 0.40                     # classifier prob above this == trust the name
MAX_BOX_FRAC = 0.45                # box bigger than this fraction of the image = panel
MIN_BOX_PX = 14                    # ignore sub-tiny boxes
TOP_FRAC, BOT_FRAC = 0.025, 0.86   # ignore top tabs / bottom quick-use bar
OCC_STD = 11.0                     # crop interior std below this == empty/flat


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def tiled_detect(model, pil, conf):
    """Detect over overlapping tiles; return (N,5) [x0,y0,x1,y1,score] in full coords."""
    W, H = pil.size
    dets = []
    xs = sorted(set(list(range(0, max(1, W - TILE) + 1, STRIDE)) + [max(0, W - TILE)]))
    ys = sorted(set(list(range(0, max(1, H - TILE) + 1, STRIDE)) + [max(0, H - TILE)]))
    for y in ys:
        for x in xs:
            tile = pil.crop((x, y, min(x + TILE, W), min(y + TILE, H)))
            res = model.predict(tile, conf=conf, imgsz=TILE, verbose=False)[0]
            xary = res.boxes.xyxy.cpu().numpy()
            sary = res.boxes.conf.cpu().numpy()
            for (x0, y0, x1, y1), s in zip(xary, sary):
                dets.append([x0 + x, y0 + y, x1 + x, y1 + y, float(s)])
    return np.array(dets, dtype=np.float32) if dets else np.zeros((0, 5), np.float32)


def nms(dets, iou_thr=0.45):
    if len(dets) == 0:
        return dets
    from torchvision.ops import nms as tvnms
    keep = tvnms(torch.tensor(dets[:, :4]), torch.tensor(dets[:, 4]), iou_thr).numpy()
    return dets[keep]


def keep_box(gray, x0, y0, x1, y1, W, H):
    """Resolution-independent sanity: drop slivers, panel-sized boxes, UI chrome
    rows, and flat/empty boxes."""
    bw, bh = x1 - x0, y1 - y0
    if bw < MIN_BOX_PX or bh < MIN_BOX_PX:
        return False
    if bw * bh > MAX_BOX_FRAC * W * H:
        return False
    cy = (y0 + y1) / 2
    if cy < TOP_FRAC * H or cy > BOT_FRAC * H:
        return False
    m = max(3, int(min(bw, bh) * 0.12))
    patch = gray[int(y0) + m:int(y1) - m, int(x0) + m:int(x1) - m]
    return bool(patch.size) and patch.std() > OCC_STD


WEAPON_TYPES = {"gun", "preset"}
_MODEL = None
_IDX = None


def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = YOLO(WEIGHTS)
    return _MODEL


def item_index():
    global _IDX
    if _IDX is None:
        raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
        _IDX = {it["id"]: it for it in raw}
    return _IDX


def scan_pil(pil, conf=0.25):
    """Detect + name every item. Returns a list of dicts:
    id, name, shortName, prob, score, w, h, slots, price, perslot, weapon,
    sure, icon, box. Slots come from the matched item's DB footprint (grid-free)."""
    pil = pil.convert("RGB")
    import cv2
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
    W, H = pil.size
    dets = nms(tiled_detect(get_model(), pil, conf))
    dets = [d for d in dets if keep_box(gray, *d[:4], W, H)]
    idx = item_index()
    out = []
    for x0, y0, x1, y1, score in dets:
        crop = pil.crop((int(x0), int(y0), int(x1), int(y1)))
        ba = (x1 - x0) / max(1.0, (y1 - y0))
        it, prob = cls.classify(crop, topn=1, box_aspect=ba)[0]
        meta = idx.get(it["id"], it)
        w, h = meta.get("width", 1), meta.get("height", 1)
        slots = max(1, w * h)
        price = (meta.get("avg24hPrice") or meta.get("lastLowPrice")
                 or meta.get("basePrice") or 0)
        out.append({
            "id": it["id"], "name": meta.get("name", it["id"]),
            "shortName": meta.get("shortName", it["id"]),
            "prob": round(prob, 3), "score": round(float(score), 3),
            "w": w, "h": h, "slots": slots, "price": price,
            "perslot": price // slots,
            "weapon": bool(set(meta.get("types") or []) & WEAPON_TYPES),
            "sure": prob >= PROB_OK,
            "icon": os.path.join(DATA, "icons", it["id"] + ".webp"),
            "box": (int(x0), int(y0), int(x1), int(y1))})
    return out


def draw_overlay(pil, items):
    import cv2
    overlay = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    for x in items:
        x0, y0, x1, y1 = x["box"]
        col = (0, 220, 0) if x["sure"] else (0, 140, 255)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), col, 2)
        cv2.putText(overlay, x["shortName"][:14] if x["sure"] else "?",
                    (x0 + 2, y0 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (60, 255, 255), 1, cv2.LINE_AA)
    return overlay


def main():
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else "test screenshot 1.png"
    conf = arg("--conf", 0.25)
    if not os.path.exists(WEIGHTS):
        print(f"no weights at {WEIGHTS} -- train first (python train_yolo.py)")
        return
    import cv2
    pil = Image.open(path).convert("RGB")
    items = scan_pil(pil, conf)
    items.sort(key=lambda x: (x["sure"], x["price"]), reverse=True)
    named = [x for x in items if x["sure"]]

    print(f"{'item':<20}{'prob':>6}{'yolo':>6}{'WxH':>6}{'price':>11}")
    print("-" * 49)
    total = 0
    for x in items:
        total += x["price"] if x["sure"] else 0
        sn = x["shortName"] if x["sure"] else "?"
        wh = f"{x['w']}x{x['h']}"
        price = x["price"] if x["sure"] else 0
        print(f"{sn:<20}{x['prob']:>6.2f}{x['score']:>6.2f}{wh:>6}{price:>11,}")
    print("-" * 49)
    print(f"{len(items)} item boxes ({len(named)} named, {len(items)-len(named)} "
          f"uncertain) | est. total ~{total:,} RUB (named only)")

    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, "detect_items.png"), draw_overlay(pil, items))
    print(f"-> {OUT}/detect_items.png  (green=named, orange=uncertain)")


if __name__ == "__main__":
    main()
