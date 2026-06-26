"""
scan.py — runtime scan pipeline: screenshot -> ranked items by price-per-slot.

Fusion (keeps YOLO and OCR doing their own jobs):
  YOLO (active model) -> WHERE each item is (boxes) + icon-id.
  OCR reads ONLY inside each box -> the printed name -> catalog item (price, size).
This restricts OCR to real item locations, killing the false matches you get when
OCR reads the whole screen (trader text, tooltips, etc.).

price-per-slot = value / (width*height), both from the catalog once identified, so
it's exact and resolution-independent.

CLI test (no F2 / capture needed):
  python app/scan.py sessions/20260623-182907/raw.png
  python app/scan.py shot.png --model shared/models/best.pt --conf 0.25
"""
import os, sys, json, time, argparse
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for sibling imports
from ocr_identify import ocr_words, match_name  # noqa: E402
from backend import models  # noqa: E402  (model packages: weights + link map)

DEFAULT_MODEL = "shared/models/best.pt"   # barry v3 (active)

# The icon-id -> item link map (visual matcher), manual overrides, and the baseline
# correction log all ship INSIDE the active model's package (the icon-id set is
# model-specific). This is what lets YOLO NAME an item, not just locate it — it's
# PREFERRED over OCR when its match is confident. Catalog/prices (items.json) are
# model-independent and stay in data/.
ITEMS_PATH = "data/items.json"
_MODEL = models.DEFAULT


def use_model(name):
    """Point the identity sources at model `name`'s package and drop the cached link
    projection. Call this when the active detector model changes."""
    global _MODEL, _LINK
    if name and name != _MODEL:
        _MODEL = name
        _LINK = None


def _links_dir():
    return models.links_dir(_MODEL)


_LINK = _CAT = None

# The visual icon-id->item map is often right on the ICON but wrong on the ITEM when
# its match is ambiguous. Turn its score/margin into a 0..1 certainty and prefer
# whichever source (icon-map vs OCR) is more certain. Tunables:
MARGIN_FULL = 5.0    # icon-map margin (gap to 2nd best) giving full confidence
SCORE_GOOD = 12.0    # L2 distance <= this = great visual match
SCORE_BAD = 40.0     # L2 distance >= this = poor visual match


def yolo_certainty(meta):
    """0..1 confidence that the icon-id->item map is correct for this icon."""
    if meta.get("override"):
        return 1.0                                   # manual link = fully trusted
    m, s = meta.get("margin"), meta.get("score")
    if m is None or s is None:
        return 0.5
    margin_c = max(0.0, min(1.0, m / MARGIN_FULL))   # ambiguous (low margin) -> low
    score_c = max(0.0, min(1.0, (SCORE_BAD - s) / (SCORE_BAD - SCORE_GOOD)))
    return round(margin_c * score_c, 3)


def _jload(p, d):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d


def _events_from(p):
    """Read an append-only link event log (one JSON object per line); [] if absent."""
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _events():
    """Manual-correction events shipped in the model package (read-only baseline)."""
    return _events_from(str(_links_dir() / "links.jsonl"))


def _link_map():
    """Resolved icon-id(str) -> {item_id, score, margin, override}. Projection over:
    auto visual matcher, then manual sources (flat overrides + event log) which win.
    The event log is append-only; the LATEST manual event per icon takes effect."""
    global _LINK
    if _LINK is None:
        links = _links_dir()
        auto = _jload(str(links / "icon_item_map.json"), {})      # visual matcher (package)
        _LINK = {k: {"item_id": v.get("item_id"), "score": v.get("score"),
                     "margin": v.get("margin")}
                 for k, v in auto.items() if v.get("item_id")}
        for k, iid in _jload(str(links / "icon_overrides.json"), {}).items():  # flat manual
            _LINK[k] = {"item_id": iid, "score": None, "margin": None, "override": True}
        for ev in _events():                                      # event-sourced manual
            if ev.get("source") == "manual" and ev.get("item_id"):
                _LINK[str(ev["icon_id"])] = {"item_id": ev["item_id"], "score": None,
                                             "margin": None, "override": True}
    return _LINK


