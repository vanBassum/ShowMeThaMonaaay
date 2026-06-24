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
from PIL import Image

CACHE = os.path.join(
    os.environ["LOCALAPPDATA"], "Temp", "Battlestate Games",
    "EscapeFromTarkov", "Icon Cache", "live",
)
TEMPLATE_DIR = "templates/screen1"
OUT = "data/yolo"


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


def build_image(bg, containers, queue, icons_ram, inset=2, max_objs=None):
    """Pop icons from `queue` and paste until no more fit. Returns (img, labels).
    `icons_ram` maps path -> preloaded RGBA Image (decoded once, reused)."""
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
        ic = icons_ram[path].resize(
            (max(1, round(bw)), max(1, round(bh))), Image.LANCZOS)
        img.paste(ic, (round(x0), round(y0)), ic)
        cx = (x0 + bw / 2) / W
        cy = (y0 + bh / 2) / H
        labels.append((cls_idx, cx, cy, bw / W, bh / H))
    queue.extend(reversed(leftover))  # carry unplaceable icons to next image
    return img.convert("RGB"), labels


# ---- multiprocessing worker (icons decoded once per process, kept in RAM) ----
_W = {}  # per-process cache: bg, containers, icons_ram


def _init_worker(bg_path, containers, icon_paths):
    bg = Image.open(bg_path).convert("RGBA")
    bg.load()
    _W["bg"] = bg
    _W["containers"] = containers
    _W["icons"] = {p: Image.open(p).convert("RGBA") for p in icon_paths}
    for im in _W["icons"].values():
        im.load()


def _gen_chunk(task):
    """Pack one worker's slice of the placement queue into images on disk."""
    wid, chunk, val_frac, max_objs, seed = task
    rng = random.Random(seed * 100000 + wid)
    queue = list(chunk)
    bg, containers, icons_ram = _W["bg"], _W["containers"], _W["icons"]
    n = 0
    while queue:
        split = "val" if rng.random() < val_frac else "train"
        img, labels = build_image(bg, containers, queue, icons_ram, max_objs=max_objs)
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
    args = ap.parse_args()
    random.seed(args.seed)

    icons = load_icons(args.max_classes, args.seed)
    containers = load_grids()
    print(f"icons/classes: {len(icons)}  containers: {len(containers)}")

    # contiguous class indices; remember original icon number
    cls_of = {icon_no: i for i, (icon_no, *_) in enumerate(icons)}
    names = {i: str(icon_no) for icon_no, i in cls_of.items()}

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
        _init_worker(bg_path, containers, icon_paths)
        _, n = _gen_chunk((0, queue, args.val_frac, args.max_objs, args.seed))
        idx = n
    else:
        # split the shuffled queue into `workers` contiguous chunks
        from concurrent.futures import ProcessPoolExecutor
        k = (len(queue) + workers - 1) // workers
        chunks = [queue[i:i + k] for i in range(0, len(queue), k)]
        tasks = [(wid, ch, args.val_frac, args.max_objs, args.seed)
                 for wid, ch in enumerate(chunks)]
        idx = 0
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(bg_path, containers, icon_paths)) as ex:
            for wid, n in ex.map(_gen_chunk, tasks):
                idx += n
                print(f"  worker {wid}: {n} imgs")
    dt = _t.perf_counter() - t0
    print(f"wrote {idx} images in {dt:.1f}s using {workers} workers")

    json.dump(names, open(os.path.join(OUT, "classes.json"), "w"))
    with open(os.path.join(OUT, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(OUT)}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write(f"nc: {len(icons)}\n")
        f.write("names:\n")
        for i in range(len(icons)):
            f.write(f"  {i}: '{names[i]}'\n")
    print(f"data.yaml + classes.json written to {OUT}")


if __name__ == "__main__":
    main()
