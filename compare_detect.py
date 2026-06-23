"""Side-by-side: baseline vs retrained detector on one screenshot."""
import sys, numpy as np, cv2
from PIL import Image
from ultralytics import YOLO
import detect_items as di

def run(weights, pil, gray, W, H, conf=0.25):
    di._MODEL = YOLO(weights)
    raw = di.nms(di.tiled_detect(di._MODEL, pil, conf))
    kept = [d for d in raw if di.keep_box(gray, *d[:4], W, H)]
    return kept

def draw(pil, dets):
    im = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    for x0,y0,x1,y1,s in dets:
        cv2.rectangle(im,(int(x0),int(y0)),(int(x1),int(y1)),(0,220,0),2)
    return im

pil = Image.open("out/last_scan.png").convert("RGB")
gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
W,H = pil.size
A = run("models/detector_baseline_overlap_e16.pt", pil, gray, W, H)
B = run("runs/detect/items/weights/best.pt", pil, gray, W, H)
print(f"baseline kept {len(A)} | retrained kept {len(B)}")
ia, ib = draw(pil,A), draw(pil,B)
# full side-by-side (scaled)
def lab(im,t):
    cv2.putText(im,t,(20,40),cv2.FONT_HERSHEY_SIMPLEX,1.2,(0,0,255),3); return im
sb = np.vstack([lab(ia.copy(),f"BASELINE  {len(A)} boxes"), lab(ib.copy(),f"RETRAINED  {len(B)} boxes")])
cv2.imwrite("out/_cmp_full.png", sb)
# equipment-panel crop (left), stacked
x0,y0,x1,y1 = 0, int(0.02*H), int(0.30*W), int(0.80*H)
eq = np.hstack([lab(ia[y0:y1,x0:x1].copy(),"BASELINE"), lab(ib[y0:y1,x0:x1].copy(),"RETRAINED")])
cv2.imwrite("out/_cmp_equip.png", eq)
print("-> out/_cmp_full.png, out/_cmp_equip.png")
