"""
Train a single-class 'item' detector on the synthetic dataset.

CPU-only here, so we keep it light: yolov8n, 640px, early-stopping. The model
only has to learn "icon-in-a-cell vs empty cell / chrome", which converges fast.

Run:  python train_yolo.py [epochs]
Weights land in runs/detect/items/weights/best.pt
"""
import os
import sys
from ultralytics import YOLO

ROOT = os.path.dirname(__file__)


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    model = YOLO("yolov8n.pt")          # transfer from COCO-pretrained backbone
    model.train(
        data=os.path.join(ROOT, "data", "yolo", "data.yaml"),
        epochs=epochs,
        imgsz=640,
        batch=16,
        device="cpu",
        patience=12,
        project=os.path.join(ROOT, "runs", "detect"),
        name="items",
        exist_ok=True,
        verbose=True,
    )


if __name__ == "__main__":
    main()
