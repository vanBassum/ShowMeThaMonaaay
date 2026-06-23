"""
Feasibility test: identify stash items by template-matching the icon library
over the calibrated grid. For each 1x1 cell we rank all 1x1 icons by an
edge-shape cosine similarity on the cell centre (the name bar / borders are
excluded), and overlay the top guess. Tells us whether template matching is a
viable auto-labeller before we build the full multi-footprint assigner.
"""
import os, json, numpy as np, cv2
from PIL import Image
import stashgrid

DATA = "data"
CENTER = 0.72          # use central 72% of the cell (skip name bar + borders)


def edge_vec(gray_sq):
    """Normalised edge-shape descriptor of a square grayscale patch."""
    g = cv2.GaussianBlur(gray_sq, (3, 3), 0)
    sx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    sy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    m = cv2.magnitude(sx, sy)
    v = m.flatten().astype(np.float32)
    v -= v.mean()
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else v


def load_1x1_templates(side):
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    cs = int(side * CENTER)
    vecs, meta = [], []
    for it in items:
        if it.get("width") != 1 or it.get("height") != 1:
            continue
        p = os.path.join(DATA, "icons", it["id"] + ".webp")
        if not os.path.exists(p):
            continue
        try:
            ic = np.array(Image.open(p).convert("L").resize((side, side)))
        except Exception:
            continue
        off = (side - cs) // 2
        vecs.append(edge_vec(ic[off:off + cs, off:off + cs].astype(np.float32)))
        meta.append(it)
    return np.array(vecs, np.float32), meta


def main():
    pil = Image.open("out/last_scan.png").convert("RGB")
    rgb = np.array(pil); gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    region = (int(0.638 * W), int(0.085 * H), int(0.995 * W), int(0.56 * H))
    g = stashgrid.calibrate(gray, region)
    side = g["pitch"]; cs = int(side * CENTER); off = (side - cs) // 2
    T, meta = load_1x1_templates(side)
    print(f"{len(meta)} 1x1 icon templates; grid {g['cols']}x{g['rows']} pitch {side}")

    ov = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    for r in range(g["rows"]):
        for c in range(g["cols"]):
            x = g["x0"] + c * side; y = g["y0"] + r * side
            cell = gray[y:y + side, x:x + side].astype(np.float32)
            if cell.shape != (side, side):
                continue
            ctr = cell[off:off + cs, off:off + cs]
            if ctr.std() < 12:                      # empty cell
                continue
            scores = T @ edge_vec(ctr)
            best = int(np.argmax(scores))
            sn = meta[best].get("shortName", "?")
            cv2.rectangle(ov, (x, y), (x + side, y + side), (0, 200, 0), 1)
            cv2.putText(ov, sn[:9], (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                        0.34, (60, 255, 255), 1, cv2.LINE_AA)
    crop = ov[g["y0"]:g["y0"] + g["rows"] * side, g["x0"]:g["x0"] + g["cols"] * side]
    crop = cv2.resize(crop, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite("out/_match_test.png", crop)
    print("-> out/_match_test.png")


if __name__ == "__main__":
    main()
