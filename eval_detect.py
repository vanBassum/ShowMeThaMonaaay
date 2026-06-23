"""
Detection-only evaluation: run the trained YOLO detector over a screenshot and
draw the raw boxes — no classifier needed. Lets us judge detection quality
(recall, panel/oversized boxes, merges, misses) in isolation.

Run:  python eval_detect.py [path] [--conf 0.25]
      -> out/eval_detect.png  + printed box stats
"""
import os
import sys
import numpy as np
import cv2
from PIL import Image

from detect_items import (get_model, tiled_detect, nms, keep_box,
                          MAX_BOX_FRAC, IMGSZ)

ROOT = os.path.dirname(__file__)
OUT = os.path.join(ROOT, "out")


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else os.path.join(OUT, "last_scan.png")
    conf = arg("--conf", 0.25)
    pil = Image.open(path).convert("RGB")
    W, H = pil.size
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)

    raw = nms(tiled_detect(get_model(), pil, conf))
    kept = [d for d in raw if keep_box(gray, *d[:4], W, H)]
    dropped = len(raw) - len(kept)

    overlay = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    areas = []
    for x0, y0, x1, y1, s in kept:
        cv2.rectangle(overlay, (int(x0), int(y0)), (int(x1), int(y1)), (0, 220, 0), 2)
        cv2.putText(overlay, f"{s:.2f}", (int(x0) + 2, int(y0) + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 255, 255), 1, cv2.LINE_AA)
        areas.append((x1 - x0) * (y1 - y0))

    os.makedirs(OUT, exist_ok=True)
    outp = os.path.join(OUT, "eval_detect.png")
    cv2.imwrite(outp, overlay)

    areas = np.array(areas) if areas else np.zeros(1)
    big = int((areas > MAX_BOX_FRAC * W * H * 0.5).sum())  # near-panel-sized
    print(f"image {W}x{H} @ imgsz={IMGSZ} conf={conf}")
    print(f"raw boxes {len(raw)} | kept {len(kept)} | dropped by filters {dropped}")
    print(f"box area px: median {np.median(areas):.0f}  max {areas.max():.0f}  "
          f"(image {W*H}); near-panel-sized kept: {big}")
    print(f"-> {outp}")


if __name__ == "__main__":
    main()
