"""
mask_pipeline.py — Classical front-end that prepares a screenshot for the
detector by isolating item pixels. Three steps, each dumps a numbered PNG so we
can eyeball where it works and where it breaks:

  1_ocr_containers.png  OCR every line; flag the lines that name a CONTAINER
                        (STASH / POCKETS / BACKPACK / TACTICAL RIG / ...).
  2_subdivision.png     Carve the image into one region per container, anchored
                        on those labels (columns by x, stacked by y).
  3_bg_mask.png         Per container: flood-fill the uniform cell background
  3_masked.png          from the borders -> foreground = items. Mask + the
                        background-removed image (items on black) = detector input.

The masked image (3_masked.png) is the eventual input to the YOLO detector:
panels / UI chrome / world background are gone, so the detector only has to
separate adjacent items instead of also rejecting non-item regions.

Usage:
  python mask_pipeline.py
  python mask_pipeline.py -i "test screenshot 1.png" -o out --flood-thresh 22
"""
import argparse
import asyncio
import os
from collections import deque

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageOps


# ─────────────────────────────────────────────────────────────────────────────
# OCR (Windows OCR via winsdk) — full image, returns per-line boxes.
# ─────────────────────────────────────────────────────────────────────────────
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        _ENGINE = (OcrEngine.try_create_from_language(Language("en-US"))
                   or OcrEngine.try_create_from_user_profile_languages())
        if _ENGINE is None:
            raise RuntimeError("No Windows OCR language pack available")
    return _ENGINE


def _to_bitmap(pil):
    from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
    from winsdk.windows.storage.streams import DataWriter
    rgba = pil.convert("RGBA")
    w = DataWriter()
    w.write_bytes(rgba.tobytes())
    return SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.RGBA8, rgba.width, rgba.height)


async def _recognize(pil):
    return await _engine().recognize_async(_to_bitmap(pil))


def read_lines(img, scale=2, cutoff=1):
    """OCR a PIL RGB image. Returns [(text, x, y, w, h)] per line in ORIGINAL
    image coords. Upscales + autocontrasts (in-game text is small/low-contrast)."""
    proc = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=cutoff)
    proc = proc.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    res = asyncio.run(_recognize(proc.convert("RGBA")))
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


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — container labels (ported from the proven money2/349fcbe detectors).
# OCR every line, fuzzy-match its text against the known container header names.
# ─────────────────────────────────────────────────────────────────────────────
import difflib

NAMES = ["EARPIECE", "HEADWEAR", "FACE COVER", "ARMBAND", "BODY ARMOR", "EYEWEAR",
         "DOGTAG", "ON SLING", "ON BACK", "HOLSTER", "SHEATH", "TACTICAL RIG",
         "POCKETS", "BACKPACK", "SPECIAL SLOTS", "SECURED CONTAINER", "STASH",
         "SCABBARD", "POUCH"]


def match_name(text):
    u = text.upper().strip()
    if u in NAMES:
        return u
    m = difflib.get_close_matches(u, NAMES, n=1, cutoff=0.82)
    return m[0] if m else None


def quick_use_y(lines, default):
    """Y of the 'QUICK USE' bar label — used as the working bottom so the
    bottom quick-use slot strip (and HUD below it) is never masked."""
    for text, x, y, w, h in lines:
        u = text.upper().strip()
        if u == "QUICK USE" or difflib.get_close_matches(u, ["QUICK USE"], n=1, cutoff=0.8):
            return y
    return default


def find_containers(lines):
    """Return [(name, x, y, w, h)] for OCR lines that name a container."""
    out = []
    for text, x, y, w, h in lines:
        name = match_name(text)
        if name:
            out.append((name, x, y, w, h))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — subdivision (resolution-independent).
#
# No static sizes. Every container header gets a generous SEARCH region bounded
# by its neighbours, derived purely from relative geometry:
#   right  = nearest header to the right on the same row    (else panel edge)
#   bottom = nearest header below within this header's x-band(else panel bottom)
# Panels (the 3 columns) are found from the dark vertical gutters so a region
# never crosses between equipment / your-gear / loot panels.
# The real item box inside each region is recovered later by flood-fill (step 3),
# so the exact pixel size of a slot never needs to be known in advance.
#
# GRID containers are tall (their height depends on contents); SLOT containers
# hold one item. The only thing the type changes is the default x-band/extent
# used when a header has no neighbour to bound it.
# ─────────────────────────────────────────────────────────────────────────────
GRID_NAMES = {"TACTICAL RIG", "BACKPACK", "POCKETS", "SPECIAL SLOTS", "STASH",
              "LOOT", "SECURED CONTAINER"}


