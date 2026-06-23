"""
Train a single-class 'item' detector on the synthetic dataset.

CPU-only here, so we keep it light: yolov8n, 640px, early-stopping. The model
only has to learn "icon-in-a-cell vs empty cell / chrome", which converges fast.

Run:  python train_yolo.py [epochs]
Weights land in runs/detect/items/weights/best.pt
"""
import os
import sys
import torch
from ultralytics import YOLO

ROOT = os.path.dirname(__file__)


DEV_MAX_EPOCHS = 16            # capped to guard against runaway runs — raise for more


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEV_MAX_EPOCHS
    if epochs > DEV_MAX_EPOCHS:
        print(f"[dev] capping {epochs} -> {DEV_MAX_EPOCHS} epochs "
              f"(raise DEV_MAX_EPOCHS in train_yolo.py for a full run)")
        epochs = DEV_MAX_EPOCHS
    data = arg("--data", os.path.join(ROOT, "data", "yolo", "data.yaml"))
    name = arg("--name", "items")
    gpu = torch.cuda.is_available()
    model = YOLO("yolov8s.pt")          # 's' > 'n': more capacity for recall/precision
    # Sized for a 6 GB card (RTX 3060 Laptop): yolov8s @960 batch16 needs ~8.8 GB
    # and silently spills to shared memory (~10x slower). imgsz 640 also matches
    # the inference tile size (detect_items.TILE=640). Bump both on a bigger GPU.
    model.train(
        data=data,
        epochs=epochs,
        imgsz=640,
        batch=8 if gpu else 4,
        device=0 if gpu else "cpu",
        patience=12,
        project=os.path.join(ROOT, "runs", "detect"),
        name=name,
        exist_ok=True,
        verbose=True,
    )


if __name__ == "__main__":
    main()
