"""
scan.py — Read an EFT gear screenshot and value its contents.

Approach (deliberately NOT grid reconstruction): the strongest signal in the
image is the item text the game prints on every item. We OCR all text, drop UI
chrome (tab/slot labels, durability/weight numbers), match what's left against
the tarkov.dev item database, and report identified items + their value.

  screenshot -> OCR lines -> drop UI text -> match to item DB -> value + annotate

Outputs:
  out/scan.png   screenshot with identified items boxed + named + priced
  stdout         item list sorted by value, and a total

Usage:
  python scan.py
  python scan.py -i "test screenshot 1.png" --min-score 0.82
"""
import argparse
import os
import re

from PIL import Image, ImageDraw, ImageFont

import tarkov
from ocr import read_lines

# UI text that is not an item — skip before matching.
UI_WORDS = {
    "OVERALL", "GEAR", "HEALTH", "SKILLS", "MAP", "TASKS", "ACHIEVEMENTS",
    "BACK", "BODY", "QUICK USE", "LOOT",
    "EARPIECE", "HEADWEAR", "FACE COVER", "ARMBAND", "BODY ARMOR", "EYEWEAR",
    "DOGTAG", "ON SLING", "ON BACK", "HOLSTER", "SHEATH", "TACTICAL RIG",
    "POCKETS", "BACKPACK", "SPECIAL SLOTS",
}


def is_noise(text):
    """True for UI chrome: known labels, or mostly digits/slashes (durability,
    weight, ammo counts like '20/20', '205/212', '42.1')."""
    t = text.strip()
    if t.upper() in UI_WORDS:
        return True
    alnum = re.sub(r"[^a-z0-9]", "", t.lower())
    if not alnum:
        return True
    digits = sum(c.isdigit() for c in alnum)
    return digits / len(alnum) > 0.5


def load_font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--output", default="out/scan.png")
    p.add_argument("--min-score", type=float, default=0.82,
                   help="Minimum fuzzy match confidence to accept an item.")
    p.add_argument("--refresh", action="store_true", help="Re-fetch item DB.")
    args = p.parse_args()

    matcher = tarkov.Matcher(tarkov.load(refresh=args.refresh))

    img = Image.open(args.input).convert("RGB")
    lines = read_lines(img)

    found = []
    for text, x, y, w, h in lines:
        if is_noise(text):
            continue
        item, score = matcher.match(text, threshold=args.min_score)
        if item:
            found.append({"text": text, "item": item, "score": score,
                          "price": tarkov.best_price(item), "box": (x, y, w, h)})

    # annotate
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    draw = ImageDraw.Draw(img)
    font = load_font(max(13, img.width // 110))
    for f in found:
        x, y, w, h = f["box"]
        draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2],
                       outline=(0, 255, 0), width=2)
        tag = f"{f['item']['shortName']} {f['price']:,}"
        draw.text((x, y + h + 2), tag, fill=(0, 255, 0), font=font)
    img.save(args.output)

    found.sort(key=lambda f: -f["price"])
    total = sum(f["price"] for f in found)
    print(f"{'OCR':16} {'ITEM':40} {'SCORE':>5} {'PRICE':>12}")
    print("-" * 78)
    for f in found:
        print(f"{f['text'][:16]:16} {f['item']['name'][:40]:40} "
              f"{f['score']:5.2f} {f['price']:>12,}")
    print("-" * 78)
    print(f"{len(found)} items identified | total {total:,} RUB")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
