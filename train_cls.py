"""
Train the icon-classifier CNN, robust to the in-game look AND grid-free.

Each item icon is augmented at its native aspect, then squashed to a square in
cls_model.to_tensor (full detail for elongated items). Item SHAPE is supplied
separately at inference as a grid-free aspect prior (cls.classify), so we keep
detail without a cell grid or resolution assumptions.

Augmentation simulates the on-screen look: translucent-panel background bleed,
colour tint/jitter, blur (upscale softness), gridlines, name bar + count, and
small translate/scale jitter.

Output: data/cls.pt  (weights + ordered class ids)

Run:  python train_cls.py [epochs]   (default 16)
"""
import os
import sys
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

from cls_model import IconNet, to_tensor

ROOT = os.path.dirname(__file__)
DATA = os.path.join(ROOT, "data")
ICONS = os.path.join(DATA, "icons")
LABELED = os.path.join(DATA, "labeled")
RNG = np.random.default_rng(0)
CELL = 64        # render each cell ~64px (native icon scale); aspect preserved
REAL_OVERSAMPLE = 120   # weight each real labeled crop this many times per epoch


def load_icons():
    """Load icons at native aspect (scaled to ~CELL px per cell). Returns a list
    of uint8 HWC arrays (variable size) + parallel class ids."""
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    icons, ids = [], []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if not (it.get("gridImageLink") and os.path.exists(p)):
            continue
        try:
            im = Image.open(p).convert("RGB")
            im = im.resize((max(1, it["width"]) * CELL, max(1, it["height"]) * CELL))
        except Exception:
            continue
        icons.append(np.asarray(im, np.uint8))
        ids.append(it["id"])
    return icons, ids


def load_real(ids):
    """Load real labeled crops from data/labeled/<id>/*.png as (array, class_idx).
    These are real on-screen crops (auto-labeled by autolabel.py or hand-picked)
    and close the synthetic->real gap. Returns [] if none."""
    if not os.path.isdir(LABELED):
        return []
    idx = {i: k for k, i in enumerate(ids)}
    out = []
    for iid in os.listdir(LABELED):
        if iid not in idx:
            continue
        for f in os.listdir(os.path.join(LABELED, iid)):
            try:
                im = Image.open(os.path.join(LABELED, iid, f)).convert("RGB")
            except Exception:
                continue
            out.append((np.asarray(im, np.uint8), idx[iid]))
    return out


def make_bg_pool(k=160):
    """Pool of large blurred 'game world behind a translucent panel' images we
    crop per-call to whatever size an icon needs."""
    pool = []
    for _ in range(k):
        s = int(RNG.integers(120, 360))
        base = int(RNG.integers(10, 55))
        a = np.clip(np.full((s, s, 3), base, np.int16)
                    + RNG.integers(-8, 9, (s, s, 3)), 0, 255).astype(np.uint8)
        img = Image.fromarray(a)
        d = ImageDraw.Draw(img)
        for _ in range(int(RNG.integers(0, 4))):
            cx, cy, r = RNG.integers(0, s), RNG.integers(0, s), int(RNG.integers(20, 120))
            col = tuple(int(v) for v in RNG.integers(30, 150, 3))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        pool.append(img.filter(ImageFilter.GaussianBlur(RNG.uniform(6, 20))))
    shot = os.path.join(ROOT, "test screenshot 1.png")
    if os.path.exists(shot):
        big = Image.open(shot).convert("RGB").filter(ImageFilter.GaussianBlur(8))
        pool += [big] * (k // 4)
    return pool


def bg_like(pool, w, h, rng):
    src = pool[int(rng.integers(0, len(pool)))]
    W, H = src.size
    if W <= w or H <= h:
        return src.resize((w, h))
    x, y = int(rng.integers(0, W - w)), int(rng.integers(0, H - h))
    return src.crop((x, y, x + w, y + h))


def augment(icon_arr, pool, rng, real=False):
    """One in-game-like view of an icon array (native aspect preserved).
    `real` crops already have a real background, so skip the bleed step and
    augment lightly."""
    icon = Image.fromarray(icon_arr)
    w, h = icon.size
    if real:
        img = icon
    else:
        # 1) background bleed (synthetic icons only)
        img = Image.blend(bg_like(pool, w, h, rng), icon, rng.uniform(0.74, 0.96))
    # 2) tint
    if rng.random() < 0.6:
        tint = Image.new("RGB", (w, h), tuple(int(v) for v in rng.integers(30, 220, 3)))
        img = Image.blend(img, tint, rng.uniform(0.0, 0.18))
    # 3) brightness / contrast / colour
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.7, 1.25))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 1.25))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.7, 1.3))
    # 4) gridlines + name bar + count
    d = ImageDraw.Draw(img, "RGBA")
    if rng.random() < 0.7:
        g = int(rng.integers(55, 90))
        d.line([0, 0, 0, h], fill=(g, g, g, 160)); d.line([w - 1, 0, w - 1, h], fill=(g, g, g, 160))
        d.line([0, 0, w, 0], fill=(g, g, g, 160)); d.line([0, h - 1, w, h - 1], fill=(g, g, g, 160))
    if rng.random() < 0.6:
        d.rectangle([0, 0, w, max(8, int(h * 0.16))], fill=(10, 10, 10, 150))
    if rng.random() < 0.5:
        d.rectangle([int(w * 0.7), int(h * 0.8), w, h], fill=(15, 15, 15, 140))
    # 5) blur
    if rng.random() < 0.6:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.3)))
    # 6) small scale jitter (crop/pad back to size keeps aspect)
    if rng.random() < 0.6:
        f = rng.uniform(0.9, 1.1)
        img = img.resize((max(1, int(w * f)), max(1, int(h * f)))).resize((w, h))
    return img


