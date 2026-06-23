"""
Build a self-contained HTML viewer for a labelled screenshot:
- screenshot + a TOGGLE-able transparent overlay of the labels,
- mouse-wheel ZOOM (to cursor) + click-drag PAN + Fit button,
- boxes coloured by confidence (green ok / orange low / red unmatched),
- a "needs review" list so you can see what's left, then fix it in the JSON.

Edit out/<shot>.truth.json, re-run this, refresh the browser.

Run:  python label_viewer.py [out/last_scan.truth.json]
"""
import os, sys, json, base64, io
from PIL import Image

LBL = sys.argv[1] if len(sys.argv) > 1 else "out/last_scan.truth.json"
data = json.load(open(LBL, encoding="utf-8"))
img_path = data.get("image", "out/last_scan.png")
items = data.get("items", data if isinstance(data, list) else [])

pil = Image.open(img_path).convert("RGB")
W, H = pil.size
buf = io.BytesIO(); pil.save(buf, "JPEG", quality=88)      # full-res so zoom stays sharp
uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def color(it):
    if not it.get("id"):
        return "#ff4d4d"
    s = it.get("score", 1.0)
    return "#39d353" if s >= 0.85 else "#ffa657"


rects, review = [], []
for it in items:
    b = it.get("box")
    if not b:
        continue
    x0, y0, x1, y1 = b
    name = it.get("shortName") or (it.get("ocr", "") + "?")
    c = color(it)
    rects.append(
        f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="{c}" '
        f'fill-opacity="0.16" stroke="{c}" stroke-width="2"/>'
        f'<text x="{x0+3}" y="{y0+15}" font-size="13" fill="{c}" '
        f'font-family="monospace" paint-order="stroke" stroke="#000" '
        f'stroke-width="0.6">{name}</text>')
    if not it.get("id") or it.get("score", 1) < 0.85:
        review.append((it.get("row"), it.get("col"), it.get("ocr", ""),
                       it.get("shortName"), it.get("score", 0)))

n_ok = sum(1 for it in items if it.get("id") and it.get("score", 1) >= 0.85)
n_low = sum(1 for it in items if it.get("id") and it.get("score", 1) < 0.85)
n_bad = sum(1 for it in items if not it.get("id"))
review_rows = "".join(
    f"<tr><td>{r},{c}</td><td>{ocr}</td><td>{sn or '—'}</td><td>{sc:.2f}</td></tr>"
    for r, c, ocr, sn, sc in review) or "<tr><td colspan=4>nothing to review 🎉</td></tr>"

html = f"""<title>Label viewer — {os.path.basename(img_path)}</title>
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif}}
 .bar{{position:sticky;top:0;background:#161b22;padding:10px 16px;display:flex;
   gap:14px;align-items:center;border-bottom:1px solid #30363d;z-index:5;flex-wrap:wrap}}
 button{{background:#238636;color:#fff;border:0;padding:8px 14px;border-radius:6px;
   font-size:14px;cursor:pointer}} button.alt{{background:#30363d}}
 .wrap{{display:flex;gap:14px;padding:14px;align-items:flex-start}}
 .stage{{position:relative;flex:1;min-width:0;height:86vh;overflow:hidden;
   border:1px solid #30363d;background:#000;cursor:grab}}
 #view{{position:absolute;top:0;left:0;transform-origin:0 0;will-change:transform}}
 #view img{{display:block;width:{W}px;height:{H}px}}
 #view svg{{position:absolute;top:0;left:0;width:{W}px;height:{H}px}}
 aside{{width:300px;flex:none;background:#161b22;border:1px solid #30363d;
   border-radius:8px;padding:12px;font-size:13px;max-height:86vh;overflow:auto}}
 table{{width:100%;border-collapse:collapse}} td,th{{padding:3px 6px;text-align:left;
   border-bottom:1px solid #21262d;font-size:12px}}
 .g{{color:#39d353}} .o{{color:#ffa657}} .r{{color:#ff4d4d}} code{{color:#79c0ff}}
</style>
<div class="bar">
 <button onclick="t()">Toggle overlay (space)</button>
 <button class="alt" onclick="fit()">Fit (f)</button>
 <span><b>{len(items)}</b> &nbsp;<span class="g">{n_ok} ok</span>
  <span class="o">{n_low} low</span> <span class="r">{n_bad} unmatched</span></span>
 <span style="opacity:.6">wheel = zoom · drag = pan · edit <code>{os.path.basename(LBL)}</code> &rarr; re-run &rarr; refresh</span>
</div>
<div class="wrap">
 <div class="stage" id="stage">
   <div id="view"><img src="{uri}">
     <svg id="ov" viewBox="0 0 {W} {H}" preserveAspectRatio="none">{''.join(rects)}</svg>
   </div>
 </div>
 <aside>
   <h3 style="margin:4px 0">Needs review ({len(review)})</h3>
   <table><tr><th>cell</th><th>ocr</th><th>match</th><th>score</th></tr>{review_rows}</table>
 </aside>
</div>
<script>
 const stage=document.getElementById('stage'), view=document.getElementById('view'),
       ov=document.getElementById('ov'); const IW={W};
 let s=1,tx=0,ty=0,on=true,drag=false,lx=0,ly=0;
 function apply(){{view.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;}}
 function fit(){{s=stage.clientWidth/IW; tx=0; ty=0; apply();}}
 function t(){{on=!on; ov.style.display=on?'block':'none';}}
 stage.addEventListener('wheel',e=>{{e.preventDefault();
   const r=stage.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
   const ns=Math.min(20,Math.max(0.1, s*(e.deltaY<0?1.15:1/1.15)));
   tx=mx-(mx-tx)*(ns/s); ty=my-(my-ty)*(ns/s); s=ns; apply();}},{{passive:false}});
 stage.addEventListener('mousedown',e=>{{drag=true;lx=e.clientX;ly=e.clientY;stage.style.cursor='grabbing';}});
 addEventListener('mousemove',e=>{{if(!drag)return;tx+=e.clientX-lx;ty+=e.clientY-ly;lx=e.clientX;ly=e.clientY;apply();}});
 addEventListener('mouseup',()=>{{drag=false;stage.style.cursor='grab';}});
 addEventListener('keydown',e=>{{if(e.code==='Space'){{e.preventDefault();t();}}
   if(e.key==='f')fit();}});
 fit();
</script>"""

out = "out/label_viewer.html"
open(out, "w", encoding="utf-8").write(html)
print(f"items {len(items)} | ok {n_ok} low {n_low} unmatched {n_bad}")
print(f"-> {out}  (wheel=zoom, drag=pan, space=toggle, f=fit)")
