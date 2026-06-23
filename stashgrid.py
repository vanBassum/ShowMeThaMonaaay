"""
Calibrate the stash cell grid from a screenshot: find the cell pitch (px) and
the grid origin, so each inventory cell maps to an exact pixel box. The stash is
a strict regular grid, so we recover it from the periodicity of the gridline
edges (Sobel projection -> autocorrelation for pitch -> phase for origin).

calibrate(gray, region) -> dict(x0,y0,pitch,cols,rows) for the stash region.
"""
import numpy as np
import cv2

PITCH_RANGE = (60, 110)        # plausible cell pitch @ 1440p (~84px)


def _profile_pitch(prof):
    """Dominant period of a 1-D edge profile via autocorrelation."""
    prof = prof - prof.mean()
    best, bestlag = -1e9, PITCH_RANGE[0]
    for lag in range(*PITCH_RANGE):
        c = np.sum(prof[:-lag] * prof[lag:])
        if c > best:
            best, bestlag = c, lag
    return bestlag


def _phase(prof, pitch):
    """Offset in [0,pitch) whose periodic comb best lines up with the peaks."""
    best, bestoff = -1e9, 0
    for off in range(pitch):
        idx = np.arange(off, len(prof), pitch)
        s = prof[idx].sum()
        if s > best:
            best, bestoff = s, off
    return bestoff


def calibrate(gray, region):
    x0r, y0r, x1r, y1r = region
    sub = gray[y0r:y1r, x0r:x1r].astype(np.float32)
    colp = np.abs(cv2.Sobel(sub, cv2.CV_32F, 1, 0)).sum(0)   # vertical lines
    rowp = np.abs(cv2.Sobel(sub, cv2.CV_32F, 0, 1)).sum(1)   # horizontal lines
    px = _profile_pitch(colp)
    py = _profile_pitch(rowp)
    pitch = int(round((px + py) / 2))                         # square cells
    ox = _phase(colp, pitch)
    oy = _phase(rowp, pitch)
    cols = int((sub.shape[1] - ox) // pitch)
    rows = int((sub.shape[0] - oy) // pitch)
    return {"x0": x0r + ox, "y0": y0r + oy, "pitch": pitch,
            "cols": cols, "rows": rows, "px": px, "py": py}


if __name__ == "__main__":
    import sys
    from PIL import Image
    pil = Image.open(sys.argv[1] if len(sys.argv) > 1 else "out/last_scan.png").convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    # stash region (right block); tune if needed
    region = (int(0.638 * W), int(0.085 * H), int(0.995 * W), int(0.56 * H))
    g = calibrate(gray, region)
    print(g)
    ov = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.rectangle(ov, region[:2], region[2:], (0, 0, 255), 1)
    for c in range(g["cols"] + 1):
        x = g["x0"] + c * g["pitch"]
        cv2.line(ov, (x, g["y0"]), (x, g["y0"] + g["rows"] * g["pitch"]), (0, 255, 0), 1)
    for r in range(g["rows"] + 1):
        y = g["y0"] + r * g["pitch"]
        cv2.line(ov, (g["x0"], y), (g["x0"] + g["cols"] * g["pitch"], y), (0, 255, 0), 1)
    cv2.imwrite("out/_grid_overlay.png", ov)
    print("-> out/_grid_overlay.png  pitch=", g["pitch"], "cols=", g["cols"], "rows=", g["rows"])