def panels(gray, headers):
    """Split the screen into vertical panels. The middle|right divider is a
    strong dark full-height gutter; the equipment|gear divider has no brightness
    signal, so derive it from where the grid containers start. Returns sorted
    [(x0, x1)] panel spans. All thresholds are relative to W."""
    W = gray.shape[1]
    band = gray[200:1000, :].astype(float).mean(0)
    strong = []
    for i in np.argsort(band):
        if band[i] > 12:
            break
        if all(abs(i - j) > 200 for j in strong):
            strong.append(int(i))
    right_div = min([g for g in strong if 0.5 * W < g < 0.78 * W], default=int(W * 0.64))
    grid_xs = [hx for (n, hx, hy, w, h) in headers
               if n in GRID_NAMES and hx < right_div]
    left_div = (min(grid_xs) - 35) if grid_xs else int(W * 0.33)
    bounds = sorted({0, left_div, right_div, W})
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _panel_of(x, pans):
    for x0, x1 in pans:
        if x0 <= x < x1:
            return (x0, x1)
    return (0, pans[-1][1])


def subdivide(headers, W, bottom, gray):
    """Generous, neighbour-bounded search region per header — no static sizes.
    `bottom` is the working bottom (the quick-use bar line). Each region fills
    down to the next label, or to `bottom` if nothing is below it.
    Returns ([{label, type, rect:(x0,y0,x1,y1)}], panels)."""
    pans = panels(gray, headers)
    # typical header line height drives all relative tolerances
    lh = int(np.median([h for (_, _, _, _, h) in headers])) if headers else 14
    row_tol = 3 * lh          # "same row" if header tops are within this
    xband = 4 * lh            # "below me" if header x is within this band
    margin = lh               # small gap kept between adjacent containers

    out = []
    for name, hx, hy, hw, hh in headers:
        px0, px1 = _panel_of(hx, pans)
        rights = [x2 for (n2, x2, y2, w2, h2) in headers
                  if hx + margin < x2 < px1 and abs(y2 - hy) < row_tol]
        belows = [y2 for (n2, x2, y2, w2, h2) in headers
                  if y2 > hy + 2 * lh and abs(x2 - hx) < xband]
        x0 = max(px0, hx - margin)
        x1 = (min(rights) - margin) if rights else px1 - margin // 2
        y0 = hy - margin // 2
        y1 = (min(belows) - margin) if belows else bottom - margin // 2
        kind = "GRID" if name in GRID_NAMES else "SLOT"
        out.append({"label": name, "type": kind, "rect": (x0, y0, x1, y1)})
    return out, pans


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — background removal: flood the uniform cell background from the region
# borders; everything it can't reach (items) is foreground.
# ─────────────────────────────────────────────────────────────────────────────
def flood_background(rgb, seeds, threshold, connectivity=4):
    arr = rgb.astype(np.int32)
    h, w, _ = arr.shape
    visited = np.zeros((h, w), dtype=bool)
    mask = np.zeros((h, w), dtype=bool)
    t2 = float(threshold) ** 2
    steps = ([(-1, 0), (1, 0), (0, -1), (0, 1)] if connectivity == 4 else
             [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)])
    q = deque()
    for sx, sy in seeds:
        sx = sx + w if sx < 0 else sx
        sy = sy + h if sy < 0 else sy
        if 0 <= sx < w and 0 <= sy < h and not visited[sy, sx]:
            visited[sy, sx] = mask[sy, sx] = True
            q.append((sx, sy))
    while q:
        cx, cy = q.popleft()
        cr, cg, cb = arr[cy, cx]
        for dx, dy in steps:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h or visited[ny, nx]:
                continue
            nr, ng, nb = arr[ny, nx]
            visited[ny, nx] = True
            if (nr - cr) ** 2 + (ng - cg) ** 2 + (nb - cb) ** 2 <= t2:
                mask[ny, nx] = True
                q.append((nx, ny))
    return mask