def _catalog():
    global _CAT
    if _CAT is None:
        _CAT = {it["id"]: it for it in _jload(ITEMS_PATH, [])}
    return _CAT


def catalog_age():
    """Seconds since the price/metadata cache (items.json) was last written."""
    return time.time() - os.path.getmtime(ITEMS_PATH) if os.path.exists(ITEMS_PATH) else float("inf")


def invalidate_catalog():
    """Drop the in-memory catalog so the next lookup reloads fresh prices from disk."""
    global _CAT
    _CAT = None


def search_items(q, limit=25):
    """Search the catalog by name/short for the manual-correction picker."""
    q = " ".join(q.lower().split())
    if not q:
        return []
    out = []
    for it in _catalog().values():
        name, short = it["name"].lower(), (it.get("shortName") or "").lower()
        if q in name or q in short:
            out.append({"id": it["id"], "name": it["name"], "short": it.get("shortName", ""),
                        "width": it.get("width", 1) or 1, "height": it.get("height", 1) or 1,
                        "value": value_of(it)})
    out.sort(key=lambda x: (not x["short"].lower().startswith(q),
                            not x["name"].lower().startswith(q), len(x["name"])))
    return out[:limit]


PRICE_MODE = "avg24h"   # "avg24h" = flea 24h average; "low" = latest flea low (most current)


def set_price_mode(mode):
    """Choose which flea price drives valuation/ranking. Returns the mode actually set."""
    global PRICE_MODE
    PRICE_MODE = "low" if mode == "low" else "avg24h"
    return PRICE_MODE


def value_of(it):
    """Best realistic sell value (RUB). Flea price per PRICE_MODE (24h avg vs latest low,
    each falling back to the other if missing), with best vendor / base price as a floor."""
    avg, low = it.get("avg24hPrice") or 0, it.get("lastLowPrice") or 0
    flea = (low or avg) if PRICE_MODE == "low" else (avg or low)
    vendor = max([s.get("priceRUB") or 0 for s in (it.get("sellFor") or [])] + [0])
    return max(flea, vendor, it.get("basePrice") or 0)


def _name_in_box(crop, ocr_scale, name_cutoff):
    """OCR a box crop and return (item, score, raw_text). The printed name sits in
    the top strip of the cell; try that first, then fall back to all words."""
    words = ocr_words(crop, scale=ocr_scale)
    if not words:
        return None, 0.0, ""
    h = crop.height
    top = [w for w in words if (w[2] + w[4] / 2) < h * 0.45]   # word y-center in top 45%
    for group in (top, words):
        if not group:
            continue
        txt = " ".join(t for t, *_ in sorted(group, key=lambda w: w[1]))
        it, sc = match_name(txt, cutoff=name_cutoff)
        if it and sc >= name_cutoff:
            return it, sc, txt
    return None, 0.0, " ".join(t for t, *_ in words)


def _entry(it):
    """Flatten a catalog item for the valuer."""
    return {"id": it["id"], "name": it["name"], "short": it.get("shortName", ""),
            "width": it.get("width", 1) or 1, "height": it.get("height", 1) or 1}


def _resolve(det):
    """Turn one raw detection (icon_id + box + ocr fields) into a result rec, choosing
    the MORE CERTAIN identity (confident icon-match -> YOLO; ambiguous -> OCR; manual
    override always wins). Pure function of det + current link map -> re-runnable."""
    link, cat = _link_map(), _catalog()
    icon_id = str(det["icon_id"])
    meta = link.get(icon_id)
    yitem = cat.get(meta["item_id"]) if meta else None
    yc = yolo_certainty(meta) if yitem else 0.0
    yolo = ({**_entry(yitem), "score": meta.get("score"), "margin": meta.get("margin"),
             "override": meta.get("override", False), "certainty": yc} if yitem else None)

    oit = cat.get(det.get("ocr_id")) if det.get("ocr_id") else None
    oc = det.get("ocr_score", 0.0)
    ocr = {**_entry(oit), "score": oc, "raw": det.get("ocr_raw", "")} if oit else \
          {"id": "", "name": "", "short": "", "score": oc, "raw": det.get("ocr_raw", "")}

    if yitem and (not oit or yc >= oc):
        chosen = yitem
        source = "override" if (yolo and yolo["override"]) else "yolo"
        cert = yc
    elif oit:
        chosen, source, cert = oit, "ocr", oc
    else:
        chosen, source, cert = None, None, 0.0
    rec = {"box": det["box"], "icon_id": icon_id, "det_conf": det.get("det_conf"),
           "source": source, "certainty": cert, "yolo": yolo, "ocr": ocr,
           "agree": bool(yitem and oit and yitem["id"] == oit["id"])}
    if chosen:
        e = _entry(chosen)
        val = value_of(chosen)
        rec.update(e, value=val, slots=e["width"] * e["height"],
                   per_slot=round(val / (e["width"] * e["height"])))
    return rec, bool(chosen)


