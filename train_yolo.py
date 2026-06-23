"""
Train a single-class 'item' detector on the synthetic dataset.

IMPORTANT: training imgsz must match the inference imgsz in detect_items.py
(IMGSZ there) so the net sees items at the same scale it learned. Both are 960.

Tuned for a 12 GB GPU (RTX 4070): yolov8m @ 960, batch 12 (fits with AMP, watch
the GPU_mem column). On a smaller card drop to yolov8s / lower batch; CPU falls
back to a tiny batch automatically.

Run:  python train_yolo.py [epochs]
Weights land in runs/detect/items/weights/best.pt
"""
import os
import sys
import torch
from ultralytics import YOLO

ROOT = os.path.dirname(__file__)
IMGSZ = 960                              # keep in sync with detect_items.IMGSZ


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    gpu = torch.cuda.is_available()
    model = YOLO("yolov8m.pt")          # 'm': more capacity for recall/precision on 12 GB
    model.train(
        data=os.path.join(ROOT, "data", "yolo", "data.yaml"),
        epochs=epochs,
        imgsz=IMGSZ,
        batch=12 if gpu else 4,
        device=0 if gpu else "cpu",
        patience=20,
        cache=False,                    # no caching (RAM cache OOMs; JPEG decode is cheap)
        project=os.path.join(ROOT, "runs", "detect"),
        name="items",
        exist_ok=True,
        verbose=True,
    )


if __name__ == "__main__":
    main()
