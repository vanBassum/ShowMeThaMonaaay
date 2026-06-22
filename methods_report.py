"""
Per-method classification report for one screenshot.

Detects items (grid-free YOLO), then for every box runs all four classifiers
independently and emits:
  * out/method_cnn.png / method_ocr.png / method_phash.png / method_orb.png
    -- the screenshot with each box labelled by THAT method's top guess + %.
  * out/methods.txt -- one row per box: location + each method's guess & certainty.

Run:  python methods_report.py "test screenshot 1.png"
"""
import os
import sys
import numpy as np
import cv2
from PIL import Image

import detect_items as D
import compare as C

OUT = D.OUT
ICONS = C.ICONS


def top1(scores):
    """(item_id, score) for the highest-scoring candidate, or (None, 0)."""
    if not scores:
        return None, 0.0
    i = max(scores, key=scores.get)
    return i, scores[i]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "test screenshot 1.png"
    pil = Image.open(path).convert("RGB")
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
    W, H = pil.size
    byid = C.phash_db()["byid"]
    allitems = list(byid.values())

    dets = D.nms(D.tiled_detect(D.get_model(), pil, 0.25))
    dets = [d for d in dets if D.keep_box(gray, *d[:4], W, H)]
    print(f"{len(dets)} boxes")

    methods = ["cnn", "ocr", "phash", "orb"]
    # per box: {method: (item_id, score)}
    rows = []
    for x0, y0, x1, y1, sc in dets:
        crop = pil.crop((int(x0), int(y0), int(x1), int(y1)))
        aspect = (x1 - x0) / max(1.0, (y1 - y0))
        cnn = C.cnn_scores(crop, aspect, k=10)
        ph = C.phash_scores(crop, k=10)
        oc, _ = C.ocr_scores(crop, allitems)
        shortlist = set(cnn) | set(ph) | set(oc)
        orb = {i: C.orb_score(crop, os.path.join(ICONS, i + ".webp")) for i in shortlist}
        res = {"cnn": top1(cnn), "ocr": top1(oc), "phash": top1(ph), "orb": top1(orb)}
        rows.append(((int(x0), int(y0), int(x1), int(y1)), res))

    # 4 overlays, one per method
    base = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    for m in methods:
        ov = base.copy()
        for (x0, y0, x1, y1), res in rows:
            iid, s = res[m]
            label = (byid[iid]["shortName"][:12] + f" {int(s*100)}%") if iid and s > 0 else "-"
            col = (0, 200, 0) if s >= 0.45 else ((0, 165, 255) if s > 0 else (90, 90, 90))
            cv2.rectangle(ov, (x0, y0), (x1, y1), col, 2)
            cv2.putText(ov, label, (x0 + 2, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (60, 255, 255), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(OUT, f"method_{m}.png"), ov)

    # comparison table
    def cell(res, m):
        iid, s = res[m]
        return f"{byid[iid]['shortName'][:14]} {int(s*100)}%" if iid and s > 0 else "-"
    lines = [f"{'#':<3}{'location(x,y,w,h)':<22}{'CNN':<20}{'OCR':<20}"
             f"{'pHash':<20}{'ORB':<20}"]
    for j, ((x0, y0, x1, y1), res) in enumerate(rows):
        loc = f"({x0},{y0},{x1-x0},{y1-y0})"
        lines.append(f"{j:<3}{loc:<22}{cell(res,'cnn'):<20}{cell(res,'ocr'):<20}"
                     f"{cell(res,'phash'):<20}{cell(res,'orb'):<20}")
    with open(os.path.join(OUT, "methods.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("-> out/method_{cnn,ocr,phash,orb}.png + out/methods.txt")


if __name__ == "__main__":
    main()
