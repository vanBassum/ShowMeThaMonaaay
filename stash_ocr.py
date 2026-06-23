"""
Stash-only auto-labeller via OCR. OCR the whole stash region once (word boxes),
treat each printed name as an item anchor at its top-left cell, snap to the grid
(pitch from calibration, ORIGIN derived from the name positions themselves --
robust to grid-calibration offset), fuzzy-match text to items.json. The matched
item's width/height gives the box footprint.

No icon matching, no domain gap; text disambiguates same-icon families (keys).
Writes out/last_scan.labels.json + an overlay for verification.
"""
import os, json, re, difflib, statistics, numpy as np, cv2
from PIL import Image
import stashgrid, ocr

DATA = "data"
SCALE = 3


def build_index():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    by = {}
    for it in items:
        sn = it.get("shortName", "").strip().lower()
        if sn:
            by.setdefault(sn, it)
    return by, list(by.keys())


def clean(tok):
    t = tok.replace("Ø", "0").replace("—", "").strip()
    if len(t) < 2 or re.fullmatch(r"[0-9/x.,\-]+", t):   # number/durability/junk
        return ""
    return t


def main():
    pil = Image.open("out/last_scan.png").convert("RGB")
    rgb = np.array(pil); gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    region = (int(0.638 * W), int(0.085 * H), int(0.995 * W), int(0.56 * H))
    pitch = stashgrid.calibrate(gray, region)["pitch"]
    by, names = build_index()

    words = ocr.ocr_words(ocr.prep(pil.crop(region), scale=SCALE))
    anchors = []                                  # (left, top, text) in full coords
    for text, wx, wy, ww, wh in words:
        tok = clean(text)
        if not tok:
            continue
        anchors.append((region[0] + wx / SCALE, region[1] + wy / SCALE, tok))
    if not anchors:
        print("no name words"); return

    # origin = modal phase of the name positions (names share a constant margin)
    ox = statistics.median(l % pitch for l, _, _ in anchors)
    oy = statistics.median(t % pitch for _, t, _ in anchors)

    # group anchors by cell (a multi-word name lands in one cell)
    cells = {}
    for l, t, tok in anchors:
        c = round((l - ox) / pitch); r = round((t - oy) / pitch)
        cells.setdefault((r, c), []).append((l, tok))

    ov = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    labels = []
    for (r, c), toks in sorted(cells.items()):
        phrase = " ".join(tok for _, tok in sorted(toks)).lower()
        hit = difflib.get_close_matches(phrase, names, n=1, cutoff=0.5)
        cx = int(ox + c * pitch) - 3; cy = int(oy + r * pitch) - 3
        if hit:
            it = by[hit[0]]; w, h = it.get("width", 1), it.get("height", 1)
            sc = difflib.SequenceMatcher(None, phrase, hit[0]).ratio()
            box = [cx, cy, cx + w * pitch, cy + h * pitch]
            labels.append({"row": r, "col": c, "ocr": phrase, "id": it["id"],
                           "shortName": it["shortName"], "score": round(sc, 2),
                           "w": w, "h": h, "box": box})
            cv2.rectangle(ov, (box[0], box[1]), (box[2], box[3]), (0, 210, 0), 2)
            cv2.putText(ov, it["shortName"][:11], (cx + 2, cy + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 255, 120), 1, cv2.LINE_AA)
        else:
            cv2.putText(ov, phrase[:11] + "?", (cx + 2, cy + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 160, 255), 1, cv2.LINE_AA)
            labels.append({"row": r, "col": c, "ocr": phrase, "id": None,
                           "shortName": None, "score": 0.0, "w": 1, "h": 1,
                           "box": [cx, cy, cx + pitch, cy + pitch]})

    matched = sum(1 for x in labels if x["id"])
    print(f"name anchors: {len(anchors)} | cells: {len(cells)} | matched: {matched}")
    for x in sorted(labels, key=lambda z: (z["row"], z["col"])):
        print(f"({x['row']},{x['col']})  {x['ocr'][:16]:18s}-> {str(x['shortName'])[:15]:16s}{x['score']}")
    payload = {"image": "out/last_scan.png", "items": labels}
    # auto file is always overwritten; truth file is yours to edit (never clobbered)
    json.dump(payload, open("out/last_scan.auto.json", "w"), indent=1)
    if not os.path.exists("out/last_scan.truth.json"):
        json.dump(payload, open("out/last_scan.truth.json", "w"), indent=1)
        print("seeded out/last_scan.truth.json (edit this one)")
    print("-> out/last_scan.auto.json (+ truth.json). Run label_viewer.py to view.")


if __name__ == "__main__":
    main()
