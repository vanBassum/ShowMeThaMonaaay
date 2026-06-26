"""
pack_model.py — assemble a distributable model archive (see docs/PACKAGING.md).

Bundles the model + its bound link map + an icon-hash provenance manifest into one
versioned zip, with a manifest.json (per-file sha256 + an icon-set fingerprint). This
is the model-bound plane; the live catalog (items.json / icons) is fetched at runtime
and is NOT included.

    python tools/pack_model.py barry-v3
    python tools/pack_model.py barry-v3 --out training/release

Inputs (resolved from the repo root):
  shared/models/archive/<name>/best.pt, classes.json   # model + idx->icon-id map
  data/icon_item_map.json                               # icon-id -> item (visual matcher)
  shared/links/icon_overrides.json, links.jsonl         # CURATED baseline links (ours)
  EFT icon cache (EFT_ICON_CACHE or AppData default)    # to hash the trained icons

icon_hashes.json is generated here from the icons the model actually trained on (the
ids in classes.json). For an already-trained model this is a retrofit against the
current cache; going forward emit it from build_dataset.py atomic with training.
"""
import os, sys, json, glob, hashlib, zipfile, argparse, datetime
from PIL import Image
import imagehash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "shared", "models", "archive")
ICON_MAP = os.path.join(ROOT, "data", "icon_item_map.json")
OVERRIDES = os.path.join(ROOT, "shared", "links", "icon_overrides.json")
LINKS_LOG = os.path.join(ROOT, "shared", "links", "links.jsonl")
CACHE = os.environ.get("EFT_ICON_CACHE") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "Battlestate Games",
    "EscapeFromTarkov", "Icon Cache", "live")
MIN_APP_VERSION = "0.1.0"


def cells(px):
    return max(1, round((px - 1) / 63))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def icon_hashes(icon_ids):
    """icon-id -> {sha256(decoded RGBA), dhash(on black), w, h}. Returns (hashes, missing)."""
    out, missing = {}, []
    for i in icon_ids:
        p = os.path.join(CACHE, f"{i}.png")
        if not os.path.exists(p):
            missing.append(i)
            continue
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGB", im.size, (0, 0, 0))
        bg.paste(im, (0, 0), im)
        out[i] = {"sha256": hashlib.sha256(im.tobytes()).hexdigest(),
                  "dhash": str(imagehash.dhash(bg)),
                  "w": cells(im.width), "h": cells(im.height)}
    return out, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="archived model dir, e.g. barry-v3")
    ap.add_argument("--out", default=os.path.join(ROOT, "training", "release"))
    args = ap.parse_args()

    mdir = os.path.join(ARCHIVE, args.name)
    pt = os.path.join(mdir, "best.pt")
    classes_path = os.path.join(mdir, "classes.json")
    for p in (pt, classes_path, ICON_MAP):
        if not os.path.exists(p):
            sys.exit(f"missing required input: {p}")
    model, _, version = args.name.rpartition("-")
    if not model:
        model, version = args.name, ""

    classes = json.load(open(classes_path, encoding="utf-8"))   # idx -> icon-id
    icon_ids = list(dict.fromkeys(classes.values()))            # unique, order-preserving
    print(f"{args.name}: {len(classes)} classes, {len(icon_ids)} unique icon-ids")

    hashes, missing = icon_hashes(icon_ids)
    if missing:
        print(f"  WARNING: {len(missing)} trained icons not in cache (skipped): "
              f"{missing[:8]}{'...' if len(missing) > 8 else ''}")
    fingerprint = hashlib.sha256(
        "\n".join(f"{i}:{hashes[i]['sha256']}" for i in sorted(hashes)).encode()
    ).hexdigest()

    # ---- stage the archive contents (path-in-zip -> source path) ----
    os.makedirs(args.out, exist_ok=True)
    staged = os.path.join(args.out, f"_{args.name}")
    os.makedirs(os.path.join(staged, "model"), exist_ok=True)
    os.makedirs(os.path.join(staged, "links"), exist_ok=True)
    os.makedirs(os.path.join(staged, "icons"), exist_ok=True)

    members = {}  # zip path -> abs source path
    def stage(zip_path, src):
        members[zip_path] = src

    stage("model/best.pt", pt)
    stage("links/icon_item_map.json", ICON_MAP)
    if os.path.exists(OVERRIDES):
        stage("links/icon_overrides.json", OVERRIDES)
    if os.path.exists(LINKS_LOG):
        stage("links/links.jsonl", LINKS_LOG)
    hashes_path = os.path.join(staged, "icons", "icon_hashes.json")
    json.dump(hashes, open(hashes_path, "w", encoding="utf-8"))
    stage("icons/icon_hashes.json", hashes_path)

    manifest = {
        "model": model, "version": version,
        "classes": len(classes), "icon_count": len(hashes),
        "icons_fingerprint": fingerprint,
        "files": {zp: {"sha256": sha256_file(src)} for zp, src in members.items()},
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "min_app_version": MIN_APP_VERSION,
    }
    if missing:
        manifest["icons_missing"] = len(missing)
    manifest_path = os.path.join(staged, "manifest.json")
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), indent=2)

    # ---- zip ----
    zip_path = os.path.join(args.out, f"smtm-model-{args.name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(manifest_path, "manifest.json")
        for zp, src in members.items():
            z.write(src, zp)

    size_mb = os.path.getsize(zip_path) / 1e6
    print(f"\nwrote {zip_path}  ({size_mb:.1f} MB)")
    print(f"  fingerprint {fingerprint[:16]}…  ({len(hashes)} icons hashed)")
    print("  contents: " + ", ".join(["manifest.json"] + list(members)))


if __name__ == "__main__":
    main()
