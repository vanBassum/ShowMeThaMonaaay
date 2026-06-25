"""
ocr_identify.py — IDENTIFICATION half of the pipeline.

YOLO gives box + icon-id (what icon, where). This reads the item NAME the game
prints on each item and resolves it to a tarkov.dev item (name + price). OCR is
game->game so it sidesteps the icon->web visual gap; the printed short-name is
matched to the catalog. Windows built-in OCR (winsdk), CPU-only — safe to run
alongside GPU training.

Use:
  words = ocr_words(pil)                 # [(text, x, y, w, h)] in image px
  item, score = match_name("TP-200")     # -> catalog item dict, 0..1
  # then assign each word to the YOLO box whose top edge it sits on, and
  # majority-vote name per icon-id across many detections.
"""
import json, difflib, asyncio
from PIL import ImageOps

ITEMS = "data/items.json"
_IDX = None


def _index():
    global _IDX
    if _IDX is None:
        items = json.load(open(ITEMS, encoding="utf-8"))
        short, full = {}, {}
        for it in items:
            if it.get("shortName"):
                short.setdefault(it["shortName"].lower(), it)
            if it.get("name"):
                full.setdefault(it["name"].lower(), it)
        _IDX = (short, full, list(short), list(full))
    return _IDX


def price(it):
    return it.get("avg24hPrice") or it.get("lastLowPrice") or it.get("basePrice") or 0


def match_name(text, cutoff=0.6):
    """Fuzzy-match OCR text to a catalog item. Returns (item|None, score 0..1)."""
    short, full, sk, fk = _index()
    n = " ".join(text.lower().split())
    if not n:
        return None, 0.0
    if n in short:
        return short[n], 1.0
    if n in full:
        return full[n], 1.0
    for keys, idx in ((sk, short), (fk, full)):
        c = difflib.get_close_matches(n, keys, n=1, cutoff=cutoff)
        if c:
            return idx[c[0]], difflib.SequenceMatcher(None, n, c[0]).ratio()
    return None, 0.0


async def _recognize(rgba):
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
    from winsdk.windows.storage.streams import DataWriter
    eng = (OcrEngine.try_create_from_language(Language("en-US"))
           or OcrEngine.try_create_from_user_profile_languages())
    w = DataWriter()
    w.write_bytes(rgba.tobytes())
    sb = SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.RGBA8, rgba.width, rgba.height)
    return await eng.recognize_async(sb)


def ocr_words(pil, scale=4):
    """OCR `pil` (upscaled x`scale` for small game text); return word boxes
    [(text, x, y, w, h)] mapped back to ORIGINAL pixel coords."""
    big = pil.resize((pil.width * scale, pil.height * scale))
    big = ImageOps.autocontrast(ImageOps.grayscale(big), cutoff=1).convert("RGBA")
    try:
        res = asyncio.run(_recognize(big))
    except Exception:
        return []
    out = []
    for line in res.lines:
        for word in line.words:
            r = word.bounding_rect
            out.append((word.text, r.x / scale, r.y / scale,
                        r.width / scale, r.height / scale))
    return out


if __name__ == "__main__":
    import sys
    from PIL import Image
    img = sys.argv[1] if len(sys.argv) > 1 else "sessions/20260623-182907/raw.png"
    box = (1687, 540, 2400, 920)  # demo: a region known to have named items
    words = ocr_words(Image.open(img).convert("RGB").crop(box))
    print(f"{len(words)} words")
    for t, x, y, w, h in words:
        it, sc = match_name(t)
        tag = f"-> {it['name']} ({price(it):,} RUB)" if it and sc > 0.7 else ""
        print(f"  ({x:4.0f},{y:4.0f}) {t!r:16s} {tag}")
