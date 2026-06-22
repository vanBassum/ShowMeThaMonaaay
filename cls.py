"""
Item-icon classifier inference: name a crop with the trained CNN.

  classify(crop, w, h) -> (item_dict, prob)

Footprint (w,h) masks the logits to same-shape items, mirroring the hash
matcher's dimension filter -- a big precision win, since most confusions are
between items of different cell shapes.

Usage (standalone sanity):  python cls.py <crop.png> [--w N --h M]
"""
import os
import sys
import json
import numpy as np
import torch

from cls_model import IconNet, to_tensor

DATA = os.path.join(os.path.dirname(__file__), "data")
_M = None


def model():
    global _M
    if _M is None:
        ck = torch.load(os.path.join(DATA, "cls.pt"), map_location="cpu")
        net = IconNet(ck["nclasses"], pretrained=False)
        net.load_state_dict(ck["state"])
        net.eval()
        items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
        byid = {it["id"]: it for it in items}
        meta = [byid.get(i, {"id": i, "name": i, "shortName": i,
                             "width": 1, "height": 1}) for i in ck["ids"]]
        foot = np.array(ck["foot"])           # (N,2) = (w,h)
        _M = {"net": net, "meta": meta, "fw": foot[:, 0], "fh": foot[:, 1]}
    return _M


@torch.no_grad()
def classify(crop, w=None, h=None, topn=1):
    """Return [(item_dict, prob)] best-first. If w,h given, restrict to items
    of that footprint (falls back to all if none match)."""
    m = model()
    x = to_tensor(crop).unsqueeze(0)
    logits = m["net"](x)[0]
    if w and h:
        mask = torch.from_numpy(((m["fw"] == w) & (m["fh"] == h)).astype(np.float32))
        if mask.any():
            logits = logits.masked_fill(mask == 0, float("-inf"))
    prob = torch.softmax(logits, 0)
    p, idx = prob.topk(min(topn, len(prob)))
    return [(m["meta"][int(i)], float(pp)) for pp, i in zip(p, idx)]


def main():
    from PIL import Image
    if len(sys.argv) < 2:
        print(__doc__)
        return
    w = int(sys.argv[sys.argv.index("--w") + 1]) if "--w" in sys.argv else None
    h = int(sys.argv[sys.argv.index("--h") + 1]) if "--h" in sys.argv else None
    for it, p in classify(Image.open(sys.argv[1]), w, h, topn=5):
        print(f"  p={p:.3f}  {it['shortName']:<18} {it['name']}")


if __name__ == "__main__":
    main()
