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
import os, sys, argparse
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for sibling imports
from ocr_identify import ocr_words, match_name  # noqa: E402

DEFAULT_MODEL = "shared/models/best.pt"   # barry v3 (active)


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


def scan(pil, model, conf=0.25, imgsz=1536, ocr_scale=6, name_cutoff=0.6):
    """Run the full pipeline on a PIL image. Returns a result dict."""
    r = model.predict(pil, imgsz=imgsz, conf=conf, max_det=400, verbose=False)[0]
    items, unidentified = [], []
    for b in r.boxes:
        x0, y0, x1, y1 = (round(v) for v in b.xyxy[0].tolist())
        icon_id = r.names[int(b.cls)]
        det_conf = float(b.conf)
        crop = pil.crop((x0, y0, x1, y1))
        it, sc, raw = _name_in_box(crop, ocr_scale, name_cutoff)
        rec = {"box": [x0, y0, x1, y1], "icon_id": str(icon_id),
               "det_conf": round(det_conf, 3), "ocr": raw}
        if it:
            w, h = it.get("width", 1) or 1, it.get("height", 1) or 1
            val = value_of(it)
            rec.update({"id": it.get("id", ""), "name": it["name"], "short": it.get("shortName", ""),
                        "value": val, "width": w, "height": h, "slots": w * h,
                        "per_slot": round(val / (w * h)), "ocr_score": round(sc, 2)})
            items.append(rec)
        else:
            unidentified.append(rec)
    items.sort(key=lambda r: r["per_slot"], reverse=True)
    return {"items": items, "unidentified": unidentified,
            "detections": len(r.boxes), "identified": len(items)}


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
    print(f"{res['detections']} detections, {res['identified']} identified, "
          f"{len(res['unidentified'])} unidentified\n")
    print(f"{'KEEP (₽/slot desc)':38s}  slots   ₽/slot      value")
    for it in res["items"][:25]:
        print(f"  {it['short'][:34]:34s}  {it['slots']:>3}  {it['per_slot']:>9,}  {it['value']:>10,}")


if __name__ == "__main__":
    main()
