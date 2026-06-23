"""
server.py — local backend for the review/correct UI.

  screenshot --(mask front-end)--> detect (YOLO) --> classify each crop
            (CNN top-5 + gap-immune OCR of the printed name) --> JSON
            --> UI shows boxes, you relabel the wrong ones --> save

Detection runs on the MASKED image (the detector is trained on black-bg);
classification crops come from the ORIGINAL pixels. Structural flukes are
dropped by detect_items.keep_box; low-confidence items are flagged 'uncertain'
(NOT hard-rejected — the icon→game gap makes confidence unreliable, so the human
corrects them).

Run:  python server.py     then open http://127.0.0.1:5000
"""
import difflib
import json
import os
import time

import numpy as np
import cv2
from flask import Flask, request, jsonify, send_file, Response
from PIL import Image

import detect_items as di
import cls
import ocr as ocrmod
import mask_pipeline as mp
import retrieval

RET_OK = 0.80          # cosine sim to a gallery crop above this == trust retrieval

ROOT = os.path.dirname(__file__)
DATA = os.path.join(ROOT, "data")
ICONS = os.path.join(DATA, "icons")
SESS = os.path.join(ROOT, "sessions")
GALLERY = os.path.join(ROOT, "gallery")
GCROPS = os.path.join(GALLERY, "crops")
GLABELS = os.path.join(GALLERY, "labels.json")
os.makedirs(SESS, exist_ok=True)
os.makedirs(GCROPS, exist_ok=True)

app = Flask(__name__, static_folder=None)
_ITEMS = None
_NORM = None
_BYID = None


def items_list():
    global _ITEMS, _NORM, _BYID
    if _ITEMS is None:
        raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
        _ITEMS = [it for it in raw if it.get("gridImageLink")]
        _NORM = [( (it.get("shortName", "") + " " + it.get("name", "")).lower(), it)
                 for it in _ITEMS]
        _BYID = {it["id"]: it for it in _ITEMS}
    return _ITEMS


def cand_dict(it, prob, src):
    return {"id": it["id"], "short": it.get("shortName", ""),
            "name": it.get("name", ""), "prob": round(float(prob), 3), "src": src}


def price_of(it):
    return (it.get("avg24hPrice") or it.get("lastLowPrice")
            or it.get("basePrice") or 0)


def match_ocr(text):
    """Fuzzy-match an OCR string to an item by name/shortName. Returns (item,
    score) or None. OCR of the game's printed name is gap-immune, so a strong
    match is high-precision."""
    t = "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()
    if len(t) < 2:
        return None
    best, bs = None, 0.0
    for norm, it in _NORM:
        for cand in (it.get("shortName", "").lower(), it.get("name", "").lower()):
            if len(cand) < 3:
                continue
            r = difflib.SequenceMatcher(None, t, cand).ratio()
            # substring boost only for reasonably long candidates, so a 2-3 char
            # short name (e.g. "DE") can't match inside any longer OCR string
            if len(cand) >= 5 and (t in cand or cand in t):
                r = max(r, 0.85)
            if r > bs:
                bs, best = r, it
    return (best, bs) if bs >= 0.8 else None


def scan(image_name, conf=0.25):
    path = os.path.join(ROOT, image_name)
    img = Image.open(path).convert("RGB")
    W, H = img.size
    items_list()

    masked, _ = mp.build_masked(img)
    model = di.get_model()
    gray = cv2.cvtColor(np.asarray(masked), cv2.COLOR_RGB2GRAY)
    dets = di.nms(di.tiled_detect(model, masked, conf))
    dets = [d for d in dets if di.keep_box(gray, *d[:4], W, H)]

    out = []
    for x0, y0, x1, y1, score in dets:
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        crop = img.crop((x0, y0, x1, y1))
        ar = (x1 - x0) / max(1.0, (y1 - y0))
        cands = cls.classify(crop, topn=5, box_aspect=ar)
        otext = ocrmod.ocr(ocrmod.prep(crop)).strip()
        om = match_ocr(otext)
        ret = retrieval.query(crop, topk=3)               # [(item_id, sim)] over real gallery
        ret_best = ret[0] if ret else None

        top_it, top_p = cands[0]
        # vote priority: OCR (gap-immune) > retrieval (game→game) > CNN
        if om and om[1] >= 0.8:
            chosen, status, src, conf = om[0], "sure", "ocr", om[1]
        elif ret_best and ret_best[1] >= RET_OK:
            chosen, status, src, conf = _BYID[ret_best[0]], "sure", "retrieval", ret_best[1]
        elif top_p >= di.PROB_OK:
            chosen, status, src, conf = top_it, "sure", "cnn", top_p
        elif ret_best and ret_best[1] >= 0.55:
            chosen, status, src, conf = _BYID[ret_best[0]], "uncertain", "retrieval", ret_best[1]
        else:
            chosen, status, src, conf = top_it, "uncertain", "cnn", top_p

        # candidates: chosen first (so the UI pre-selects the AI's pick), then
        # retrieval matches, then CNN top-5; deduped.
        cand_out, seen = [], set()
        def add(it_, prob, tag):
            if it_ and it_["id"] not in seen:
                seen.add(it_["id"]); cand_out.append(cand_dict(it_, prob, tag))
        add(chosen, conf, src)
        for iid, s in ret:
            add(_BYID.get(iid), s, "retrieval")
        for it_, p in cands:
            add(it_, p, "cnn")

        w, h = chosen.get("width", 1), chosen.get("height", 1)
        out.append({
            "box": [x0, y0, x1, y1], "score": round(float(score), 3),
            "id": chosen["id"], "name": chosen.get("name", chosen["id"]),
            "short": chosen.get("shortName", chosen["id"]),
            "prob": round(float(conf), 3), "ocr": otext, "src": src, "status": status,
            "price": price_of(chosen), "slots": max(1, w * h),
            "candidates": cand_out,
        })
    return {"image": {"name": image_name, "width": W, "height": H}, "items": out}


