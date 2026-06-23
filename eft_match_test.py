"""Validate EFT-cache <-> tarkov.dev cross-matching: for a few known items, find
the best-matching EFT render (by footprint + edge-shape) and save side-by-sides."""
import os, glob, json, numpy as np, cv2
from PIL import Image

DATA="data"
CACHE=r'C:\Users\basvi\AppData\Local\Temp\Battlestate Games\EscapeFromTarkov\Icon Cache\live'
KNOWN=["Alyonka","Nails","Matches","Wrench","Morphine","IFAK","Screws"]

def footprint(sz):
    w,h=sz; return (round((w+1)/64), round((h+1)/64))

def edesc(gray, S=64):
    g=cv2.resize(gray.astype(np.float32),(S,S))
    g=cv2.GaussianBlur(g,(3,3),0)
    m=cv2.magnitude(cv2.Sobel(g,cv2.CV_32F,1,0),cv2.Sobel(g,cv2.CV_32F,0,1))
    v=m.flatten(); v-=v.mean(); n=np.linalg.norm(v); return v/n if n>1e-6 else v

# index EFT pngs by footprint, precompute descriptors
eft=[]
for p in glob.glob(CACHE+r'\*.png'):
    im=Image.open(p); fp=footprint(im.size)
    arr=np.array(im.convert("RGBA"))
    rgb=arr[...,:3]; a=arr[...,3:]/255.0
    gray=cv2.cvtColor((rgb*a+128*(1-a)).astype(np.uint8),cv2.COLOR_RGB2GRAY)  # on grey
    eft.append((p,fp,edesc(gray)))
print("indexed",len(eft),"EFT renders")

items=json.load(open(os.path.join(DATA,"items.json"),encoding="utf-8"))
def find(sub):
    for i in items:
        if i.get("shortName","").lower()==sub.lower(): return i
    for i in items:
        if sub.lower() in i.get("shortName","").lower(): return i

for sn in KNOWN:
    it=find(sn)
    if not it: print(sn,"not found"); continue
    w,h=it.get("width",1),it.get("height",1)
    dev=np.array(Image.open(os.path.join(DATA,"icons",it["id"]+".webp")).convert("L"))
    dv=edesc(dev)
    cands=[(p,d) for p,fp,d in eft if fp==(w,h)]
    if not cands: print(f"{sn}: no EFT of footprint {w}x{h}"); continue
    scores=[(float(d@dv),p) for p,d in cands]
    scores.sort(reverse=True)
    best=scores[0]; print(f"{sn:10s} {w}x{h}: best {best[0]*100:.1f}%  ({len(cands)} cands)  -> {os.path.basename(best[1])}")
    # side by side: tarkov.dev | top-3 EFT
    tiles=[cv2.resize(cv2.cvtColor(np.array(Image.open(os.path.join(DATA,'icons',it['id']+'.webp')).convert('RGB')),cv2.COLOR_RGB2BGR),(96,96))]
    for s,p in scores[:3]:
        im=Image.open(p).convert("RGBA"); arr=np.array(im); rgb=arr[...,:3]; al=arr[...,3:]/255.0
        comp=(rgb*al+30*(1-al)).astype(np.uint8)
        tiles.append(cv2.resize(cv2.cvtColor(comp,cv2.COLOR_RGB2BGR),(96,96)))
    cv2.imwrite(f"out/_eftm_{sn}.png", np.hstack(tiles))
print("-> out/_eftm_*.png  (leftmost = tarkov.dev query, then top-3 EFT matches)")
