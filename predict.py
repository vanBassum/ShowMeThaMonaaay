"""
predict.py — run the single-pass item detector on a screenshot and save an
annotated copy (box + icon identity + confidence).

    python predict.py "Examples/screen 1.png"
    python predict.py img.png --model runs/detect/demo100/weights/best.pt --conf 0.4
"""
import argparse, os
from ultralytics import YOLO
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--model", default="runs/detect/demo100/weights/best.pt")
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--imgsz", type=int, default=1536)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    m = YOLO(args.model)
    r = m.predict(args.image, imgsz=args.imgsz, conf=args.conf,
                  max_det=400, verbose=False)[0]

    im = Image.open(args.image).convert("RGB")
    d = ImageDraw.Draw(im)
    dets = []
    for b in r.boxes:
        x0, y0, x1, y1 = b.xyxy[0].tolist()
        cls, cf = int(b.cls), float(b.conf)
        d.rectangle([x0, y0, x1, y1], outline=(0, 255, 0), width=2)
        d.text((x0 + 2, y0 + 1), f"#{r.names[cls]} {cf:.2f}", fill=(255, 255, 0))
        dets.append((r.names[cls], cf, (round(x0), round(y0), round(x1), round(y1))))

    out = args.out or (os.path.splitext(args.image)[0] + ".pred.png")
    im.save(out)
    print(f"{len(dets)} detections -> {out}")
    for name, cf, box in sorted(dets, key=lambda x: -x[1]):
        print(f"  icon #{name}  conf {cf:.2f}  box {box}")


if __name__ == "__main__":
    main()
