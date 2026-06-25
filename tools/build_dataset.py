"""
build_dataset.py — synthetic YOLO dataset for single-pass item detection.

Pastes real game-rendered icons (from the EFT icon cache in AppData) onto the
stash background at valid grid positions, and emits YOLO detection labels where
each box's CLASS is the icon itself. One network -> box + item identity.

Icon cache:  %LOCALAPPDATA%\\Temp\\Battlestate Games\\EscapeFromTarkov\\Icon Cache\\live
Background + grid layout: templates/screen1/{background.png,grids.json}

Output (ultralytics layout):
    data/yolo/
        images/{train,val}/*.png
        labels/{train,val}/*.txt
        data.yaml
        classes.json   # class_idx -> icon number (filename stem)
"""
import os, json, glob, random, argparse, shutil
from PIL import Image, ImageDraw, ImageFont

OVERLAYS = "shared/assets/overlays"
FONT_CANDIDATES = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"]
# overlay probabilities (real items almost always show a name; rest are common)
P_NAME, P_COUNT, P_FIR, P_MARKED = 0.95, 0.35, 0.30, 0.10
# In-stash items are frequently rotated 90 deg to pack the grid. The cache stores
# ONE orientation, so without this the model never sees rotated items and misses
# them entirely. Rotate 90 deg with this prob (same class, footprint swapped cw<->ch).
P_ROT90 = 0.5
# Items can have a colored cell background (assignable bg colors + ammo tints). The
# cache icon is transparent on a plain cell, so without this the model never sees a
# tinted cell behind/through an item. Real muted EFT tints sampled from screenshots.
P_BGCOLOR = 0.30
BG_COLORS = [(72, 64, 45), (86, 49, 37), (59, 66, 35), (36, 47, 61),
             (39, 29, 42), (90, 30, 35), (34, 55, 49)]

# Local default = the live EFT icon cache in AppData. Override with EFT_ICON_CACHE
# (e.g. on Kaggle, point it at the uploaded cache dir). .get avoids KeyError off-Windows.
CACHE = os.environ.get("EFT_ICON_CACHE") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "Battlestate Games",
    "EscapeFromTarkov", "Icon Cache", "live",
)
TEMPLATE_DIR = "shared/templates/screen1"
OUT = "training/dataset"


def icon_cells(px):
    """Cache icons render at ~63px/cell. Map a pixel dimension to cell count."""
    return max(1, round((px - 1) / 63))


def load_icons(max_classes=None, seed=0):
    """Return list of (icon_number:int, path, cells_w, cells_h)."""
    paths = glob.glob(os.path.join(CACHE, "*.png"))
    icons = []
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        if not stem.isdigit():
            continue
        with Image.open(p) as im:
            w, h = im.size
        cw, ch = icon_cells(w), icon_cells(h)
        if not (1 <= cw <= 10 and 1 <= ch <= 16):
            continue
        icons.append((int(stem), p, cw, ch))
    icons.sort(key=lambda x: x[0])
    if max_classes:
        random.Random(seed).shuffle(icons)
        icons = sorted(icons[:max_classes], key=lambda x: x[0])
    return icons


def load_grids():
    """Return list of containers as dicts with pixel cell geometry."""
    grids = json.load(open(os.path.join(TEMPLATE_DIR, "grids.json")))
    out = []
    for g in grids:
        cols, rows = g.get("cols", 1), g.get("rows", 1)
        out.append({
            "x": g["x"], "y": g["y"],
            "cols": cols, "rows": rows,
            "cw": g["w"] / cols, "ch": g["h"] / rows,
        })
    return out


def place_into(containers, cw, ch, occ):
    """Find a free top-left cell for a cw x ch icon. Returns (ci, col, row) or None."""
    order = list(range(len(containers)))
    random.shuffle(order)
    for ci in order:
        c = containers[ci]
        if cw > c["cols"] or ch > c["rows"]:
            continue
        spots = [(col, row)
                 for col in range(c["cols"] - cw + 1)
                 for row in range(c["rows"] - ch + 1)]
        random.shuffle(spots)
        for col, row in spots:
            if all(occ[ci][row + r][col + cl]
                   for r in range(ch) for cl in range(cw)):
                return ci, col, row
    return None


