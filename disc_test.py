"""Discrimination: peak NCC of items KNOWN-present vs KNOWN-absent in the stash.
If present >> absent, sliding-match is a usable auto-labeller (pick a threshold)."""
import os, json, numpy as np, cv2
from PIL import Image

DATA="data"; PITCH=84
PRESENT=["Alyonka","Morphine","IFAK","Screws","Nails","Wrench","Salt","Matches","Crackers","Tushonka","Sugar","Vodka"]
ABSENT =["LEDX","GPU","Bitcoin","Ophthalmoscope","Defibrillator","Virtex","Magazine case","Intelligence","Ledx","Moonshine","Propane","SSD"]

items=json.load(open(os.path.join(DATA,"items.json"),encoding="utf-8"))
def find(sub):
    for i in items:
        if i.get("shortName","").lower()==sub.lower(): return i
    for i in items:
        if sub.lower() in i.get("shortName","").lower() or sub.lower() in i.get("name","").lower(): return i
    return None

rgb=np.array(Image.open("out/last_scan.png").convert("RGB"))
gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
H,W=gray.shape
stash=gray[int(0.085*H):int(0.56*H), int(0.638*W):int(0.995*W)]

def peak(sub):
    it=find(sub)
    if not it: return None
    w,h=it.get("width",1),it.get("height",1)
    p=os.path.join(DATA,"icons",it["id"]+".webp")
    if not os.path.exists(p): return None
    icon=np.array(Image.open(p).convert("L").resize((w*PITCH,h*PITCH)))
    if icon.shape[0]>stash.shape[0] or icon.shape[1]>stash.shape[1]: return (it,w,h,None)
    r=cv2.matchTemplate(stash,icon.astype(np.uint8),cv2.TM_CCOEFF_NORMED)
    return (it,w,h,cv2.minMaxLoc(r)[1])

print(f"{'item':16s} {'WxH':5s} {'peak%':>6s}  group")
rows=[]
for sn in PRESENT:
    r=peak(sn)
    if r and r[3] is not None: rows.append((r[0]['shortName'],f"{r[1]}x{r[2]}",r[3]*100,"PRESENT"))
for sn in ABSENT:
    r=peak(sn)
    if r and r[3] is not None: rows.append((r[0]['shortName'],f"{r[1]}x{r[2]}",r[3]*100,"absent"))
for nm,wh,pc,grp in rows:
    print(f"{nm:16s} {wh:5s} {pc:6.1f}  {grp}")
pres=[pc for _,_,pc,g in rows if g=="PRESENT"]; absn=[pc for _,_,pc,g in rows if g=="absent"]
if pres and absn:
    print(f"\nPRESENT: min {min(pres):.1f} / mean {np.mean(pres):.1f} / max {max(pres):.1f}")
    print(f"absent : min {min(absn):.1f} / mean {np.mean(absn):.1f} / max {max(absn):.1f}")
    print(f"separation gap (present-min - absent-max): {min(pres)-max(absn):.1f} pts")
