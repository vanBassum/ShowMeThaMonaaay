"""
find_items.py — OCR the gear screen and box the main item-slot labels
(EARPIECE, ON SLING, TACTICAL RIG, ...). Uses the built-in Windows OCR engine
via ocr.py (same engine as the ShowMeThaMonaaay project).

Original image is never modified; an annotated copy is written.

Usage:
    python find_items.py
    python find_items.py -i "test screenshot 1.png" -o annotated.png --scale 2
"""
import argparse

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ocr import ocr_lines

# The slot labels we treat as "main items". Matching is case/space-insensitive
# and substring-based so minor OCR noise still hits.
SLOT_LABELS = [
    "EARPIECE", "HEADWEAR", "FACE COVER", "ARMBAND", "BODY ARMOR",
    "EYEWEAR", "DOGTAG", "ON SLING", "HOLSTER", "ON BACK", "SHEATH",
    "TACTICAL RIG", "POCKETS", "SPECIAL SLOTS", "BACKPACK",
]


def norm(s):
    return "".join(c for c in s.upper() if c.isalnum())


def load_font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def find_labels(img, scale=2, keep_all=False):
    """OCR `img` (a PIL RGB image) and return [(text, x, y, w, h)] for each slot
    label, in original-image coordinates. keep_all=True returns every OCR line.
    """
    w, h = img.size
    # Upscale + contrast-boost a grayscale copy purely to feed the OCR engine.
    proc = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    proc = proc.resize((w * scale, h * scale), Image.LANCZOS).convert("RGBA")

    lines = ocr_lines(proc)
    wanted = {norm(l) for l in SLOT_LABELS}
    matches = []
    for text, x, y, bw, bh in lines:
        ox, oy, obw, obh = x / scale, y / scale, bw / scale, bh / scale
        n = norm(text)
        # A real match means the full slot label is present in the detected text
        # (handles trailing OCR noise). Detected fragments that are merely a
        # substring of a label (BACK⊂ONBACK, BODY⊂BODYARMOR) are rejected.
        hit = keep_all or any(lbl in n for lbl in wanted if lbl)
        if hit and n:
            matches.append((text, ox, oy, obw, obh))
    return matches


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--output", default="test screenshot 1 items.png")
    p.add_argument("--scale", type=int, default=2,
                   help="Upscale factor before OCR (small text reads better).")
    p.add_argument("--all", action="store_true",
                   help="Box every OCR line, not just known slot labels.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    w, h = img.size
    matches = find_labels(img, scale=args.scale, keep_all=args.all)

    draw = ImageDraw.Draw(img)
    font = load_font(max(12, w // 90))
    pad_grow = 4  # enlarge box a touch so text isn't clipped
    for text, x, y, bw, bh in matches:
        x0, y0 = x - pad_grow, y - pad_grow
        x1, y1 = x + bw + pad_grow, y + bh + pad_grow
        draw.rectangle([x0, y0, x1, y1], outline=(0, 255, 0), width=2)
        # label above the box
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        ly = max(0, y0 - th - 4)
        draw.rectangle([x0, ly, x0 + tw + 4, ly + th + 4], fill=(0, 255, 0))
        draw.text((x0 + 2, ly + 2), text, fill=(0, 0, 0), font=font)

    img.save(args.output)
    print(f"Detected {len(matches)} label(s):")
    for text, x, y, bw, bh in matches:
        print(f"  {text!r:24} @ ({x:.0f},{y:.0f}) {bw:.0f}x{bh:.0f}")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
