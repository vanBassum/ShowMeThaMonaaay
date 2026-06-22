# ShowMeThaMonaaay — Status & Next Steps

Tarkov inventory valuer: screenshot your stash/loot, detect every item, identify
it, and rank by ₽-per-slot. This doc is a handoff for continuing on another
(more powerful) machine.

**Active branch: `grid-free`** (all current work is here, not `master`).

---

## Architecture (grid-free, resolution-independent)

Two decoupled stages — **detection** (where) then **classification** (what):

```
screenshot → YOLO detector → item boxes → crop each → classifier(s) → names → ₽/slot list
```

- **Detector** = single-class ("item") YOLO, trained on synthetic inventory
  composites. Finds item boxes anywhere; no cell grid, no fixed resolution.
- **Classifier** = the "what is it" stage. We have **four independent methods**
  and fuse them (agreement = high confidence):
  | Method | Strength | Weakness |
  |---|---|---|
  | CNN (`cls.py`) | best all-rounder | under-confident on real crops |
  | OCR (`ocr.py`) | great where the game prints the name | silent/noisy otherwise |
  | pHash | ok tiebreaker | falls apart under offset/reframe |
  | ORB | precise when it fires | usually silent (icons low-texture) |

No grid / cell-pitch anywhere: detector is scale-invariant (trained across cell
sizes), classifier letterbox→squash + a **scale-free aspect prior** replaces the
old footprint mask. Works at any resolution.

---

## Current state

**Detection — good, being improved.**
- Finds essentially all items on both test screenshots, any resolution.
- Known issues: occasional **panel-sized / oversized** boxes, some **merged**
  adjacent items, a few **misses** in dense stash.
- A retrain is in progress with a richer generator + bigger model (see below).

**Classification — the lagging half.**
- Key finding: the CNN is usually **right but under-confident** on real crops
  (true item often at p≈0.1–0.5, below the 0.40 gate) — a *calibration* problem
  from the synthetic→real gap, **not** a knowledge gap. (`val_clean`≈0.94 on
  clean icons; ~87% on its own augmentation.)
- More synthetic epochs will NOT fix this. **Real labeled crops will.**
- The ensemble (`compare.py`) already corrects individual-method errors via
  consensus (e.g. fixes CNN's "SP BT" → "BCP FMJ").

**Proven mechanism for the fix (the flywheel):**
1. `compare.py --save` / `autolabel.py` → where ≥2 methods agree, save the crop
   as a high-precision label to `data/labeled/<id>/` (zero manual work; OCR of
   the game's printed name is a strong auto-label source).
2. `train_cls.py --resume` mixes those real crops (oversampled) and fine-tunes.
3. Better CNN → more agreement → more labels → repeat.

---

## Repo map

| File | Role |
|---|---|
| `fetch_items.py` | download item metadata + icons from tarkov.dev → `data/` |
| `gen_synth.py` | generate synthetic YOLO detection dataset (real bg, UI negatives, adjacent pairs, partials) |
| `train_yolo.py` | train the detector (currently `yolov8s` @ imgsz 960) |
| `cls_model.py` | classifier net (MobileNetV3-small) + preprocessing |
| `train_cls.py` | train/fine-tune classifier; `--resume` to continue; saves every epoch |
| `cls.py` | classifier inference (+ aspect prior) |
| `ocr.py` | Windows OCR of the printed item name |
| `detect_items.py` | **main pipeline**: detect → classify → list + overlay; `scan_pil()` API |
| `compare.py` | run+fuse all 4 methods; `--save` mints consensus labels |
| `autolabel.py` | OCR+CNN agreement → auto-labeled real crops |
| `methods_report.py` | 4 per-method overlays + `methods.txt` comparison table |
| `ui.py` | Tkinter F2-hotkey UI (uses `scan_pil`) |
| `capture.py` | screen-grab helper |

Git-ignored (regenerate locally): `data/` (icons, items.json, cls.pt, yolo/,
labeled/), `runs/`, `*.pt`, `out/`.

---

## Setup on the new machine

```bash
pip install ultralytics imagehash opencv-python keyboard winsdk
# GPU: install CUDA torch (match your CUDA), e.g.
pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126

python fetch_items.py                 # → data/items.json + data/icons/ (~5044)
python gen_synth.py --n 3000 --val 300
python train_yolo.py 40                # detector
python train_cls.py 16                 # classifier
python detect_items.py "test screenshot 1.png"
```

Everything auto-uses CUDA if available, else CPU. GPU-trained weights run on CPU
too (device-portable).

---

## Next steps (prioritized)

**1. Finish detection (in progress — do first; it gates classification).**
- Validate the current retrain (`yolov8s` @960 + richer generator) on both
  screenshots: are panel/merge/miss cases reduced?
- With more powerful hardware, scale up: **`yolov8m`/`l`**, **imgsz 1280**,
  **`gen_synth --n 5000+`**, full epoch count. Add **multi-scale / TTA** at
  inference. (Generator already has: real-bg, UI negatives, anti-merge pairs,
  partials.)

**2. Fix classifier confidence via the real-data flywheel.**
- Run `compare.py --save` over many screenshots → consensus labels.
- `train_cls.py --resume` to fine-tune on real crops; raise `REAL_OVERSAMPLE`
  with more data. Re-measure named-count + correctness on a held-out shot.
- Tune the ensemble: tighten OCR (drop 1-char "T" matches), try **AKAZE**
  (more features than ORB on icons), tune vote weights in `compare.py`.

**3. Bigger real-data source (parked idea).**
- Single Player Tarkov (SPT): stage known inventories → capture screenshots with
  ground-truth → auto labeled data for detector AND classifier. Best long-term
  fix for the synthetic→real gap.

**4. Build the human-in-the-loop reviewer** for the residual <2-agreement crops
   (show crop + top-5 candidates, one-click confirm → label). Mostly confirming,
   since the CNN's top-1 is usually right.

**5. Polish**: resolution-proportional filters already in `detect_items.py`;
   verify on a 1080p/ultrawide shot. Re-wire `ui.py` value report end-to-end.

---

## Key lessons learned (don't re-discover)
- **Detection is not the naming bottleneck — calibration is.** The CNN knows the
  items; it's just unsure on real crops. Real labels > more synthetic epochs.
- **No single classifier is reliable; their agreement is.** Build on consensus.
- **pHash needs near-perfect framing** (1–2px offset ⇒ distance explodes); only a
  tiebreaker. CNN/ORB/OCR are offset-robust.
- **Squash beats letterbox** for elongated items (keeps detail); aspect is fed
  back as a separate prior.
- The old grid + perceptual-hash approach was removed; don't reintroduce cells.
