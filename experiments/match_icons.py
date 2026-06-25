"""
match_icons.py — link each EFT icon-cache PNG (#N) to a tarkov.dev item.

Both sources render at 64px/cell. Cache icons are RGBA (item on transparent);
tarkov.dev grid icons are RGB (item on a baked dark cell bg). We pre-filter
candidates by cell footprint, then score similarity ONLY inside the cache icon's
alpha silhouette so the background difference can't poison the match.

    python match_icons.py --eval 40      # montage spot-check, no full run
    python match_icons.py                # full run -> data/icon_item_map.json
"""
import os, json, glob, argparse
import numpy as np
from PIL import Image

CACHE = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "Battlestate Games",
                     "EscapeFromTarkov", "Icon Cache", "live")
ITEMS = "data/items.json"
DEVICONS = "data/icons"


def cells(px): return max(1, round((px - 1) / 63))


def load_dev_by_fp():
    """Group tarkov.dev items by (w,h) cells; preload icon arrays at w*64 x h*64."""
    items = json.load(open(ITEMS, encoding="utf-8"))
    by_fp = {}
    for it in items:
        p = os.path.join(DEVICONS, it["id"] + ".webp")
        if not os.path.exists(p):
            continue
        w, h = it["width"], it["height"]
        try:
            im = Image.open(p).convert("RGB").resize((w * 64, h * 64), Image.LANCZOS)
        except Exception:
            continue
        by_fp.setdefault((w, h), []).append((it, np.asarray(im, np.float32)))
    return by_fp


def cache_arr(path):
    im = Image.open(path).convert("RGBA")
    w, h = cells(im.size[0]), cells(im.size[1])
    im = im.resize((w * 64, h * 64), Image.LANCZOS)
    a = np.asarray(im, np.float32)
    return (w, h), a[..., :3], a[..., 3]  # rgb, alpha


def best_matches(rgb, alpha, cands, k=3):
    """Masked-L2 distance to each candidate; return top-k (item, score)."""
    mask = (alpha > 16).astype(np.float32)
    n = mask.sum()
    if n < 1:
        return []
    m3 = mask[..., None]
    scored = []
    for it, dev in cands:
        if dev.shape != rgb.shape:
            continue
        d = ((rgb - dev) * m3) ** 2
        scored.append((float(np.sqrt(d.sum() / (n * 3))), it))
    scored.sort(key=lambda x: x[0])
    return scored[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", type=int, default=0,
                    help="spot-check N random icons into a montage, skip full run")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    by_fp = load_dev_by_fp()
    print("tarkov.dev candidates by footprint:",
          {k: len(v) for k, v in sorted(by_fp.items())[:6]}, "...")
    cache_paths = sorted(glob.glob(os.path.join(CACHE, "*.png")),
                         key=lambda p: int(os.path.splitext(os.path.basename(p))[0])
                         if os.path.splitext(os.path.basename(p))[0].isdigit() else 0)

    if args.eval:
        import random
        random.Random(args.seed).shuffle(cache_paths)
        sample = cache_paths[:args.eval]
        cols = 4
        rows = (len(sample) + cols - 1) // cols
        cell = 150
        lab = 28
        sheet = Image.new("RGB", (cols * cell * 2, rows * (cell + lab)), (30, 30, 30))
        from PIL import ImageDraw
        d = ImageDraw.Draw(sheet)
        for i, p in enumerate(sample):
            fp, rgb, alpha = cache_arr(p)
            top = best_matches(rgb, alpha, by_fp.get(fp, []))
            r, c = divmod(i, cols)
            x = c * cell * 2; y = r * (cell + lab)
            ci = Image.open(p).convert("RGB").resize((cell, cell))
            sheet.paste(ci, (x, y))
            num = os.path.splitext(os.path.basename(p))[0]
            if top:
                score, it = top[0]
                mp = os.path.join(DEVICONS, it["id"] + ".webp")
                mi = Image.open(mp).convert("RGB").resize((cell, cell))
                sheet.paste(mi, (x + cell, y))
                d.text((x + 2, y + cell + 2),
                       f"#{num} -> {it['name'][:34]}  (d{score:.0f})", fill=(0, 255, 0))
            else:
                d.text((x + 2, y + cell + 2), f"#{num} no cand", fill=(255, 80, 80))
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "match_eval.png")
        sheet.save(path)
        print("montage ->", path)
        return

    # full run
    mapping = {}
    for i, p in enumerate(cache_paths):
        num = os.path.splitext(os.path.basename(p))[0]
        if not num.isdigit():
            continue
        fp, rgb, alpha = cache_arr(p)
        top = best_matches(rgb, alpha, by_fp.get(fp, []), k=3)
        if not top:
            mapping[num] = {"match": None, "fp": fp}
            continue
        s0, it0 = top[0]
        s1 = top[1][0] if len(top) > 1 else None
        mapping[num] = {
            "item_id": it0["id"], "name": it0["name"], "short": it0["shortName"],
            "w": it0["width"], "h": it0["height"],
            "price": it0.get("avg24hPrice") or it0.get("lastLowPrice") or it0.get("basePrice"),
            "score": round(s0, 1),
            "margin": round(s1 - s0, 1) if s1 is not None else None,  # gap to 2nd (low => ambiguous)
            "alts": [t[1]["name"] for t in top[1:]],
        }
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(cache_paths)}")
    json.dump(mapping, open("data/icon_item_map.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"wrote data/icon_item_map.json ({len(mapping)} icons)")


if __name__ == "__main__":
    main()
