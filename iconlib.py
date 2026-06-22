"""
Icon normalization + hashing, shared by build_hashes.py and identify.py so both
sides process icons identically.

The game overlays an item-name strip (top) and a stack-count / durability
readout (bottom-right) on each inventory cell; the tarkov.dev DB grid-icons have
neither. We mask those zones on BOTH sides before hashing so the perceptual
hashes compare like-for-like.
"""
import imagehash
from PIL import Image

HASH_SIZE = 16
NORM = 64                  # normalize each cell to NORM x NORM before hashing
NAME_H = 15                # top strip: item-name text (in NORM space)
COUNT_W, COUNT_H = 28, 20  # bottom-right: stack count / durability
MASK_RGB = (25, 25, 25)
COLOR_GRID = 8             # 8x8 RGB colour signature (colour discriminates well)


def load_icon(path):
    """Load a DB icon, flattening alpha onto a dark stash-like background."""
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (25, 25, 25, 255))
    return Image.alpha_composite(bg, img).convert("RGB")


def prep(img, w_cells=1, h_cells=1):
    """Normalize a whole item icon to (w*64 x h*64) and mask the name strip and
    count zone. Returns an RGB image ready to hash."""
    w_cells, h_cells = max(1, w_cells), max(1, h_cells)
    canvas = img.convert("RGB").resize((NORM * w_cells, NORM * h_cells))
    px = canvas.load()
    W, H = canvas.size
    for y in range(min(NAME_H, H)):          # name strip across the top row
        for x in range(W):
            px[x, y] = MASK_RGB
    for y in range(max(0, H - COUNT_H), H):  # count zone bottom-right
        for x in range(max(0, W - COUNT_W), W):
            px[x, y] = MASK_RGB
    return canvas


def color_sig(img):
    """Coarse 8x8x3 colour fingerprint as a flat list of ints."""
    return list(img.convert("RGB").resize((COLOR_GRID, COLOR_GRID)).tobytes())


def hashes(img):
    return {
        "p": str(imagehash.phash(img, hash_size=HASH_SIZE)),
        "d": str(imagehash.dhash(img, hash_size=HASH_SIZE)),
        "a": str(imagehash.average_hash(img, hash_size=HASH_SIZE)),
        "c": color_sig(img),
    }
