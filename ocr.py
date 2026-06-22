"""
OCR the item-name text the game prints on each inventory cell, using the
built-in Windows OCR engine (Windows.Media.Ocr via winsdk) -- no external
binary. Used to disambiguate items that share an icon (keys, ammo, etc.).

The in-game text is small/low-contrast, so we upscale + boost contrast first.
"""
import asyncio
from PIL import Image, ImageOps

from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
from winsdk.windows.security.cryptography import CryptographicBuffer

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = (OcrEngine.try_create_from_language(Language("en-US"))
                   or OcrEngine.try_create_from_user_profile_languages())
        if _ENGINE is None:
            raise RuntimeError("No Windows OCR language pack available")
    return _ENGINE


def _to_softwarebitmap(img):
    img = img.convert("RGBA")
    b, g, r, a = img.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()  # BGRA byte order
    buf = CryptographicBuffer.create_from_byte_array(bgra)
    return SoftwareBitmap.create_copy_from_buffer(
        buf, BitmapPixelFormat.BGRA8, img.width, img.height)


async def _recognize(sb):
    return await engine().recognize_async(sb)


def ocr(img):
    """Return recognized text (single string) from a PIL image region."""
    sb = _to_softwarebitmap(img)
    res = asyncio.run(_recognize(sb))
    return res.text.strip()


def ocr_words(img):
    """Return [(text, x, y, w, h)] for every recognized word with its box."""
    sb = _to_softwarebitmap(img)
    res = asyncio.run(_recognize(sb))
    out = []
    for line in res.lines:
        for w in line.words:
            br = w.bounding_rect
            out.append((w.text, int(br.x), int(br.y), int(br.width), int(br.height)))
    return out


def ocr_lines(img):
    """Return [(text, x, y, w, h)] per recognized line (multi-word phrases joined),
    with the line's bounding box (union of its word boxes)."""
    sb = _to_softwarebitmap(img)
    res = asyncio.run(_recognize(sb))
    out = []
    for line in res.lines:
        text = line.text
        boxes = []
        for w in line.words:
            br = w.bounding_rect
            boxes.append((float(br.x), float(br.y), float(br.width), float(br.height)))
        if not boxes:
            continue
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[0] + b[2] for b in boxes)
        y1 = max(b[1] + b[3] for b in boxes)
        out.append((text, int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
    return out


def prep_name(crop, scale=4):
    """Enhance a cell's name region for OCR: grayscale, autocontrast, upscale."""
    g = ImageOps.grayscale(crop)
    g = ImageOps.autocontrast(g, cutoff=2)
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    return g.convert("RGBA")


if __name__ == "__main__":
    import sys
    print(repr(ocr(prep_name(Image.open(sys.argv[1]).convert("RGB")))))
