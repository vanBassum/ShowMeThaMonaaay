"""
train.py — train the single-pass item detector (box + icon identity).

Usage:
    python train.py                       # dev: 3 epochs, yolo11n, imgsz 1280
    python train.py --epochs 100 --model yolo11s --name full
"""
import argparse
from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/yolo/data.yaml")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=3)   # dev default (synth converges fast)
    ap.add_argument("--imgsz", type=int, default=1280)  # tiny 1x1 icons need resolution
    ap.add_argument("--batch", default=-1)              # -1 = auto-fit VRAM
    ap.add_argument("--name", default="dev")
    # IMPORTANT: pin optimizer/lr. optimizer='auto' scales lr by 0.002*5/(4+nc),
    # which collapses to ~3e-6 at nc=3446 and never converges. SGD lr0=0.01 is the
    # standard YOLO setting and is independent of class count.
    ap.add_argument("--optimizer", default="SGD")
    ap.add_argument("--lr0", type=float, default=0.01)
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        name=args.name,
        optimizer=args.optimizer,
        lr0=args.lr0,
        # icons don't flip/rotate in-game; keep geometry, let color jitter do the work
        fliplr=0.0, flipud=0.0, degrees=0.0, scale=0.1, mosaic=0.0,
    )


if __name__ == "__main__":
    main()
