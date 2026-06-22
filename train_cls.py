"""
Train an icon-classifier CNN that is robust to the in-game look.

The wall the perceptual-hash hit: Tarkov's inventory panels are translucent, so
the blurred game world bleeds through every icon, and 64px icons are upscaled to
~84px cells. A clean DB icon therefore looks quite different from its on-screen
crop. We fix that by TRAINING on the clean icons with augmentation that
SIMULATES that domain shift:
  * background bleed  -> blend the icon over a blurred random/world background
  * tint + jitter     -> colour/brightness/contrast variation
  * blur              -> upscale softness
  * gridlines / name bar / count overlay
  * small transl/scale jitter (loose-box alignment)

Output: data/cls.pt  (weights + ordered class ids + per-class footprint)

Run:  python train_cls.py [epochs]   (default 14)
"""
import os
import sys
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

from cls_model import IconNet, to_tensor, INPUT

ROOT = os.path.dirname(__file__)
DATA = os.path.join(ROOT, "data")
ICONS = os.path.join(DATA, "icons")
RNG = np.random.default_rng(0)


def load_icons():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    icons, ids, foot = [], [], []
    for it in items:
        p = os.path.join(ICONS, it["id"] + ".webp")
        if not (it.get("gridImageLink") and os.path.exists(p)):
            continue
        try:
            im = Image.open(p).convert("RGB").resize((INPUT, INPUT))
        except Exception:
            continue
        icons.append(np.asarray(im, np.uint8))
        ids.append(it["id"])
        foot.append((it["width"], it["height"]))
    return np.stack(icons), ids, foot


def make_backgrounds(k=240):
    """Procedural blurred 'game world behind a dark panel' tiles for bleed."""
    bgs = []
    for _ in range(k):
        base = int(RNG.integers(10, 55))
        a = np.full((INPUT, INPUT, 3), base, np.uint8)
        a = np.clip(a + RNG.integers(-8, 9, (INPUT, INPUT, 3)), 0, 255).astype(np.uint8)
        img = Image.fromarray(a)
        d = ImageDraw.Draw(img)
        for _ in range(int(RNG.integers(0, 4))):
            cx, cy = RNG.integers(0, INPUT), RNG.integers(0, INPUT)
            r = int(RNG.integers(10, 50))
            col = tuple(int(v) for v in RNG.integers(30, 150, 3))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        bgs.append(img.filter(ImageFilter.GaussianBlur(RNG.uniform(6, 20))))
    # add a few crops of the real screenshot's blurred world, if present
    shot = os.path.join(ROOT, "test screenshot 1.png")
    if os.path.exists(shot):
        big = Image.open(shot).convert("RGB").filter(ImageFilter.GaussianBlur(8))
        W, H = big.size
        for _ in range(k // 4):
            s = int(RNG.integers(60, 240))
            x, y = int(RNG.integers(0, W - s)), int(RNG.integers(0, H - s))
            bgs.append(big.crop((x, y, x + s, y + s)).resize((INPUT, INPUT)))
    return bgs


def augment(icon_arr, bgs, rng, train=True):
    """Render one in-game-like view of a clean icon array (HWC uint8)."""
    icon = Image.fromarray(icon_arr)
    if not train:
        return icon
    # 1) background bleed: icon over a blurred background, icon dominant
    bg = bgs[int(rng.integers(0, len(bgs)))]
    alpha = rng.uniform(0.74, 0.96)
    img = Image.blend(bg, icon, alpha)
    # 2) global colour tint
    if rng.random() < 0.6:
        tint = Image.new("RGB", (INPUT, INPUT),
                         tuple(int(v) for v in rng.integers(30, 220, 3)))
        img = Image.blend(img, tint, rng.uniform(0.0, 0.18))
    # 3) brightness / contrast / colour jitter
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.7, 1.25))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 1.25))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.7, 1.3))
    # 4) gridlines + name bar + count, like the game draws
    d = ImageDraw.Draw(img, "RGBA")
    if rng.random() < 0.7:
        g = int(rng.integers(55, 90))
        for k in (0, INPUT - 1):
            d.line([k, 0, k, INPUT], fill=(g, g, g, 160))
            d.line([0, k, INPUT, k], fill=(g, g, g, 160))
    if rng.random() < 0.6:
        d.rectangle([0, 0, INPUT, int(rng.integers(8, 14))], fill=(10, 10, 10, 150))
    if rng.random() < 0.5:
        d.rectangle([INPUT - 18, INPUT - 12, INPUT, INPUT], fill=(15, 15, 15, 140))
    # 5) blur (upscale softness)
    if rng.random() < 0.6:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.3)))
    # 6) small translate/scale jitter
    if rng.random() < 0.7:
        s = rng.uniform(0.9, 1.12)
        ns = max(8, int(INPUT * s))
        big = img.resize((ns, ns))
        ox = int(rng.integers(0, abs(ns - INPUT) + 1)) * (1 if ns > INPUT else -1)
        oy = int(rng.integers(0, abs(ns - INPUT) + 1)) * (1 if ns > INPUT else -1)
        img = big.crop((ox, oy, ox + INPUT, oy + INPUT)) if ns >= INPUT else \
            img.resize((ns, ns)).crop((0, 0, INPUT, INPUT))
    return img


class IconDS(Dataset):
    def __init__(self, icons, repeat, bgs, train=True):
        self.icons, self.repeat, self.bgs, self.train = icons, repeat, bgs, train

    def __len__(self):
        return len(self.icons) * self.repeat

    def __getitem__(self, i):
        idx = i % len(self.icons)
        # per-sample rng seeded by index so workers stay deterministic-ish
        rng = np.random.default_rng(i * 2654435761 % (2**32))
        img = augment(self.icons[idx], self.bgs, rng, self.train)
        return to_tensor(img), idx


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    icons, ids, foot = load_icons()
    n = len(ids)
    print(f"{n} classes")
    bgs = make_backgrounds()
    print(f"{len(bgs)} background tiles")

    train_dl = DataLoader(IconDS(icons, repeat=10, bgs=bgs, train=True),
                          batch_size=128, shuffle=True, num_workers=6,
                          persistent_workers=True, drop_last=True)
    val_dl = DataLoader(IconDS(icons, repeat=1, bgs=bgs, train=False),
                        batch_size=256, shuffle=False, num_workers=4)

    dev = "cpu"
    model = IconNet(n).to(dev)
    # lower LR on the pretrained backbone, higher on the fresh head
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
            opt.zero_grad()
            out = model(x)
            loss = lossf(out, y)
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item() * len(y)
            seen += len(y)
        # val: clean icons -> top-1 (sanity, should be ~1.0)
        model.eval()
        correct = 0
        with torch.no_grad():
            for x, y in val_dl:
                correct += (model(x).argmax(1) == y).sum().item()
        print(f"epoch {ep+1}/{epochs}  loss {tot/seen:.3f}  val_clean {correct/n:.3f}",
              flush=True)

    torch.save({"state": model.state_dict(), "ids": ids, "foot": foot,
                "nclasses": n}, os.path.join(DATA, "cls.pt"))
    print(f"-> {os.path.join(DATA, 'cls.pt')}")


if __name__ == "__main__":
    main()
