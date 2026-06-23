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

**VRAM note (important):** detector batch×imgsz must fit GPU VRAM. On a 6 GB
card, `yolov8s` @ imgsz 960 batch 16 needs ~8.8 GB → it silently spills to
shared system memory and runs ~10× slower (~20 s/iter). Keep it under VRAM:
- 6 GB: `yolov8s` @ 768 batch 4–6, or `yolov8n` @ 960 batch 8.
- ≥12 GB (the new machine): `yolov8m/l` @ 1280, batch 16+ — set these in
  `train_yolo.py`. Watch the `GPU_mem` column; if it exceeds your card, lower
  batch or imgsz.

---

## Direction v2 — robust plan (updated 2026-06-22)

A round of experiments (see "What the experiments settled" below) converged on a
robust architecture: **text-first identity + grid/detector boxes**, validated
against a fixed ground-truth set instead of eyeballing.

### Robust architecture

- **Localize**
  - Stash (regular grid): calibrate cell *pitch* (reliable, Sobel periodicity)
    and take the *origin* from the OCR name anchors → exact cells. More robust
    than YOLO on the grid. (`stashgrid.py`)
  - Equipment / rig / non-grid: the synthetic-trained YOLO detector for boxes.
- **Identify — text first**
  - Primary: OCR the printed name → fuzzy-match `items.json`. No domain gap, and
    it's the ONLY thing that separates same-icon families (keys). (`ocr.py`
    `ocr_words`, `stash_ocr.py`)
  - Fallback (name unreadable / not printed): pretrained-CNN embedding nearest-
    neighbour vs the icon library, or the trained classifier.
  - Confidence-gated: report `?` rather than guess.
- **Value**: matched item → DB price; sum per slot; guns detected but NOT valued.

### Plan (ordered by ROI)

**Phase 0 — Measurement (do FIRST).** Finish the OCR labeller (stash + equipment;
correct the ~4 misreads), label 3–5 screenshots → `tests/*.truth.json`, plus an
eval script (detection P/R, identity accuracy, value error). Ends the "did it
improve?" guesswork — every later change becomes measurable.

**Phase 1 — Robust stash reader (MVP).** grid + OCR identity + DB footprint →
boxes + names + values for the stash. A working valuer for the common case with
no fragile icon matching. Handle multi-cell grouping + occupancy.

**Phase 2 — Fill the gaps.** Equipment/rig via the YOLO detector for boxes; OCR
names where printed; pretrained-embedding classifier for items OCR can't read.

**Phase 3 — Real-data flywheel.** Use OCR-labelled crops to TRAIN the classifier
(`cls.pt`, never trained yet) and FINE-TUNE the detector on real data; re-measure
on the Phase-0 eval set.

**Phase 4 — Polish.** Value report + `ui.py` wire-up; verify other resolutions;
SPT auto-labelling for scale (optional, biggest lift).

### What the experiments settled (2026-06-22)

- **Visual icon-matching is a dead end for identity** — domain gap (tarkov.dev ≠
  live render) + same-icon families. Failed three ways: per-cell edge-cosine,
  sliding NCC (present/absent score ranges overlap), EFT↔dev cross-match
  (Alyonka→grenade). Don't reinvest without a strong embedding.
- **OCR of the printed name is the reliable identity signal** — 57/58 stash cells
  first real try; uniquely separates keys. Read the WHOLE region at once (tiny
  per-cell crops give OCR no context); grayscale+autocontrast+fuzzy beat a
  white-text mask (mask dropped ~20% of words).
- **Generator negatives work**: non-overlap + empty-slot/UI negatives cut the real
  empty-slot FPs; clean data converges fast (epoch-1 mAP 0.98 vs 0.51). Synthetic
  cell-states (locked/highlight/FiR) not worth pixel-matching — let the detector
  generalise.
- **EFT icon cache** is extractable (3431 real renders, alpha, footprint-coded
  sizes) but UNLABELLED — hash is opaque (0/5044 crack hits). Mapping needs a CNN
  embedding; parked.
- **Grid**: pitch (84 @ 1440p) recovers cleanly; origin is best taken from OCR
  anchors (Sobel-only origin was ~0.8 cell off).
- Detector dev runs = 3 epochs; long runs only for the final model.
- Baseline detector snapshot: `models/detector_baseline_overlap_e16.pt`.

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
