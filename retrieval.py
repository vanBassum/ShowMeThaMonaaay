"""
retrieval.py — embedding retrieval over the real-crop gallery (game→game).

The icon→game gap sinks methods that compare a game crop to the internet icon.
Retrieval sidesteps it: we compare a game crop to OTHER game crops (the ones you
confirmed in the review UI), both passed through the SAME encoder, so the gap
largely cancels. One confirmed crop per item is enough to start matching.

Encoder = the trained IconNet (MobileNetV3-small) reused as a feature extractor
(512-d activation before the classifier head) — no extra model download.

Only TRUSTED gallery entries are indexed (user-corrected, or OCR-sure — OCR is
gap-immune), so the index can't be poisoned by the model's own shaky guesses.
"""
import json
import os

import numpy as np
import torch
from PIL import Image

import cls
from cls_model import to_tensor

ROOT = os.path.dirname(__file__)
GLABELS = os.path.join(ROOT, "gallery", "labels.json")
GCROPS = os.path.join(ROOT, "gallery", "crops")
DEV = "cuda" if torch.cuda.is_available() else "cpu"

_IDX = None
_MTIME = None


def _trusted(e):
    return bool(e.get("corrected")) or (e.get("status") == "sure" and e.get("src") == "ocr")


@torch.no_grad()
def embed(pil):
    """L2-normalized 512-d embedding of a crop (IconNet pre-head activation)."""
    net = cls.model()["net"]
    x = to_tensor(pil).unsqueeze(0).to(DEV)
    f = net.avgpool(net.features(x))
    z = net.head[2](net.head[1](net.head[0](f)))     # Flatten → Linear(576,512) → Hardswish
    v = z[0].detach().cpu().numpy().astype("float32")
    return v / (np.linalg.norm(v) + 1e-8)


def index():
    """Build/refresh the gallery embedding index from TRUSTED labels. Rebuilds
    when labels.json changes. Returns {'E':(N,512), 'ids':[...]} or None."""
    global _IDX, _MTIME
    if not os.path.exists(GLABELS):
        return None
    mt = os.path.getmtime(GLABELS)
    if _IDX is not None and mt == _MTIME:
        return _IDX
    labels = json.load(open(GLABELS, encoding="utf-8"))
    E, ids = [], []
    for e in labels.values():
        if not _trusted(e):
            continue
        p = os.path.join(GCROPS, e["crop"])
        if os.path.exists(p):
            E.append(embed(Image.open(p).convert("RGB")))
            ids.append(e["item_id"])
    _MTIME = mt
    _IDX = {"E": np.stack(E), "ids": ids} if E else None
    return _IDX


@torch.no_grad()
def query(pil, topk=3):
    """Nearest gallery items to a crop. Returns [(item_id, cosine_sim)] best-first,
    aggregated to the max sim per item, or [] if the gallery is empty."""
    idx = index()
    if not idx:
        return []
    sims = idx["E"] @ embed(pil)
    best = {}
    for iid, s in zip(idx["ids"], sims):
        if s > best.get(iid, -1):
            best[iid] = float(s)
    return sorted(best.items(), key=lambda kv: -kv[1])[:topk]
