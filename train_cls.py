"""
Train the icon-classifier CNN, robust to the in-game look AND grid-free.

Each item icon is kept at its NATIVE aspect ratio (a 5x1 weapon stays 5:1); the
classifier letterboxes it to a square in cls_model.to_tensor, so item SHAPE is a
learned signal -- this replaces the old cell-footprint logit mask. No grid, no
resolution assumptions.

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
RNG = np.random.default_rng(0)
CELL = 64        # render each cell ~64px (native icon scale); aspect preserved


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


def augment(icon_arr, pool, rng):
    """One in-game-like view of an icon array (native aspect preserved)."""
    icon = Image.fromarray(icon_arr)
    w, h = icon.size
    # 1) background bleed
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
    def __init__(self, icons, repeat, pool, train=True):
        self.icons, self.repeat, self.pool, self.train = icons, repeat, pool, train

    def __len__(self):
        return len(self.icons) * self.repeat

    def __getitem__(self, i):
        idx = i % len(self.icons)
        if not self.train:
            return to_tensor(Image.fromarray(self.icons[idx])), idx
        rng = np.random.default_rng(i * 2654435761 % (2**32))
        return to_tensor(augment(self.icons[idx], self.pool, rng)), idx


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    icons, ids = load_icons()
    n = len(ids)
    print(f"{n} classes")
    pool = make_bg_pool()
    print(f"{len(pool)} background images")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    bs = 256 if dev == "cuda" else 128
    print(f"device: {dev}" + (f" ({torch.cuda.get_device_name(0)})"
                              if dev == "cuda" else ""))
    train_dl = DataLoader(IconDS(icons, repeat=10, pool=pool, train=True),
                          batch_size=bs, shuffle=True, num_workers=6,
                          persistent_workers=True, drop_last=True,
                          pin_memory=(dev == "cuda"))
    val_dl = DataLoader(IconDS(icons, repeat=1, pool=pool, train=False),
                        batch_size=512, shuffle=False, num_workers=4,
                        pin_memory=(dev == "cuda"))

    model = IconNet(n).to(dev)
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

    torch.save({"state": model.state_dict(), "ids": ids, "nclasses": n},
               os.path.join(DATA, "cls.pt"))
    print(f"-> {os.path.join(DATA, 'cls.pt')}")


if __name__ == "__main__":
    main()