def fresh_occ(containers):
    return [[[True] * c["cols"] for _ in range(c["rows"])] for c in containers]


def build_image(bg, containers, queue, icons_ram, rng, inset=2, max_objs=None,
                overlays=True):
    """Pop icons from `queue` and paste until no more fit. Returns (img, labels).
    `icons_ram` maps path -> preloaded RGBA Image (decoded once, reused).
    When `overlays`, stamp game-style name/count/FiR/marked so the model learns
    to see through them (closes the sim-to-real gap)."""
    img = bg.copy()
    occ = fresh_occ(containers)
    labels = []  # (class_idx, cx, cy, w, h) normalized
    W, H = img.size
    leftover = []
    while queue:
        if max_objs is not None and len(labels) >= max_objs:
            break
        item = queue.pop()
        cls_idx, path, cw, ch = item
        rot = rng.random() < P_ROT90      # rotate this instance 90 deg?
        if rot:
            cw, ch = ch, cw               # footprint swaps when rotated
        spot = place_into(containers, cw, ch, occ)
        if spot is None:
            leftover.append(item)
            continue
        ci, col, row = spot
        c = containers[ci]
        for r in range(ch):
            for cl in range(cw):
                occ[ci][row + r][col + cl] = False
        # pixel rect of the footprint
        x0 = c["x"] + col * c["cw"] + inset
        y0 = c["y"] + row * c["ch"] + inset
        bw = cw * c["cw"] - 2 * inset
        bh = ch * c["ch"] - 2 * inset
        if rng.random() < P_BGCOLOR:   # solid colored cell behind the (transparent) icon
            ImageDraw.Draw(img).rectangle(
                [round(x0 - inset), round(y0 - inset),
                 round(x0 + bw + inset), round(y0 + bh + inset)],
                fill=rng.choice(BG_COLORS))
        ic = icons_ram[path]
        if rot:
            ic = ic.transpose(Image.ROTATE_90)
        ic = ic.resize(
            (max(1, round(bw)), max(1, round(bh))), Image.LANCZOS)
        img.paste(ic, (round(x0), round(y0)), ic)
        if overlays:
            apply_overlays(img, x0, y0, bw, bh, c["cw"], c["ch"], rng)
        cx = (x0 + bw / 2) / W
        cy = (y0 + bh / 2) / H
        labels.append((cls_idx, cx, cy, bw / W, bh / H))
    queue.extend(reversed(leftover))  # carry unplaceable icons to next image
    return img.convert("RGB"), labels


# ---- multiprocessing worker (icons decoded once per process, kept in RAM) ----
_W = {}  # per-process cache: bg, containers, icons_ram, overlays, fonts, names


def _font(size):
    cache = _W.setdefault("_fonts", {})
    if size not in cache:
        f = None
        for p in FONT_CANDIDATES:
            try:
                f = ImageFont.truetype(p, size); break
            except Exception:
                pass
        cache[size] = f or ImageFont.load_default()
    return cache[size]


import string as _string
_NAME_CHARS = _string.ascii_letters + _string.digits + "   .-"  # spaces/punct rare


def _rand_name(rng):
    """RANDOM characters — deliberately NOT real words. Content is irrelevant and
    randomizing it stops the detector from learning the text instead of the icon;
    it can only treat the stamped text as ignorable noise."""
    n = rng.randint(2, 10)
    s = "".join(rng.choice(_NAME_CHARS) for _ in range(n)).strip()
    return s or "X"


