"""
Minimal Windows OCR (winsdk) for reading the item name the game prints on a
crop. Used to AUTO-LABEL real crops for classifier fine-tuning -- not for
detection (that's grid-free YOLO).

  ocr(pil) -> recognized text (lowercased words joined)
"""
import asyncio
from PIL import Image, ImageOps

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        _ENGINE = OcrEngine.try_create_from_language(Language("en-US")) \
            or OcrEngine.try_create_from_user_profile_languages()
    return _ENGINE


def _to_softwarebitmap(pil):
    from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
    from winsdk.windows.storage.streams import DataWriter
    rgba = pil.convert("RGBA")
    w = DataWriter()
    w.write_bytes(rgba.tobytes())
    return SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.RGBA8, rgba.width, rgba.height)


async def _run(pil):
    sb = _to_softwarebitmap(pil)
    res = await _engine().recognize_async(sb)
    return res.text


def ocr(pil):
    """OCR a (small) PIL image; returns recognized text or ''."""
    try:
        return asyncio.run(_run(pil)) or ""
    except Exception:
        return ""


async def _run_words(pil):
    sb = _to_softwarebitmap(pil)
    res = await _engine().recognize_async(sb)
    out = []
    for line in res.lines:
        for w in line.words:
            r = w.bounding_rect
            out.append((w.text, float(r.x), float(r.y), float(r.width), float(r.height)))
    return out


def ocr_words(pil):
    """OCR a PIL image; return [(text, x, y, w, h)] word boxes in pil pixels."""
    try:
        return asyncio.run(_run_words(pil))
    except Exception:
        return []


def prep(crop, scale=6):
    """Upscale + autocontrast (grayscale) so OCR reads small in-game text.
    Binarizing hurt (e.g. 'BCP FMJ' -> 'BCP#MA'); plain grayscale reads best."""
    big = crop.resize((crop.width * scale, crop.height * scale))
    return ImageOps.autocontrast(ImageOps.grayscale(big), cutoff=1).convert("RGB")


def prep_text(crop, scale=4, lum=150, sat=70):
    """Isolate the white name text (the game prints names in white with a dark
    outline) and drop the busy item icon behind it: near-white, low-saturation
    pixels become black strokes on a white page -> clean high-contrast OCR."""
    import numpy as np
    big = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    a = np.asarray(big.convert("RGB")).astype(np.int16)
    luma = a.mean(2)
    satur = a.max(2) - a.min(2)
    white = (luma > lum) & (satur < sat)
    out = np.where(white, 0, 255).astype("uint8")              # black text / white page
    return Image.fromarray(out, "L").convert("RGB")
