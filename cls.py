"""
Item-icon classifier inference: name a crop with the trained CNN.

  classify(crop, topn=1) -> [(item_dict, prob)]

Grid-free: the crop is letterboxed (cls_model.to_tensor) so the net sees the
item's true aspect/shape; no cell-footprint mask is needed. Weights are
device-portable (GPU-trained models run CPU-only).

Usage (standalone):  python cls.py <crop.png>
"""
import os
import sys
import json
import math
import numpy as np
import torch

from cls_model import IconNet, to_tensor

DATA = os.path.join(os.path.dirname(__file__), "data")
DEV = "cuda" if torch.cuda.is_available() else "cpu"
ASPECT_TOL = 0.45   # |log(box_aspect) - log(item_aspect)| within this == same shape
_M = None


def model():
    global _M
    if _M is None:
        ck = torch.load(os.path.join(DATA, "cls.pt"), map_location=DEV)
        net = IconNet(ck["nclasses"], pretrained=False)
        net.load_state_dict(ck["state"])
        net.to(DEV).eval()
        items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
        byid = {it["id"]: it for it in items}
        meta = [byid.get(i, {"id": i, "name": i, "shortName": i,
                             "width": 1, "height": 1}) for i in ck["ids"]]
        aspect = np.array([math.log(max(1, it.get("width", 1))
                                    / max(1, it.get("height", 1))) for it in meta])
        _M = {"net": net, "meta": meta, "aspect": aspect}
    return _M


@torch.no_grad()
def classify(crop, topn=1, box_aspect=None):
    """Return [(item_dict, prob)] best-first. If box_aspect (box width/height)
    is given, restrict to items of matching aspect -- a grid-free, scale-free
    shape prior (replaces the old cell-footprint mask). Falls back to all items
    if nothing matches."""
    m = model()
    x = to_tensor(crop).unsqueeze(0).to(DEV)
    logit = m["net"](x)[0].cpu().numpy()
    if box_aspect and box_aspect > 0:
        keep = np.abs(m["aspect"] - math.log(box_aspect)) < ASPECT_TOL
        if keep.any():
            logit = np.where(keep, logit, -1e9)
    prob = torch.softmax(torch.from_numpy(logit), 0)
    p, idx = prob.topk(min(topn, len(prob)))
    return [(m["meta"][int(i)], float(pp)) for pp, i in zip(p, idx)]


def main():
    from PIL import Image
    if len(sys.argv) < 2:
        print(__doc__)
        return
    for it, p in classify(Image.open(sys.argv[1]), topn=5):
        print(f"  p={p:.3f}  {it['shortName']:<18} {it['name']}")


if __name__ == "__main__":
    main()
