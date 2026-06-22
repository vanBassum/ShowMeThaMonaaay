"""
grid.py — Step 1 of the grid-based algorithm.

Takes the cropped screenshot and overlays a grid of fixed 32x32-pixel cells,
then writes the result. The original image is never modified.

Output:
  out/01_grid.png

Usage:
  python grid.py
  python grid.py -i "test screenshot cropped.png" --cell 32 -o out
"""
import argparse
import os

from PIL import Image, ImageDraw


def draw_grid(img, cell, color=(0, 255, 0), width=1):
    """Return a copy of img with grid lines every `cell` pixels."""
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    w, h = out.size
    for x in range(0, w + 1, cell):
        d.line([(x, 0), (x, h)], fill=color, width=width)
    for y in range(0, h + 1, cell):
        d.line([(0, y), (w, y)], fill=color, width=width)
    return out


def main():
    p = argparse.ArgumentParser(description="Overlay a 32x32 grid on the image.")
    p.add_argument("-i", "--input", default="test screenshot cropped.png")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--cell", type=int, default=32, help="Grid cell size in px.")
    p.add_argument("--color", default="0,255,0", help="Line color R,G,B.")
    p.add_argument("--width", type=int, default=1, help="Line width in px.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    w, h = img.size
    color = tuple(int(c) for c in args.color.split(","))

    out = draw_grid(img, args.cell, color, args.width)

    os.makedirs(args.outdir, exist_ok=True)
    path = os.path.join(args.outdir, "01_grid.png")
    out.save(path)

    cols = (w + args.cell - 1) // args.cell
    rows = (h + args.cell - 1) // args.cell
    print(f"{w}x{h} image -> {cols}x{rows} cells of {args.cell}px")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