def region_foreground(crop, threshold):
    """Foreground (item) mask for a container crop: flood the background in from
    all four borders, invert, and clean up with a morphological close."""
    h, w, _ = crop.shape
    step = max(2, min(w, h) // 64)
    seeds = ([(x, 1) for x in range(0, w, step)] + [(x, h - 2) for x in range(0, w, step)]
             + [(1, y) for y in range(0, h, step)] + [(w - 2, y) for y in range(0, h, step)])
    bg = flood_background(crop, seeds, threshold, 4)
    fg = (~bg).astype(np.uint8) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    return fg


# ─────────────────────────────────────────────────────────────────────────────
def _font(size):
    for n in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def distinct_colors(n):
    """n visually distinct RGB colors, evenly spaced around the hue wheel."""
    import colorsys
    out = []
    for i in range(max(1, n)):
        h = (i * 0.618033988749895) % 1.0      # golden-ratio hue stepping
        r, g, b = colorsys.hsv_to_rgb(h, 0.65, 1.0)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="test screenshot 1.png")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("--flood-thresh", type=float, default=22.0,
                    help="Max local RGB step while flooding the cell background.")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    H, W, _ = rgb.shape
    font = _font(max(16, W // 90))

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # ---- OCR ----
    lines = read_lines(img)
    containers = find_containers(lines)
    print(f"OCR: {len(lines)} lines, {len(containers)} container labels")
    for lab, x, y, w, h in containers:
        print(f"  [{lab:16}] @ ({x},{y}) {w}x{h}")

    # ---- 1_ocr_containers.png ----
    s1 = img.copy()
    d1 = ImageDraw.Draw(s1)
    for text, x, y, w, h in lines:                      # all OCR (faint gray)
        d1.rectangle([x, y, x + w, y + h], outline=(110, 110, 110), width=1)
    for lab, x, y, w, h in containers:                  # containers (bold cyan)
        d1.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], outline=(0, 230, 255), width=3)
        d1.text((x, y - font.size - 2), lab, fill=(0, 230, 255), font=font)
    s1.save(os.path.join(args.outdir, "1_ocr_containers.png"))

    # ---- 2_subdivision.png ---- (each region its own color)
    qy = quick_use_y(lines, H)
    print(f"quick-use bar at y={qy} (working bottom)")
    regions, pans = subdivide(containers, W, qy, gray)
    colors = distinct_colors(len(regions))
    s2 = img.convert("RGBA")
    fill = Image.new("RGBA", s2.size, (0, 0, 0, 0))     # translucent fill layer
    df = ImageDraw.Draw(fill)
    for r, c in zip(regions, colors):
        x0, y0, x1, y1 = r["rect"]
        df.rectangle([x0, y0, x1, y1], fill=c + (70,))
    s2 = Image.alpha_composite(s2, fill).convert("RGB")
    d2 = ImageDraw.Draw(s2)
    for (px0, px1) in pans:                             # panel dividers (white)
        d2.line([px1 - 1, 0, px1 - 1, H], fill=(255, 255, 255), width=2)
    d2.line([0, qy, W, qy], fill=(255, 255, 255), width=2)  # quick-use cutoff
    for r, c in zip(regions, colors):
        x0, y0, x1, y1 = r["rect"]
        d2.rectangle([x0, y0, x1, y1], outline=c, width=3)
        d2.text((x0 + 4, y0 + 4), r["label"], fill=c, font=font)
    s2.save(os.path.join(args.outdir, "2_subdivision.png"))
    print(f"subdivision: {len(regions)} regions in {len(pans)} panels "
          f"(each region its own color; white = panel / quick-use dividers)")

    # ---- 3_bg_mask.png + 3_masked.png ----
    mask = np.zeros((H, W), dtype=np.uint8)
    for r in regions:
        x0, y0, x1, y1 = r["rect"]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        fg = region_foreground(rgb[y0:y1, x0:x1], args.flood_thresh)
        mask[y0:y1, x0:x1] = fg
    Image.fromarray(mask, "L").save(os.path.join(args.outdir, "3_bg_mask.png"))

    masked = rgb.copy()
    masked[mask == 0] = (255, 0, 255)                   # removed background -> bright pink
    Image.fromarray(masked).save(os.path.join(args.outdir, "3_masked.png"))

    print(f"foreground covers {100.0 * (mask > 0).mean():.1f}% of the image")
    print(f"wrote 1_ocr_containers.png, 2_subdivision.png, 3_bg_mask.png, "
          f"3_masked.png to {args.outdir}/")


if __name__ == "__main__":
    main()
