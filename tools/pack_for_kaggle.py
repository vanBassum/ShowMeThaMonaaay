"""
pack_for_kaggle.py — stage everything the Kaggle training notebook needs into one
folder, ready for `kaggle datasets create/version`.

The synthetic dataset is generated ON Kaggle (it's huge), so we only upload the
small INPUTS: the EFT icon cache + curated shared/ inputs + the generator/trainer
code + a warm-start checkpoint. Generating on Kaggle avoids a multi-GB upload and
stays reproducible.

    python tools/pack_for_kaggle.py                 # stage -> kaggle_pkg/
    cd kaggle_pkg && kaggle datasets create -p .    # first upload (private)
    cd kaggle_pkg && kaggle datasets version -p . -m "refresh cache"   # later updates

Then run the notebook (tools/kaggle_train.ipynb) against this dataset.
"""
import os, sys, json, glob, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_dataset as b  # for the resolved CACHE path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "kaggle_pkg")
# Kaggle dataset slug — change OWNER to your kaggle username.
OWNER = os.environ.get("KAGGLE_USERNAME", "vanbassum")
SLUG = "showmethamonaaay-inputs"
WARMSTART = os.path.join(ROOT, "shared", "models", "archive",
                         "full_v2_2026-06-25", "best.pt")


def stage():
    if os.path.isdir(PKG):
        shutil.rmtree(PKG)
    os.makedirs(PKG)

    # 1) icon cache (the only big-ish part; ~3.7k small PNGs)
    cache_dst = os.path.join(PKG, "icon_cache")
    os.makedirs(cache_dst)
    pngs = [p for p in glob.glob(os.path.join(b.CACHE, "*.png"))
            if os.path.splitext(os.path.basename(p))[0].isdigit()]
    for p in pngs:
        shutil.copy(p, cache_dst)
    print(f"icon_cache: {len(pngs)} pngs")

    # 2) curated inputs (read on Kaggle): templates, overlays, dup groups
    for rel in ["shared/templates", "shared/assets", "shared/links/icon_dups.json"]:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(PKG, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, dst)
    print("shared/: templates + assets + links/icon_dups.json")

    # 3) the generator + trainer (run as-is on Kaggle)
    os.makedirs(os.path.join(PKG, "tools"))
    for f in ["build_dataset.py", "train.py"]:
        shutil.copy(os.path.join(ROOT, "tools", f), os.path.join(PKG, "tools", f))

    # 4) warm-start checkpoint (backbone transfers; head reinits for deduped nc)
    if os.path.exists(WARMSTART):
        os.makedirs(os.path.join(PKG, "models"))
        shutil.copy(WARMSTART, os.path.join(PKG, "models", "full_v2_best.pt"))
        print("warm-start: models/full_v2_best.pt")
    else:
        print("WARN: warm-start checkpoint missing -> notebook will cold-start")

    # 5) Kaggle dataset metadata
    meta = {"title": "ShowMeThaMonaaay inputs",
            "id": f"{OWNER}/{SLUG}",
            "licenses": [{"name": "CC0-1.0"}]}
    json.dump(meta, open(os.path.join(PKG, "dataset-metadata.json"), "w"), indent=2)
    print(f"\nstaged -> {PKG}")
    if OWNER == "CHANGE_ME":
        print("NOTE: set KAGGLE_USERNAME (or edit dataset-metadata.json id) before upload.")
    print("next: cd kaggle_pkg && kaggle datasets create -p . --dir-mode zip")


if __name__ == "__main__":
    stage()
