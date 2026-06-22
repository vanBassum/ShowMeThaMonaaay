"""
draw_boxes.py — Draw labeled boxes around the 3 main areas of the gear screenshot.

Reads an input image and writes a NEW file (the original is never modified) with
colored rectangles drawn around each of the three main UI panels.

Usage:
    python draw_boxes.py
    python draw_boxes.py --input "test screenshot 1.png" --output annotated.png

The box positions are defined as fractions of the image size, so they scale to
any resolution. Tweak REGIONS below if the layout differs.
"""

import argparse
from PIL import Image, ImageDraw, ImageFont

# Each region: (label, x0, y0, x1, y1, color) — coords are fractions (0..1) of width/height.
REGIONS = [
    ("Character Equipment", 0.010, 0.045, 0.300, 0.790, (255, 80, 80)),    # left panel
    ("Tactical Rig / Backpack", 0.305, 0.045, 0.630, 0.870, (80, 200, 80)), # middle panel
    ("Secondary Loadout", 0.635, 0.045, 0.962, 0.870, (80, 160, 255)),     # right panel
]


def load_font(size):
    """Try a few common fonts, fall back to PIL's default."""
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_boxes(input_path, output_path):
    img = Image.open(input_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    line_width = max(2, round(w / 400))
    font = load_font(max(14, round(w / 70)))

    for label, fx0, fy0, fx1, fy1, color in REGIONS:
        x0, y0, x1, y1 = fx0 * w, fy0 * h, fx1 * w, fy1 * h
        draw.rectangle([x0, y0, x1, y1], outline=color, width=line_width)

        # Label with a filled background for readability.
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = round(th * 0.3)
        ly = max(0, y0 - th - 2 * pad)
        draw.rectangle([x0, ly, x0 + tw + 2 * pad, ly + th + 2 * pad], fill=color)
        draw.text((x0 + pad, ly + pad), label, fill=(0, 0, 0), font=font)

    img.save(output_path)
    print(f"Saved annotated image to {output_path} ({w}x{h})")


def main():
    parser = argparse.ArgumentParser(description="Draw boxes around the 3 main screen areas.")
    parser.add_argument("--input", "-i", default="test screenshot 1.png", help="Input image path")
    parser.add_argument("--output", "-o", default="test screenshot 1 annotated.png", help="Output image path")
    args = parser.parse_args()
    draw_boxes(args.input, args.output)


if __name__ == "__main__":
    main()