# ---- routes ----
@app.route("/")
def index():
    return send_file(os.path.join(ROOT, "index.html"))


@app.route("/api/image")
def api_image():
    name = request.args.get("name", "test screenshot 1.png")
    p = os.path.join(ROOT, name)
    return send_file(p) if os.path.exists(p) else ("not found", 404)


@app.route("/api/icon")
def api_icon():
    iid = request.args.get("id", "")
    p = os.path.join(ICONS, iid + ".webp")
    return send_file(p) if os.path.exists(p) else ("", 404)


@app.route("/api/scan")
def api_scan():
    name = request.args.get("image", "test screenshot 1.png")
    key = name.replace("/", "_").replace(".", "_")
    cache = os.path.join(SESS, key + ".scan.json")
    corrected = os.path.join(SESS, key + ".corrected.json")
    force = request.args.get("force") == "1"
    if not force:
        # prefer the corrected session (restores prior edits), then the scan cache
        for p in (corrected, cache):
            if os.path.exists(p):
                return Response(open(p, encoding="utf-8").read(), mimetype="application/json")
    res = scan(name, float(request.args.get("conf", 0.25)))
    json.dump(res, open(cache, "w"))
    return jsonify(res)


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip().lower()
    items_list()
    if not q:
        return jsonify([])
    scored = []
    for norm, it in _NORM:
        if q in norm:
            scored.append((norm.index(q), it))
    scored.sort(key=lambda s: s[0])
    return jsonify([{"id": it["id"], "short": it.get("shortName", ""),
                     "name": it.get("name", ""), "price": price_of(it)}
                    for _, it in scored[:25]])


def _trusted(it):
    """High-precision labels only: user-corrected, or OCR-sure (OCR of the printed
    name is gap-immune). Keeps the gallery clean of the model's shaky guesses."""
    return bool(it.get("corrected")) or (it.get("status") == "sure" and it.get("src") == "ocr")


def bank_gallery(data):
    """Bank each TRUSTED box as a real (crop, item_id) pair into the gallery,
    keyed by (image, box) so re-saving updates labels instead of duplicating.
    Untouched/uncertain/fluke boxes are NOT banked (and removed if present)."""
    img_name = data.get("image", {}).get("name", "")
    path = os.path.join(ROOT, img_name)
    if not os.path.exists(path):
        return 0, 0
    img = Image.open(path).convert("RGB")
    stem = os.path.splitext(os.path.basename(img_name))[0].replace(" ", "_")
    labels = json.load(open(GLABELS, encoding="utf-8")) if os.path.exists(GLABELS) else {}
    banked = 0
    for it in data.get("items", []):
        x0, y0, x1, y1 = it["box"]
        key = f"{stem}__{x0}_{y0}_{x1}_{y1}"
        if not _trusted(it):
            labels.pop(key, None)
            cf = os.path.join(GCROPS, key + ".png")
            if os.path.exists(cf):
                os.remove(cf)
            continue
        img.crop((x0, y0, x1, y1)).save(os.path.join(GCROPS, key + ".png"))
        labels[key] = {"crop": key + ".png", "item_id": it["id"],
                       "short": it.get("short", ""), "name": it.get("name", ""),
                       "status": it.get("status"), "src": it.get("src"),
                       "corrected": bool(it.get("corrected")), "prob": it.get("prob"),
                       "ocr": it.get("ocr", ""), "image": img_name, "box": it["box"],
                       "ts": int(time.time())}
        banked += 1
    json.dump(labels, open(GLABELS, "w"), indent=1)
    return banked, len(labels)


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    name = data.get("image", {}).get("name", "session")
    p = os.path.join(SESS, name.replace("/", "_").replace(".", "_") + ".corrected.json")
    json.dump(data, open(p, "w"), indent=1)
    banked, total = bank_gallery(data)
    return jsonify({"ok": True, "saved": os.path.basename(p),
                    "corrected": sum(1 for it in data.get("items", []) if it.get("corrected")),
                    "banked": banked, "gallery_total": total})


if __name__ == "__main__":
    print("open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
