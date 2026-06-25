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
import os, sys, json, argparse
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for sibling imports
from ocr_identify import ocr_words, match_name  # noqa: E402

DEFAULT_MODEL = "shared/models/best.pt"   # barry v3 (active)

# Identity sources. YOLO's icon-id -> item comes from the NON-OCR link map (visual
# matcher + manual overrides); it's PREFERRED over OCR (more reliable in practice).
ITEMS_PATH = "data/items.json"
ICON_MAP_PATH = "data/icon_item_map.json"            # icon-id -> {item_id, score, margin}
OVERRIDES_PATH = "shared/links/icon_overrides.json"  # icon-id -> item_id (manual, wins)
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


def _link_map():
    """Resolved icon-id(str) -> {item_id, score, margin}; manual overrides win."""
    global _LINK
    if _LINK is None:
        auto = _jload(ICON_MAP_PATH, {})
        _LINK = {k: {"item_id": v.get("item_id"), "score": v.get("score"),
                     "margin": v.get("margin")}
                 for k, v in auto.items() if v.get("item_id")}
        for k, iid in _jload(OVERRIDES_PATH, {}).items():
            _LINK[k] = {"item_id": iid, "score": None, "margin": None, "override": True}
    return _LINK


def _catalog():
    global _CAT
    if _CAT is None:
        _CAT = {it["id"]: it for it in _jload(ITEMS_PATH, [])}
    return _CAT


def value_of(it):
    """Best realistic sell value (RUB): flea 24h avg, else best vendor, else base."""
    cands = [it.get("avg24hPrice") or 0, it.get("lastLowPrice") or 0]
    for s in it.get("sellFor", []) or []:
        cands.append(s.get("priceRUB") or 0)
    cands.append(it.get("basePrice") or 0)
    return max(cands)


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


def scan(pil, model, conf=0.25, imgsz=1536, ocr_scale=6, name_cutoff=0.6):
    """Run the full pipeline on a PIL image. Returns a result dict.

    Identity: YOLO icon-id -> item (non-OCR link map) is PREFERRED; OCR is the
    fallback + an independent cross-check. Both POVs are recorded per detection."""
    link, cat = _link_map(), _catalog()
    r = model.predict(pil, imgsz=imgsz, conf=conf, max_det=400, verbose=False)[0]
    items, unidentified = [], []
    for b in r.boxes:
        x0, y0, x1, y1 = (round(v) for v in b.xyxy[0].tolist())
        icon_id = str(r.names[int(b.cls)])
        det_conf = round(float(b.conf), 3)

        # 1) YOLO identity via the non-OCR icon-id -> item map, with a certainty
        meta = link.get(icon_id)
        yitem = cat.get(meta["item_id"]) if meta else None
        yc = yolo_certainty(meta) if yitem else 0.0
        yolo = None
        if yitem:
            yolo = {**_entry(yitem), "score": meta.get("score"), "margin": meta.get("margin"),
                    "override": meta.get("override", False), "certainty": yc}

        # 2) OCR identity (independent cross-check); its fuzzy score is its certainty
        oit, osc, raw = _name_in_box(pil.crop((x0, y0, x1, y1)), ocr_scale, name_cutoff)
        oc = round(osc, 2) if oit else 0.0
        ocr = {**_entry(oit), "score": oc, "raw": raw} if oit else \
              {"id": "", "name": "", "short": "", "score": oc, "raw": raw}

        # choose the MORE CERTAIN source (confident icon-match -> YOLO; ambiguous -> OCR)
        if yitem and (not oit or yc >= oc):
            chosen, source, cert = yitem, "yolo", yc
        elif oit:
            chosen, source, cert = oit, "ocr", oc
        else:
            chosen, source, cert = None, None, 0.0
        rec = {"box": [x0, y0, x1, y1], "icon_id": icon_id, "det_conf": det_conf,
               "source": source, "certainty": cert, "yolo": yolo, "ocr": ocr,
               "agree": bool(yitem and oit and yitem["id"] == oit["id"])}
        if chosen:
            e = _entry(chosen)
            val = value_of(chosen)
            rec.update(e, value=val, slots=e["width"] * e["height"],
                       per_slot=round(val / (e["width"] * e["height"])))
            items.append(rec)
        else:
            unidentified.append(rec)
    items.sort(key=lambda r: r["per_slot"], reverse=True)
    return {"items": items, "unidentified": unidentified,
            "detections": len(r.boxes), "identified": len(items),
            "by_yolo": sum(1 for it in items if it["source"] == "yolo"),
            "by_ocr": sum(1 for it in items if it["source"] == "ocr")}


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
          f"(YOLO {res['by_yolo']} / OCR {res['by_ocr']}), "
          f"{len(res['unidentified'])} unidentified\n")
    print(f"{'KEEP (₽/slot desc)':36s} src  slots   ₽/slot      value")
    for it in res["items"][:25]:
        print(f"  {it['short'][:32]:32s} {it['source']:4s} {it['slots']:>3}  "
              f"{it['per_slot']:>9,}  {it['value']:>10,}")


if __name__ == "__main__":
    main()
