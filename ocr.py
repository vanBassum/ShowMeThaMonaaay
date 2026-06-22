"""
OCR via the built-in Windows OCR engine (Windows.Media.Ocr through winsdk).
No external binary. In-game text is small/low-contrast, so callers should
upscale + boost contrast (see read_lines).
"""
import asyncio

from PIL import Image, ImageOps
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
from winsdk.windows.security.cryptography import CryptographicBuffer

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = (OcrEngine.try_create_from_language(Language("en-US"))
                   or OcrEngine.try_create_from_user_profile_languages())
        if _ENGINE is None:
            raise RuntimeError("No Windows OCR language pack available")
    return _ENGINE


def _to_bitmap(img):
    img = img.convert("RGBA")
    b, g, r, a = img.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    buf = CryptographicBuffer.create_from_byte_array(bgra)
    return SoftwareBitmap.create_copy_from_buffer(
        buf, BitmapPixelFormat.BGRA8, img.width, img.height)


async def _recognize_async(img):
    return await _engine().recognize_async(_to_bitmap(img))


def _recognize(img):
    return asyncio.run(_recognize_async(img))


def read_lines(img, scale=2, cutoff=1):
    """OCR a PIL RGB image. Returns [(text, x, y, w, h)] per line, with boxes
    mapped back to the ORIGINAL image coordinates. Upscales + autocontrasts
    first because the in-game text is small and low-contrast."""
    proc = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=cutoff)
    proc = proc.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    res = _recognize(proc.convert("RGBA"))

    out = []
    for line in res.lines:
        boxes = [(w.bounding_rect.x, w.bounding_rect.y,
                  w.bounding_rect.width, w.bounding_rect.height)
                 for w in line.words]
        if not boxes:
            continue
        x0 = min(b[0] for b in boxes) / scale
        y0 = min(b[1] for b in boxes) / scale
        x1 = max(b[0] + b[2] for b in boxes) / scale
        y1 = max(b[1] + b[3] for b in boxes) / scale
        out.append((line.text, int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
    return out


if __name__ == "__main__":
    import sys
    for t, x, y, w, h in read_lines(Image.open(sys.argv[1]).convert("RGB")):
        print(f"({x:4d},{y:4d}) {w:3d}x{h:2d}  {t!r}")
