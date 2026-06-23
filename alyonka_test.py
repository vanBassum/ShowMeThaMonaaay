"""Slide the Alyonka icon over the screenshot; report best-match %, location, time."""
import os, json, time, numpy as np, cv2
from PIL import Image

DATA = "data"; PITCH = 84

items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
it = next((i for i in items if "lyonka" in i.get("shortName","").lower()
           or "lyonka" in i.get("name","").lower()), None)
if not it:
    raise SystemExit("Alyonka not found in items.json")
w, h = it.get("width",1), it.get("height",1)
print(f"item: {it['shortName']} | {it['name']} | {w}x{h} | id {it['id']}")

rgb = np.array(Image.open("out/last_scan.png").convert("RGB"))
gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.uint8)
icon = np.array(Image.open(os.path.join(DATA,"icons",it["id"]+".webp")).convert("L")
                .resize((w*PITCH, h*PITCH))).astype(np.uint8)

def grad(img):
    g = cv2.GaussianBlur(img.astype(np.float32),(3,3),0)
    return cv2.magnitude(cv2.Sobel(g,cv2.CV_32F,1,0), cv2.Sobel(g,cv2.CV_32F,0,1))

t0 = time.perf_counter()
res_g = cv2.matchTemplate(gray, icon, cv2.TM_CCOEFF_NORMED)
t_gray = time.perf_counter()-t0
t1 = time.perf_counter()
res_e = cv2.matchTemplate(grad(gray), grad(icon), cv2.TM_CCOEFF_NORMED)
t_edge = time.perf_counter()-t1

_, mg, _, lg = cv2.minMaxLoc(res_g)
_, me, _, le = cv2.minMaxLoc(res_e)
print(f"GRAY: best {mg*100:.1f}%  at px{lg}  (cell ~{lg[0]//PITCH},{lg[1]//PITCH})  in {t_gray*1000:.1f} ms")
print(f"EDGE: best {me*100:.1f}%  at px{le}  (cell ~{le[0]//PITCH},{le[1]//PITCH})  in {t_edge*1000:.1f} ms")
print(f"full-image search (2560x1440), one 1x1 icon: gray {t_gray*1000:.1f} ms / edge {t_edge*1000:.1f} ms")

ov = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
for (mx,my),col,tag in [(lg,(0,220,0),f"GRAY {mg*100:.0f}%"),(le,(0,140,255),f"EDGE {me*100:.0f}%")]:
    cv2.rectangle(ov,(mx,my),(mx+w*PITCH,my+h*PITCH),col,2)
    cv2.putText(ov,tag,(mx,my-4),cv2.FONT_HERSHEY_SIMPLEX,0.5,col,2,cv2.LINE_AA)
cv2.imwrite("out/_alyonka.png", ov)
# also a zoom around the gray peak
zx,zy=lg; z=ov[max(0,zy-120):zy+200, max(0,zx-200):zx+260]
cv2.imwrite("out/_alyonka_zoom.png", cv2.resize(z,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST))
print("-> out/_alyonka.png, out/_alyonka_zoom.png")