class IconDS(Dataset):
    """Synthetic canonical icons (one per class, repeated) + real labeled crops
    (oversampled). The first `n_synth` indices are synthetic; the rest cycle
    through real crops."""
    def __init__(self, icons, pool, repeat, reals=None, real_oversample=0, train=True):
        self.icons, self.pool, self.repeat, self.train = icons, pool, repeat, train
        self.reals = reals or []
        self.n_synth = len(icons) * repeat
        self.n_real = len(self.reals) * real_oversample if train else 0

    def __len__(self):
        return self.n_synth + self.n_real

    def __getitem__(self, i):
        rng = np.random.default_rng(i * 2654435761 % (2**32))
        if i < self.n_synth:
            idx = i % len(self.icons)
            if not self.train:
                return to_tensor(Image.fromarray(self.icons[idx])), idx
            return to_tensor(augment(self.icons[idx], self.pool, rng)), idx
        arr, cls_idx = self.reals[(i - self.n_synth) % len(self.reals)]
        return to_tensor(augment(arr, self.pool, rng, real=True)), cls_idx


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    resume = "--resume" in sys.argv     # fine-tune the existing cls.pt
    icons, ids = load_icons()
    n = len(ids)
    reals = load_real(ids)
    print(f"{n} classes | {len(reals)} real labeled crops"
          + (" | resuming from cls.pt" if resume else ""))
    pool = make_bg_pool()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    bs = 256 if dev == "cuda" else 128
    print(f"device: {dev}" + (f" ({torch.cuda.get_device_name(0)})"
                              if dev == "cuda" else ""))
    train_dl = DataLoader(IconDS(icons, pool, repeat=10, reals=reals,
                                 real_oversample=REAL_OVERSAMPLE, train=True),
                          batch_size=bs, shuffle=True, num_workers=6,
                          persistent_workers=True, drop_last=True,
                          pin_memory=(dev == "cuda"))
    val_dl = DataLoader(IconDS(icons, pool, repeat=1, train=False),
                        batch_size=512, shuffle=False, num_workers=4,
                        pin_memory=(dev == "cuda"))

    model = IconNet(n).to(dev)
    if resume and os.path.exists(os.path.join(DATA, "cls.pt")):
        model.load_state_dict(torch.load(os.path.join(DATA, "cls.pt"),
                                         map_location=dev)["state"])
    opt = torch.optim.AdamW([
        {"params": model.features.parameters(), "lr": 4e-4},
        {"params": model.head.parameters(), "lr": 2e-3},
    ], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=[8e-4, 3e-3], epochs=epochs, steps_per_epoch=len(train_dl))
    lossf = nn.CrossEntropyLoss(label_smoothing=0.05)

    for ep in range(epochs):
        model.train()
        tot, seen = 0.0, 0
        for x, y in train_dl:
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            opt.zero_grad()
            loss = lossf(model(x), y)
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item() * len(y)
            seen += len(y)
        model.eval()
        correct = 0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
                correct += (model(x).argmax(1) == y).sum().item()
        print(f"epoch {ep+1}/{epochs}  loss {tot/seen:.3f}  val_clean {correct/n:.3f}",
              flush=True)
        # save every epoch so the run can be stopped anytime and still leave a
        # usable model (cls.pt is always the latest completed epoch)
        torch.save({"state": model.state_dict(), "ids": ids, "nclasses": n},
                   os.path.join(DATA, "cls.pt"))
    print(f"-> {os.path.join(DATA, 'cls.pt')}")


if __name__ == "__main__":
    main()