def apply_overlays(img, x0, y0, bw, bh, cellw, cellh, rng):
    """Stamp the things the game prints on items so the model learns to see
    THROUGH them: name text (top), stack count (bottom-right), found-in-raid
    check, and marked border. Box (cell footprint) is unchanged — all within.
    Text content is RANDOM (we don't know real names; identity comes from the
    icon pixels, names later from OCR)."""
    d = ImageDraw.Draw(img, "RGBA")
    # --- name text: top-RIGHT edge, small, white + thin outline (random content) ---
    if rng.random() < P_NAME:
        fs = max(8, min(13, int(cellh * 0.13) + rng.randint(-1, 1)))
        font = _font(fs)
        txt = _rand_name(rng)
        while txt and d.textlength(txt, font=font) > bw - 3 and len(txt) > 1:
            txt = txt[:-1]
        tw = d.textlength(txt, font=font)
        d.text((x0 + bw - tw - 2, y0 + 1), txt, font=font,
               fill=(238, 238, 234, 255), stroke_width=1, stroke_fill=(0, 0, 0, 210))
    # --- stack count (bottom-right) ---
    if rng.random() < P_COUNT:
        n = rng.choice([rng.randint(2, 60), rng.randint(2, 60),
                        rng.choice([100, 120, 200, 350, 1000, 5000, 50000])])
        fs = max(9, min(15, int(cellh * 0.17)))
        font = _font(fs)
        s = str(n)
        sw = d.textlength(s, font=font)
        d.text((x0 + bw - sw - 2, y0 + bh - fs - 2), s, font=font,
               fill=(235, 225, 170, 255), stroke_width=2, stroke_fill=(0, 0, 0, 220))
    # --- found-in-raid check (bottom-right). On the now-square grid this is
    #     square; any residual stretch on odd footprints is just training noise. ---
    if _W.get("fir") is not None and rng.random() < P_FIR:
        s = (max(1, round(cellw)), max(1, round(cellh)))
        ov = _W["fir"].resize(s)
        img.alpha_composite(ov, (round(x0 + bw - s[0]), round(y0 + bh - s[1])))
    # --- marked overlay tile (border + category glyph), as the game draws it ---
    if _W.get("marked") and rng.random() < P_MARKED:
        ov = rng.choice(_W["marked"]).resize((max(1, round(bw)), max(1, round(bh))))
        img.alpha_composite(ov, (round(x0), round(y0)))


def _init_worker(bg_path, containers, icon_paths, overlays):
    bg = Image.open(bg_path).convert("RGBA")
    bg.load()
    _W["bg"] = bg
    _W["containers"] = containers
    _W["icons"] = {p: Image.open(p).convert("RGBA") for p in icon_paths}
    for im in _W["icons"].values():
        im.load()
    _W["overlays"] = overlays
    _W["fir"] = None
    _W["marked"] = []
    if overlays:
        fp = os.path.join(OVERLAYS, "fir.png")
        if os.path.exists(fp):
            _W["fir"] = Image.open(fp).convert("RGBA"); _W["fir"].load()
        for m in glob.glob(os.path.join(OVERLAYS, "marked_*.png")):
            im = Image.open(m).convert("RGBA"); im.load(); _W["marked"].append(im)


