"""
pack_for_kaggle.py — stage the Kaggle training inputs into a SINGLE bundle.zip,
ready for `kaggle datasets create/version`.

The synthetic dataset is generated ON Kaggle (it's huge); we only ship the small
INPUTS: the EFT icon cache + curated shared/ inputs + the generator/trainer code +
a warm-start checkpoint (~50MB total). A single bundle.zip avoids Kaggle's flaky
multi-zip extraction (one zip in, the kernel auto-discovers/extracts it).

    python tools/pack_for_kaggle.py                       # -> kaggle_upload/bundle.zip (+ metadata)
    cd kaggle_upload && kaggle datasets create  -p . -m initial   # first upload (private)
    cd kaggle_upload && kaggle datasets version -p . -m "refresh"  # later updates

Then push the kernel (tools/kaggle/) which reads this dataset.
"""
import os, sys, json, glob, zipfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_dataset as b  # for the resolved CACHE path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "training", "kaggle")
UPLOAD = os.path.join(BUILD, "upload")
OWNER = os.environ.get("KAGGLE_USERNAME", "vanbassum")
SLUG = "showmethamonaaay-inputs"
WARMSTART = os.path.join(ROOT, "shared", "models", "archive",
                         "barry-v2", "best.pt")


def build():
    if os.path.isdir(UPLOAD):
        shutil.rmtree(UPLOAD)
    os.makedirs(UPLOAD)
    bundle = os.path.join(UPLOAD, "bundle.zip")

    # collect (src_path, arcname) — tree lives at the zip root: icon_cache/, shared/, tools/, models/
    items = []
    cache_pngs = [p for p in glob.glob(os.path.join(b.CACHE, "*.png"))
                  if os.path.splitext(os.path.basename(p))[0].isdigit()]
    for p in cache_pngs:
        items.append((p, f"icon_cache/{os.path.basename(p)}"))
    for rel in ["shared/templates", "shared/assets", "shared/links/icon_dups.json",
                "tools/build_dataset.py", "tools/train.py"]:
        src = os.path.join(ROOT, rel)
        if os.path.isdir(src):
            for r, _, fs in os.walk(src):
                for f in fs:
                    fp = os.path.join(r, f)
                    items.append((fp, os.path.relpath(fp, ROOT).replace("\\", "/")))
        elif os.path.exists(src):
            items.append((src, rel))
    if os.path.exists(WARMSTART):
        items.append((WARMSTART, "models/full_v2_best.pt"))
    else:
        print("WARN: warm-start checkpoint missing -> kernel will cold-start")

    # offline install wheels (Kaggle kernel internet is off unless phone-verified)
    wheels = glob.glob(os.path.join(BUILD, "wheels", "*.whl"))
    for w in wheels:
        items.append((w, f"wheels/{os.path.basename(w)}"))
    print(f"wheels: {len(wheels)} (offline ultralytics install)")

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in items:
            z.write(src, arc)
    mb = os.path.getsize(bundle) // 1024 // 1024
    print(f"bundled {len(items)} files ({len(cache_pngs)} icons) -> {bundle}  ({mb} MB)")

    json.dump({"title": "ShowMeThaMonaaay inputs", "id": f"{OWNER}/{SLUG}",
               "licenses": [{"name": "CC0-1.0"}]},
              open(os.path.join(UPLOAD, "dataset-metadata.json"), "w"), indent=2)
    print(f"\nstaged -> {UPLOAD}")
    print("next: cd kaggle_upload && kaggle datasets version -p . -m <msg>")


if __name__ == "__main__":
    build()
