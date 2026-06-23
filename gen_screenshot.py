"""
gen_screenshot.py — real-grid screenshot generator (test).

Take a calibrated template (a real screenshot + grids.json from the grid editor),
fill the grid cells with random items (footprint-aware packing), paste their
catalog icons scaled to the cell size, optionally stamp variant overlays
(found-in-raid / marked), and write a labeled "real-life" screenshot.

Outputs (in out/):
  gen_screen.png        the generated screenshot
  gen_screen_boxes.png  same, with YOLO boxes drawn (sanity view)
  gen_screen.txt        YOLO labels (class 0 = item), normalized xywh

Run:  python gen_screenshot.py [template_dir] [--seed N] [--fill 0.8] [--variants]
"""
import json
import os
import random
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(__file__)
ICONS = os.path.join(ROOT, "data", "icons")
OVERLAYS = os.path.join(ROOT, "assets", "overlays")


def arg(flag, default, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def item_pool():
    raw = json.load(open(os.path.join(ROOT, "data", "items.json"), encoding="utf-8"))
    pool = []
    for it in raw:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if it.get("gridImageLink") and os.path.exists(p):
            pool.append((it["id"], max(1, it.get("width", 1)), max(1, it.get("height", 1))))
    return pool


def fits(occ, r, c, fh, fw, rows, cols):
    if r + fh > rows or c + fw > cols:
        return False
    return all(not occ[r + dr][c + dc] for dr in range(fh) for dc in range(fw))


def fill_grid(g, pool, rng, fill):
    """Greedy footprint-aware packing. Returns [(id, x, y, w, h)] in image px."""
    cols, rows = int(g["cols"]), int(g["rows"])
    cw, ch = g["w"] / cols, g["h"] / rows
    occ = [[False] * cols for _ in range(rows)]
    placed = []
    for r in range(rows):
        for c in range(cols):
            if occ[r][c] or rng.random() > fill:
                continue
            maxh, maxw = rows - r, cols - c
            cands = [it for it in pool if it[2] <= maxh and it[1] <= maxw]
            rng.shuffle(cands)
            for iid, fw, fh in cands[:40]:
                if fits(occ, r, c, fh, fw, rows, cols):
                    for dr in range(fh):
                        for dc in range(fw):
                            occ[r + dr][c + dc] = True
                    x, y = g["x"] + c * cw, g["y"] + r * ch
                    placed.append((iid, x, y, fw * cw, fh * ch))
                    break
    return placed


def stamp_variant(cell, rng):
    """Randomly stamp FiR ✓ and/or a marked border+glyph onto a cell RGBA image."""
    w, h = cell.size
    if rng.random() < 0.45:                       # marked: border + category glyph
        cat = rng.choice(["barter", "equipment", "hideout", "other", "task"])
        ov = Image.open(os.path.join(OVERLAYS, f"marked_{cat}.png")).convert("RGBA").resize((w, h))
        cell.alpha_composite(ov)
    if rng.random() < 0.5:                         # found-in-raid ✓ (bottom-right)
        fir = Image.open(os.path.join(OVERLAYS, "fir.png")).convert("RGBA")
        fw, fh = fir.size
        gl = fir.crop((fw - 22, fh - 22, fw, fh)).resize((22, 22))
        cell.alpha_composite(gl, (max(0, w - 22), max(0, h - 22)))
    return cell


def main():
    tdir = next((a for a in sys.argv[1:] if not a.startswith("-") and os.path.isdir(a)),
                os.path.join(ROOT, "templates", "screen1"))
    seed = arg("--seed", 0, int)
    fill = arg("--fill", 0.85, float)
    variants = "--variants" in sys.argv
    rng = random.Random(seed)

    bg = Image.open(os.path.join(tdir, "background.png")).convert("RGBA")
    grids = json.load(open(os.path.join(tdir, "grids.json"), encoding="utf-8"))
    pool = item_pool()
    print(f"{len(pool)} items in pool, {len(grids)} grids, fill={fill}, variants={variants}")

    boxes = []
    for g in grids:
        for iid, x, y, w, h in fill_grid(g, pool, rng, fill):
            icon = Image.open(os.path.join(ICONS, iid + ".webp")).convert("RGBA")
            icon = icon.resize((max(1, round(w)), max(1, round(h))))
            if variants:
                icon = stamp_variant(icon, rng)
            bg.alpha_composite(icon, (round(x), round(y)))
            boxes.append((round(x), round(y), round(w), round(h)))

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    out = bg.convert("RGB")
    out.save(os.path.join(ROOT, "out", "gen_screen.png"))
    # boxes overlay + YOLO labels
    dbg = out.copy()
    d = ImageDraw.Draw(dbg)
    W, H = out.size
    with open(os.path.join(ROOT, "out", "gen_screen.txt"), "w") as f:
        for x, y, w, h in boxes:
            d.rectangle([x, y, x + w, y + h], outline=(57, 217, 138), width=2)
            f.write(f"0 {(x+w/2)/W:.6f} {(y+h/2)/H:.6f} {w/W:.6f} {h/H:.6f}\n")
    dbg.save(os.path.join(ROOT, "out", "gen_screen_boxes.png"))
    print(f"placed {len(boxes)} items -> out/gen_screen.png (+_boxes, +.txt)")


if __name__ == "__main__":
    main()