def _gen_chunk(task):
    """Pack one worker's slice of the placement queue into images on disk."""
    wid, chunk, val_frac, max_objs, seed, overlays = task
    rng = random.Random(seed * 100000 + wid)
    queue = list(chunk)
    bg, containers, icons_ram = _W["bg"], _W["containers"], _W["icons"]
    n = 0
    while queue:
        split = "val" if rng.random() < val_frac else "train"
        img, labels = build_image(bg, containers, queue, icons_ram, rng,
                                  max_objs=max_objs, overlays=overlays)
        if not labels:
            break
        name = f"w{wid:02d}_{n:05d}"
        img.save(os.path.join(OUT, "images", split, name + ".png"))
        with open(os.path.join(OUT, "labels", split, name + ".txt"), "w") as f:
            for cls, cx, cy, w, h in labels:
                f.write(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
        n += 1
    return wid, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-classes", type=int, default=None,
                    help="subset N icons for fast dev (default: all)")
    ap.add_argument("--per-class", type=int, default=12,
                    help="target instances per class")
    ap.add_argument("--max-objs", type=int, default=None,
                    help="cap icons per image (fewer => more, sparser images)")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)),
                    help="parallel generation processes (default: all cores)")
    ap.add_argument("--no-overlays", action="store_true",
                    help="disable game-style name/count/FiR/marked overlays")
    ap.add_argument("--collapse-dups", action="store_true",
                    help="merge exact-duplicate icon groups (shared/links/icon_dups.json) "
                         "into ONE class each; merged classes are flagged ambiguous (OCR resolves)")
    args = ap.parse_args()
    random.seed(args.seed)
    overlays = not args.no_overlays

    icons = load_icons(args.max_classes, args.seed)
    containers = load_grids()

    # class assignment. optionally collapse exact-duplicate icon groups so identical
    # pixels no longer carry contradictory labels (the merged class = "one of these,
    # OCR decides"). non-collapse path is identical to before (1 class per icon).
    rep_of = {}        # icon_no -> representative icon_no (min of its exact-dup group)
    group_icons = {}   # representative icon_no -> sorted [icon_no...] in the group
    if args.collapse_dups:
        dups = json.load(open(os.path.join("shared", "links", "icon_dups.json")))
        for g in dups["groups"]:
            rep = min(g)
            group_icons[rep] = sorted(g)
            for ic in g:
                rep_of[ic] = rep

    def canon(no):
        return rep_of.get(no, no)

    canon_keys = sorted({canon(no) for no, *_ in icons})
    cls_of_canon = {k: i for i, k in enumerate(canon_keys)}
    cls_of = {no: cls_of_canon[canon(no)] for no, *_ in icons}
    nc = len(canon_keys)
    names = {i: str(k) for k, i in cls_of_canon.items()}
    ambiguous = sorted(cls_of_canon[r] for r in group_icons)   # merged-group class idxs
    class_icons = {cls_of_canon[k]: group_icons.get(k, [k]) for k in canon_keys}
    print(f"icons: {len(icons)}  containers: {len(containers)}  overlays: {overlays}  "
          f"nc: {nc}  (collapsed {len(icons)-nc} dup icons into {len(group_icons)} classes)")

    # build placement queue: every class repeated per_class times, shuffled
    queue = []
    for icon_no, path, cw, ch in icons:
        for _ in range(args.per_class):
            queue.append((cls_of[icon_no], path, cw, ch))
    random.shuffle(queue)
    total = len(queue)
    print(f"placements to pack: {total}")

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)

    bg_path = os.path.join(TEMPLATE_DIR, "background.png")
    icon_paths = [p for _, p, _, _ in icons]
    workers = max(1, args.workers)

    import time as _t
    t0 = _t.perf_counter()
    if workers == 1:
        _init_worker(bg_path, containers, icon_paths, overlays)
        _, n = _gen_chunk((0, queue, args.val_frac, args.max_objs, args.seed, overlays))
        idx = n
    else:
        # split the shuffled queue into `workers` contiguous chunks
        from concurrent.futures import ProcessPoolExecutor
        k = (len(queue) + workers - 1) // workers
        chunks = [queue[i:i + k] for i in range(0, len(queue), k)]
        tasks = [(wid, ch, args.val_frac, args.max_objs, args.seed, overlays)
                 for wid, ch in enumerate(chunks)]
        idx = 0
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(bg_path, containers, icon_paths,
                                           overlays)) as ex:
            for wid, n in ex.map(_gen_chunk, tasks):
                idx += n
                print(f"  worker {wid}: {n} imgs")
    dt = _t.perf_counter() - t0
    print(f"wrote {idx} images in {dt:.1f}s using {workers} workers")

    # classes.json: idx->icon# names, plus dedupe metadata (ambiguous merged classes
    # and the candidate icon#s per class) so OCR/linking can resolve merged groups.
    json.dump({"names": names, "ambiguous": ambiguous, "class_icons": class_icons},
              open(os.path.join(OUT, "classes.json"), "w"))
    with open(os.path.join(OUT, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(OUT)}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write(f"nc: {nc}\n")
        f.write("names:\n")
        for i in range(nc):
            f.write(f"  {i}: '{names[i]}'\n")
    print(f"data.yaml + classes.json written to {OUT}  (nc={nc}, {len(ambiguous)} ambiguous)")


if __name__ == "__main__":
    main()
