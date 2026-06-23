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
# Step 1 — container labels.
# ─────────────────────────────────────────────────────────────────────────────
# Header text the game prints above inventory containers. Matched loosely
# (uppercased, substring) so partial OCR ("TACTICAL" / "RIG") still anchors.
CONTAINER_LABELS = [
    "STASH", "POCKETS", "TACTICAL RIG", "RIG", "BACKPACK", "SECURE CONTAINER",
    "POUCH", "ARMOR VEST", "BODY ARMOR", "SCABBARD", "ON SLING", "ON BACK",
    "HOLSTER", "EQUIPMENT", "SPECIAL SLOTS", "POCKET",
]


def is_container_label(text):
    up = "".join(c for c in text.upper() if c.isalpha() or c.isspace()).strip()
    if not up:
        return None
    for lab in CONTAINER_LABELS:
        if lab == up or up.startswith(lab) or lab.startswith(up) and len(up) >= 4:
            return lab
    return None


def find_containers(lines):
    """Return [(label, x, y, w, h)] for OCR lines that name a container."""
    hits = []
    for text, x, y, w, h in lines:
        lab = is_container_label(text)
        if lab:
            hits.append((lab, x, y, w, h))
    return hits


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — subdivision: one region per container, anchored on its label.
# Columns are clustered by label x; within a column, each container spans from
# its label down to the next label (or image bottom).
# ─────────────────────────────────────────────────────────────────────────────
def subdivide(containers, W, H, col_tol=None):
    if not containers:
        return []
    col_tol = col_tol or W // 8
    # cluster labels into columns by x
    cs = sorted(containers, key=lambda c: c[1])
    cols = []  # list of [members]
    for c in cs:
        placed = False
        for col in cols:
            if abs(col[0][1] - c[1]) <= col_tol:
                col.append(c); placed = True; break
        if not placed:
            cols.append([c])
    cols.sort(key=lambda col: min(m[1] for m in col))
    col_x = [min(m[1] for m in col) for col in cols]
    col_right = [col_x[i + 1] for i in range(len(cols) - 1)] + [W]

    regions = []
    for ci, col in enumerate(cols):
        col.sort(key=lambda m: m[2])  # by y
        x0 = col_x[ci]
        x1 = col_right[ci]
        for mi, (lab, lx, ly, lw, lh) in enumerate(col):
            top = ly + lh  # region body starts just below the label
            bottom = col[mi + 1][2] if mi + 1 < len(col) else H
            regions.append({"label": lab, "rect": (x0, top, x1, bottom),
                            "label_box": (lx, ly, lw, lh)})
    return regions


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

    # ---- 2_subdivision.png ----
    regions = subdivide(containers, W, H)
    s2 = img.copy()
    d2 = ImageDraw.Draw(s2)
    for r in regions:
        x0, y0, x1, y1 = r["rect"]
        d2.rectangle([x0, y0, x1, y1], outline=(255, 180, 0), width=3)
        d2.text((x0 + 4, y0 + 4), r["label"], fill=(255, 180, 0), font=font)
    s2.save(os.path.join(args.outdir, "2_subdivision.png"))
    print(f"subdivision: {len(regions)} container regions")

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
    masked[mask == 0] = 0                               # background -> black
    Image.fromarray(masked).save(os.path.join(args.outdir, "3_masked.png"))

    print(f"foreground covers {100.0 * (mask > 0).mean():.1f}% of the image")
    print(f"wrote 1_ocr_containers.png, 2_subdivision.png, 3_bg_mask.png, "
          f"3_masked.png to {args.outdir}/")


if __name__ == "__main__":
    main()
