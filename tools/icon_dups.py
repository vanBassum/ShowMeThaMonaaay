"""
icon_dups.py — group EFT cache icons into visual-duplicate clusters, so we know
which icon-ids are inherently ambiguous (keys/dogtags/variants) and need OCR,
independent of YOLO.

Duplicates must share a cell footprint; phash squashes aspect, so we only ever
compare same-footprint icons.

Methods (pick with --method, tune with --size/--dist):
  exact   pixel-perfect: identical RGBA bytes (dist ignored). Zero false group.
  phash   perceptual DCT hash, --size bits/side (8=coarse, 16=fine), --dist Hamming
  dhash   gradient hash, same knobs
  ahash   average hash, same knobs

  python icon_dups.py --compare              # stats table across methods
  python icon_dups.py --method phash --size 16 --dist 4 --html   # save + page
"""
import os, json, glob, argparse, hashlib, shutil
from collections import defaultdict
from PIL import Image
import imagehash

CACHE = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "Battlestate Games",
                     "EscapeFromTarkov", "Icon Cache", "live")


def cells(px):
    return max(1, round((px - 1) / 63))


def _load(path):
    im = Image.open(path).convert("RGBA")
    fp = (cells(im.size[0]), cells(im.size[1]))
    bg = Image.new("RGB", im.size, (0, 0, 0))
    bg.paste(im, (0, 0), im)
    return fp, im, bg


def sig(path, method, size):
    """Return (footprint, signature) for the chosen method."""
    fp, rgba, rgb = _load(path)
    if method == "exact":
        return fp, hashlib.sha1(rgba.tobytes()).hexdigest()
    if method == "phash":
        return fp, imagehash.phash(rgb, hash_size=size)
    if method == "dhash":
        return fp, imagehash.dhash(rgb, hash_size=size)
    if method == "ahash":
        return fp, imagehash.average_hash(rgb, hash_size=size)
    raise ValueError(method)


def cluster(method, size, dist):
    paths = sorted(glob.glob(os.path.join(CACHE, "*.png")),
                   key=lambda p: int(os.path.splitext(os.path.basename(p))[0])
                   if os.path.splitext(os.path.basename(p))[0].isdigit() else 0)
    by_fp = defaultdict(list)
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        if not stem.isdigit():
            continue
        fp, s = sig(p, method, size)
        by_fp[fp].append((int(stem), s))
    total = sum(len(v) for v in by_fp.values())

    parent = {}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb

    for fp, items in by_fp.items():
        for i, _ in items:
            parent[i] = i
        if method == "exact":                       # bucket identical hashes
            buckets = defaultdict(list)
            for i, s in items:
                buckets[s].append(i)
            for ids in buckets.values():
                for j in ids[1:]:
                    union(ids[0], j)
        else:                                        # link within Hamming dist
            for a in range(len(items)):
                ia, ha = items[a]
                for b in range(a + 1, len(items)):
                    ib, hb = items[b]
                    if (ha - hb) <= dist:
                        union(ia, ib)

    clusters = defaultdict(list)
    for i in parent:
        clusters[find(i)].append(i)
    groups = sorted([sorted(v) for v in clusters.values() if len(v) > 1],
                    key=len, reverse=True)
    ambiguous = sorted(i for g in groups for i in g)
    return total, groups, ambiguous


def write_html(groups, label, path, maxg=120):
    """Copy the shown icons into out/icons/ and reference them with RELATIVE
    links, so a Live Preview / static HTTP server (serving the workspace) can
    load them (file:// to AppData won't work there)."""
    outdir = os.path.dirname(path) or "."
    icondir = os.path.join(outdir, "icons")
    os.makedirs(icondir, exist_ok=True)
    h = ["<meta charset=utf8><style>body{background:#1a1a1a;color:#ddd;"
         "font:13px sans-serif} .g{display:flex;flex-wrap:wrap;gap:4px;align-items:center;"
         "padding:6px;border-bottom:1px solid #333} .g b{width:70px;color:#8af}"
         " img{height:48px;background:#000;border:1px solid #444}"
         " figure{margin:0;text-align:center} figcaption{font-size:10px;color:#888}</style>",
         f"<h3>{label} — {len(groups)} duplicate groups (showing {min(maxg,len(groups))})</h3>"]
    for g in groups[:maxg]:
        h.append(f"<div class='g'><b>{len(g)}x</b>")
        for i in g[:24]:
            dst = os.path.join(icondir, f"{i}.png")
            if not os.path.exists(dst):
                src = os.path.join(CACHE, f"{i}.png")
                if os.path.exists(src):
                    shutil.copy(src, dst)
            h.append(f"<figure><img src='icons/{i}.png'>"
                     f"<figcaption>{i}</figcaption></figure>")
        if len(g) > 24:
            h.append(f"<span>+{len(g)-24} more</span>")
        h.append("</div>")
    open(path, "w", encoding="utf-8").write("\n".join(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="phash", choices=["exact", "phash", "dhash", "ahash"])
    ap.add_argument("--size", type=int, default=16)
    ap.add_argument("--dist", type=int, default=4)
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()

    if args.compare:
        configs = [("exact", 0, 0), ("phash", 8, 6), ("phash", 16, 4),
                   ("phash", 16, 2), ("dhash", 16, 4)]
        print(f"{'method':14s} {'groups':>7} {'ambig':>7} {'ambig%':>7} {'biggest':>8}")
        for m, s, d in configs:
            total, groups, amb = cluster(m, s, d)
            label = f"{m}{'' if m=='exact' else f'-{s}/d{d}'}"
            big = len(groups[0]) if groups else 0
            print(f"{label:14s} {len(groups):>7} {len(amb):>7} "
                  f"{100*len(amb)/total:>6.0f}% {big:>8}")
            write_html(groups, label, f"out/dups_{label.replace('/','_')}.html")
        print(f"\n(of {total} icons)  HTML pages -> out/dups_*.html")
        return

    total, groups, amb = cluster(args.method, args.size, args.dist)
    label = f"{args.method}{'' if args.method=='exact' else f'-{args.size}/d{args.dist}'}"
    icon_group = {}
    for gi, g in enumerate(groups):
        for i in g:
            icon_group[str(i)] = gi
    json.dump({"method": label, "groups": groups, "ambiguous": amb,
               "icon_group": icon_group},
              open("shared/links/icon_dups.json", "w"))
    print(f"{label}: {len(groups)} groups, {len(amb)}/{total} ambiguous "
          f"({100*len(amb)/total:.0f}%) -> shared/links/icon_dups.json")
    if args.html:
        write_html(groups, label, f"out/dups_{label.replace('/','_')}.html")
        print(f"-> out/dups_{label.replace('/','_')}.html")


if __name__ == "__main__":
    main()
