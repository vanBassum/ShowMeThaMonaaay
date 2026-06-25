"""
kaggle_train.py — runs ON Kaggle (script kernel) to build the deduped dataset and
train the new root model `mona1`. The private dataset `showmethamonaaay-inputs`
provides a single bundle.zip (icon_cache/ + shared/ + tools/ + models/).

Robust to Kaggle's zip handling: it auto-DISCOVERS the inputs anywhere under
/kaggle/input, and if the bundle was left zipped it extracts it first. So it works
whether Kaggle extracts to root, to a subfolder, or not at all.

The synthetic set is generated here (overlays + 90deg rotation + colored bg are all
baked into build_dataset.py, so this run gets every augmentation PLUS the exact-dup
collapse). Warm-starts from the full_v2 backbone; head reinitialises for deduped nc.

Outputs (downloadable from /kaggle/working): mona1_best.pt, mona1_classes.json, mona1_results.csv
"""
import os, sys, glob, zipfile, shutil, subprocess

IN = "/kaggle/input"
WORK = "/kaggle/working"
ROOT_NAME = "mona1"
os.chdir(WORK)


def find(name, isdir, roots):
    for r in roots:
        for h in glob.glob(f"{r}/**/{name}", recursive=True):
            if os.path.isdir(h) == isdir:
                return h
    return None


# if the bundle wasn't auto-extracted, unzip any zip we find into WORK
if not find("icon_cache", True, [IN]):
    for z in glob.glob(f"{IN}/**/*.zip", recursive=True):
        print("extracting", z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(WORK)

roots = [IN, WORK]
cache = find("icon_cache", True, roots)
bd = find("build_dataset.py", False, roots)
assert cache and bd, f"inputs not found: icon_cache={cache} build_dataset.py={bd}"
src_root = os.path.dirname(os.path.dirname(bd))   # .../tools/build_dataset.py -> repo root
print(f"cache={cache}\nsrc_root={src_root}")

# bring code + curated inputs into the writable working dir
for d in ["shared", "tools"]:
    s = os.path.join(src_root, d)
    if os.path.abspath(s) != os.path.abspath(os.path.join(WORK, d)):
        shutil.copytree(s, os.path.join(WORK, d), dirs_exist_ok=True)
os.environ["EFT_ICON_CACHE"] = cache

# ultralytics: prefer Kaggle's preinstalled copy; else install OFFLINE from bundled
# wheels (kernel internet is off unless the account is phone-verified); online last.
try:
    import ultralytics  # noqa: F401
    print("ultralytics preinstalled")
except ImportError:
    whl = find("wheels", True, roots)
    if whl:
        print("installing ultralytics offline from", whl)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-index",
                        "--no-deps", "--find-links", whl,
                        "ultralytics", "ultralytics-thop"], check=True)
    else:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics"], check=True)
    import ultralytics  # verify it imports
    print("ultralytics", ultralytics.__version__)

# 1) generate the deduped dataset (overlays + rotation + bg included)
subprocess.run([sys.executable, "tools/build_dataset.py", "--collapse-dups",
                "--per-class", "40", "--max-objs", "35",
                "--workers", "4", "--seed", "7"], check=True)

# 2) train mona1. warm-start from full_v2 backbone if present, else cold-start.
base = find("full_v2_best.pt", False, roots) or "yolo11n.pt"
print(f"base model: {base}")
subprocess.run([sys.executable, "tools/train.py", "--model", base,
                "--name", ROOT_NAME, "--epochs", "25", "--imgsz", "1536",
                "--patience", "6"], check=True)

# 3) export artifacts to /kaggle/working (downloadable)
run = f"training/runs/{ROOT_NAME}"   # train.py sets project=training/runs
shutil.copy(f"{run}/weights/best.pt", f"{WORK}/{ROOT_NAME}_best.pt")
shutil.copy("training/dataset/classes.json", f"{WORK}/{ROOT_NAME}_classes.json")
shutil.copy(f"{run}/results.csv", f"{WORK}/{ROOT_NAME}_results.csv")

# keep the kernel OUTPUT lean: drop the multi-GB dataset + working copies so
# `kaggle kernels output` only fetches the 3 small artifacts (not 4GB of images).
for d in ["training", "shared", "tools"]:
    shutil.rmtree(os.path.join(WORK, d), ignore_errors=True)
print(f"DONE -> {ROOT_NAME}_best.pt, {ROOT_NAME}_classes.json, {ROOT_NAME}_results.csv")
