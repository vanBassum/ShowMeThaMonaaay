"""
Auto-detect the stash grid (origin, cell size, columns, rows) from a screenshot.

The stash is a large block of evenly-spaced grid lines. We:
  1. build a binary edge map (robust to averaging dilution),
  2. find the cell pitch via autocorrelation of the edge column-profile,
  3. comb-correlate to find the grid PHASE in each axis (tolerates lines hidden
     behind items, because the comb sums over all teeth),
  4. grow the contiguous run of strong teeth to get origin + extent.

detect(gray) -> dict(cell, ox, oy, ncols, region_bottom) or None when no grid.
"""
import numpy as np
import cv2

PITCH_LO, PITCH_HI = 45, 160   # plausible cell size in px across resolutions
MIN_COLS, MIN_ROWS = 6, 4      # a real stash shows at least this many cells


def _edge_profiles(gray):
    sx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0))
    sy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    ex = (sx > np.percentile(sx, 90)).astype(np.float32)
    ey = (sy > np.percentile(sy, 90)).astype(np.float32)
    return ex.sum(axis=0), ey.sum(axis=1)   # per-column, per-row edge counts


def _pitch(profile):
    s = profile - profile.mean()
    ac = np.correlate(s, s, mode="full")[len(s) - 1:]
    seg = ac[PITCH_LO:PITCH_HI]
    return PITCH_LO + int(np.argmax(seg)) if len(seg) else None


def _comb(profile, pitch):
    """Return (origin, count): the strongest evenly-spaced run of grid lines."""
    n = len(profile)
    # best phase = offset whose comb of teeth collects the most edge energy
    best_off, best_score = 0, -1.0
    for off in range(pitch):
        idx = np.arange(off, n, pitch)
        score = profile[idx].sum()
        if score > best_score:
            best_off, best_score = off, score
    # tooth strengths along that phase; keep the longest contiguous strong run
    teeth = np.arange(best_off, n, pitch)
    vals = profile[teeth]
    thr = vals.max() * 0.30
    strong = vals >= thr
    best_run = (0, 0)  # (start_index_into_teeth, length)
    i = 0
    while i < len(strong):
        if strong[i]:
            j = i
            while j < len(strong) and strong[j]:
                j += 1
            if j - i > best_run[1]:
                best_run = (i, j - i)
            i = j
        else:
            i += 1
    start, length = best_run
    return int(teeth[start]), length


def detect(gray):
    col, row = _edge_profiles(gray)
    pitch = _pitch(col) or _pitch(row)
    if not pitch:
        return None
    ox, ncols_lines = _comb(col, pitch)
    oy, nrows_lines = _comb(row, pitch)
    ncols, nrows = ncols_lines - 1, nrows_lines - 1
    if ncols < MIN_COLS or nrows < MIN_ROWS:
        return None
    return dict(cell=int(pitch), ox=int(ox), oy=int(oy),
                ncols=int(ncols), region_bottom=int(oy + nrows * pitch))


if __name__ == "__main__":
    import sys
    from PIL import Image
    g = cv2.cvtColor(np.array(Image.open(sys.argv[1]).convert("RGB")), cv2.COLOR_RGB2GRAY)
    print(detect(g))
