"""
Find the actual cell grid INSIDE a container box (the orange GRID boxes).

Method: detect gridline candidates (edge-profile peaks) on each axis, then find
the longest ARITHMETIC PROGRESSION among them (evenly-spaced lines ~cell apart).
This rejects irregular edges (e.g. the rig's vest icon) and tolerates a missing
line here and there, giving the grid's true origin + extent.

find(gray, box) -> (ox, oy, cell, ncols, nrows) or None.
"""
import numpy as np
import cv2

STEP_LO, STEP_HI = 76, 99   # cell pitch range @ 2560x1440


def _peaks(sig, mind=55, n=22):
    """Top-n local peaks of an edge profile, non-max-suppressed by `mind`."""
    idx = []
    for i in np.argsort(sig)[::-1]:
        if sig[i] <= sig.max() * 0.12:
            break
        if all(abs(i - j) >= mind for j in idx):
            idx.append(int(i))
        if len(idx) >= n:
            break
    return sorted(idx)


def _longest_ap(pos):
    """Longest near-arithmetic subsequence of `pos` with step in [STEP_LO,HI]."""
    best = []
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            step = pos[j] - pos[i]
            if not STEP_LO <= step <= STEP_HI:
                continue
            seq = [pos[i], pos[j]]
            for k in range(j + 1, len(pos)):
                if abs(pos[k] - (seq[-1] + step)) <= step * 0.22:
                    seq.append(pos[k])
            if len(seq) > len(best):
                best = seq
    return best


def _axis(profile):
    ap = _longest_ap(_peaks(profile))
    if len(ap) < 2:
        return None
    step = int(round(np.median(np.diff(ap))))
    return ap[0], step, len(ap) - 1   # origin, cell, n_cells


def find(gray, box):
    x0, y0, x1, y1 = box
    sub = gray[y0:y1, x0:x1].astype(np.float32)
    if min(sub.shape) < STEP_LO:
        return None
    col = np.abs(cv2.Sobel(sub, cv2.CV_32F, 1, 0)).sum(0)
    row = np.abs(cv2.Sobel(sub, cv2.CV_32F, 0, 1)).sum(1)
    cx = _axis(col)
    ry = _axis(row)
    if not cx or not ry:
        return None
    cell = int(round((cx[1] + ry[1]) / 2))
    return (x0 + cx[0], y0 + ry[0], cell, cx[2], ry[2])


if __name__ == "__main__":
    import sys
    from PIL import Image
    import containers as c, detectors as d
    pil = Image.open(sys.argv[1] if len(sys.argv) > 1 else "out/last_scan.png").convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    for name, box, t in d.detect_all(c.detect(pil), gray, W, H):
        if t != "GRID":
            continue
        g = find(gray, box)
        if not g:
            print(f"{name}: no grid"); continue
        ox, oy, cell, nc, nr = g
        print(f"{name}: {nc}x{nr} cell={cell} origin=({ox},{oy})")
        for r in range(nr + 1):
            cv2.line(rgb, (ox, oy + r * cell), (ox + nc * cell, oy + r * cell), (0, 255, 0), 1)
        for cc in range(nc + 1):
            cv2.line(rgb, (ox + cc * cell, oy), (ox + cc * cell, oy + nr * cell), (0, 255, 0), 1)
    Image.fromarray(rgb).save("out/_grids.png")
    print("-> out/_grids.png")
