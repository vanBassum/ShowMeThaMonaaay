"""
kaggle_train.py — runs ON Kaggle (script kernel) to build the deduped dataset and
train the new root model `mona1`. Inputs come from the private dataset staged by
tools/pack_for_kaggle.py and mounted read-only at /kaggle/input.

The synthetic set is generated here (rotation + bg + overlays are all baked into
build_dataset.py, so this run gets every augmentation PLUS the exact-dup collapse).
Warm-starts from the full_v2 backbone; the head reinitialises for the deduped nc.

Outputs (downloadable from the kernel's /kaggle/working):
  mona1_best.pt, mona1_classes.json, mona1_results.csv
"""
import os, sys, shutil, subprocess

INP = "/kaggle/input/showmethamonaaay-inputs"
WORK = "/kaggle/working"
ROOT_NAME = "mona1"          # new ROOT model name (see MODELS.md lineage)

os.chdir(WORK)
# bring the code + curated inputs into the writable working dir
for d in ["shared", "tools"]:
    shutil.copytree(f"{INP}/{d}", f"{WORK}/{d}", dirs_exist_ok=True)
os.environ["EFT_ICON_CACHE"] = f"{INP}/icon_cache"

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics"], check=True)

# 1) generate the deduped dataset (overlays + 90deg rotation + colored bg included)
subprocess.run([sys.executable, "tools/build_dataset.py", "--collapse-dups",
                "--per-class", "40", "--max-objs", "35",
                "--workers", "4", "--seed", "7"], check=True)

# 2) train mona1. warm-start from full_v2 backbone if present, else cold-start.
base = f"{INP}/models/full_v2_best.pt"
model = base if os.path.exists(base) else "yolo11n.pt"
print(f"base model: {model}")
subprocess.run([sys.executable, "tools/train.py", "--model", model,
                "--name", ROOT_NAME, "--epochs", "25", "--imgsz", "1536",
                "--patience", "6"], check=True)

# 3) export artifacts to /kaggle/working (downloadable)
run = f"runs/detect/{ROOT_NAME}"
shutil.copy(f"{run}/weights/best.pt", f"{WORK}/{ROOT_NAME}_best.pt")
shutil.copy("data/yolo/classes.json", f"{WORK}/{ROOT_NAME}_classes.json")
shutil.copy(f"{run}/results.csv", f"{WORK}/{ROOT_NAME}_results.csv")
print(f"DONE -> {ROOT_NAME}_best.pt, {ROOT_NAME}_classes.json, {ROOT_NAME}_results.csv")
