"""
Does sliding an item's own icon over the stash (normalized cross-correlation)
peak at the item's true location? Tests known-present items; if even the
correct icon doesn't peak on its own cell, the tarkov.dev icon source is the
blocker (not grid alignment).
"""
import os, json, numpy as np, cv2
from PIL import Image

DATA = "data"
PITCH = 84
KNOWN = ["Morphine", "IFAK", "Nails", "Screws", "Wrench", "Salt", "Matches", "Vodka"]


def find_item(items, sub):
    for it in items:
        if it.get("shortName", "").lower() == sub.lower():
            return it
    for it in items:                       # fallback: contains
        if sub.lower() in it.get("shortName", "").lower():
            return it
    return None


def grad(img):
    g = cv2.GaussianBlur(img.astype(np.float32), (3, 3), 0)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def main():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    rgb = np.array(Image.open("out/last_scan.png").convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    sx0, sy0, sx1, sy1 = int(0.638 * W), int(0.085 * H), int(0.995 * W), int(0.56 * H)
    stash = gray[sy0:sy1, sx0:sx1]
    stash_g = grad(stash)
    ov = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    for sn in KNOWN:
        it = find_item(items, sn)
        if not it:
            print(f"{sn:10s}  (not in DB)"); continue
        w, h = it.get("width", 1), it.get("height", 1)
        p = os.path.join(DATA, "icons", it["id"] + ".webp")
        icon = np.array(Image.open(p).convert("L").resize((w * PITCH, h * PITCH)))
        # grayscale NCC and edge NCC
        rg = cv2.matchTemplate(stash, icon, cv2.TM_CCOEFF_NORMED)
        re = cv2.matchTemplate(stash_g, grad(icon), cv2.TM_CCOEFF_NORMED)
        _, mg, _, lg = cv2.minMaxLoc(rg)
        _, me, _, le = cv2.minMaxLoc(re)
        print(f"{sn:10s} ({w}x{h})  gray-peak {mg:.3f} @cell({lg[0]//PITCH},{lg[1]//PITCH})  "
              f"edge-peak {me:.3f} @cell({le[0]//PITCH},{le[1]//PITCH})")
        # draw edge-peak box
        x, y = sx0 + le[0], sy0 + le[1]
        cv2.rectangle(ov, (x, y), (x + w * PITCH, y + h * PITCH), (0, 220, 0), 2)
        cv2.putText(ov, f"{sn} {me:.2f}", (x + 2, y + 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (60, 255, 255), 1, cv2.LINE_AA)

    crop = ov[sy0:sy1, sx0:sx1]
    crop = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite("out/_slide_test.png", crop)
    print("-> out/_slide_test.png  (boxes = where each icon's edge-NCC peaked)")


if __name__ == "__main__":
    main()
