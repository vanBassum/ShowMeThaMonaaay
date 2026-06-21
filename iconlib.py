"""
Shared icon normalization + hashing so build_hashes.py and identify.py stay
identical. The game overlays a name (top) and a count/durability readout
(bottom-right) on each inventory cell; the DB grid-icons have neither. We mask
those regions on BOTH sides before hashing so the hashes compare like-for-like.
"""
import imagehash
from PIL import Image

HASH_SIZE = 16
NORM = 64  # normalize every icon-cell to 64x64 before masking/hashing

# mask rectangles in NORM(=64) space, applied per CELL (tiled for multi-cell)
NAME_H = 15          # top strip: item name text
COUNT_W, COUNT_H = 28, 20   # bottom-right: stack count / durability number
MASK_RGB = (25, 25, 25)


def load_icon(path):
    """Load an icon, flattening alpha onto a dark stash-like background."""
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (25, 25, 25, 255))
    return Image.alpha_composite(bg, img).convert("RGB")


def _mask_cell(img):
    """Mask name+count regions on a single normalized 64x64 cell (in place)."""
    px = img.load()
    for y in range(NAME_H):
        for x in range(NORM):
            px[x, y] = MASK_RGB
    for y in range(NORM - COUNT_H, NORM):
        for x in range(NORM - COUNT_W, NORM):
            px[x, y] = MASK_RGB
    return img


def prep(img, w_cells=1, h_cells=1):
    """Normalize an icon (whole item) to a (w*64 x h*64) canvas and mask the
    name/count overlay in each cell. Returns an RGB image ready to hash."""
    w_cells = max(1, w_cells)
    h_cells = max(1, h_cells)
    canvas = img.convert("RGB").resize((NORM * w_cells, NORM * h_cells))
    # mask per-cell: name appears once (top-left cell), count once
    # (bottom-right cell); mask all cells' name/count zones to stay symmetric.
    px = canvas.load()
    W, H = canvas.size
    # top name strip spans the whole top row of cells
    for y in range(NAME_H):
        for x in range(W):
            px[x, y] = MASK_RGB
    # count zone is in the overall bottom-right corner
    for y in range(H - COUNT_H, H):
        for x in range(W - COUNT_W, W):
            px[x, y] = MASK_RGB
    return canvas


COLOR_GRID = 8  # 8x8 RGB color signature -> color is highly discriminating for EFT icons


def color_sig(img):
    """Flat list of 8x8x3 ints: a coarse color fingerprint of the (masked) icon."""
    small = img.convert("RGB").resize((COLOR_GRID, COLOR_GRID))
    return list(small.tobytes())


def hashes(img):
    return {
        "p": str(imagehash.phash(img, hash_size=HASH_SIZE)),
        "d": str(imagehash.dhash(img, hash_size=HASH_SIZE)),
        "a": str(imagehash.average_hash(img, hash_size=HASH_SIZE)),
        "c": color_sig(img),
    }