def project(dets):
    """Build the result dict from raw detections + the current link map. Re-runnable
    after a manual correction (no YOLO/OCR needed)."""
    items, unidentified = [], []
    for det in dets:
        rec, ok = _resolve(det)
        (items if ok else unidentified).append(rec)
    items.sort(key=lambda r: r["per_slot"], reverse=True)
    total = sum(r["value"] for r in items)
    return {"items": items, "unidentified": unidentified,
            "detections": len(dets), "identified": len(items), "total": total,
            "by_yolo": sum(1 for r in items if r["source"] == "yolo"),
            "by_ocr": sum(1 for r in items if r["source"] == "ocr"),
            "by_override": sum(1 for r in items if r["source"] == "override")}


def dets_of(result):
    """Reconstruct the raw detection list from a result (for re-projection)."""
    return [{"icon_id": r["icon_id"], "box": r["box"], "det_conf": r.get("det_conf"),
             "ocr_id": r["ocr"]["id"], "ocr_score": r["ocr"]["score"],
             "ocr_raw": r["ocr"]["raw"]}
            for r in result["items"] + result["unidentified"]]


def scan(pil, model, conf=0.25, imgsz=1536, ocr_scale=6, name_cutoff=0.6):
    """Full pipeline on a PIL image: YOLO boxes + OCR-in-box -> raw detections -> project."""
    r = model.predict(pil, imgsz=imgsz, conf=conf, max_det=400, verbose=False)[0]
    dets = []
    for b in r.boxes:
        x0, y0, x1, y1 = (round(v) for v in b.xyxy[0].tolist())
        oit, osc, raw = _name_in_box(pil.crop((x0, y0, x1, y1)), ocr_scale, name_cutoff)
        dets.append({"icon_id": str(r.names[int(b.cls)]), "box": [x0, y0, x1, y1],
                     "det_conf": round(float(b.conf), 3),
                     "ocr_id": oit["id"] if oit else "", "ocr_score": round(osc, 2),
                     "ocr_raw": raw})
    return project(dets)


def annotate(pil, res):
    """Draw boxes for later review: green=identified (+short name & ₽/slot), red=not."""
    from PIL import ImageDraw
    im = pil.copy()
    d = ImageDraw.Draw(im)
    for it in res["items"]:
        x0, y0, x1, y1 = it["box"]
        d.rectangle([x0, y0, x1, y1], outline=(0, 220, 0), width=2)
        d.text((x0 + 2, y0 + 1), f"{it['short']} {it['per_slot']:,}/sl", fill=(180, 255, 180))
    for it in res["unidentified"]:
        x0, y0, x1, y1 = it["box"]
        d.rectangle([x0, y0, x1, y1], outline=(220, 60, 60), width=2)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()
    from ultralytics import YOLO
    m = YOLO(args.model)
    res = scan(Image.open(args.image).convert("RGB"), m, conf=args.conf)
    print(f"{res['detections']} detections, {res['identified']} identified "
          f"(YOLO {res['by_yolo']} / OCR {res['by_ocr']} / override {res['by_override']}), "
          f"{len(res['unidentified'])} unidentified · total {res['total']:,} RUB\n")
    print(f"{'KEEP (₽/slot desc)':36s} src  slots   ₽/slot      value")
    for it in res["items"][:25]:
        print(f"  {it['short'][:32]:32s} {it['source']:4s} {it['slots']:>3}  "
              f"{it['per_slot']:>9,}  {it['value']:>10,}")


if __name__ == "__main__":
    main()
