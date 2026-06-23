# ShowMeThaMonaaay — Status & Plan

Tarkov inventory valuer: screenshot your stash/loot, detect every item, identify
it, rank by ₽-per-slot. Handoff + living plan. Chronological detail lives in
`LOGBOOK.md`; this is the current picture.

**Active branch: `mask-detect-frontend`.**

---

## ⚑ The key realization (2026-06-23)

**The tarkov.dev icons we pulled from the internet do NOT match what the game
renders** (different lighting/version/scale; our manuel crops are JPG on top).
That single gap is behind a string of failures: template matching, pHash, the
under-confident classifier, and pixel-faithful variant rendering. **We have been
treating internet icons as ground truth, and they aren't.**

**Consequence — the reference and training data must come from the GAME, not the
internet.** Internet icons are still fine where exact appearance doesn't matter
(rough priors), but not as the identification reference or the appearance source.

---

## Scope decision

**Focus on RIG + BACKPACK contents only.** That's where haul value lives;
equipped gear isn't swapped for ₽ mid-raid, so we don't need market value for it.
This shrinks the relevant item set to a few hundred (not all ~5044).

---

## Architecture (current)

Two decoupled stages — **detection (where)** then **identification (what)**:

```
screenshot → [classical mask front-end] → masked image → detector → item boxes
                                                        → crop → identify (what) → ₽/slot
```

- **Mask front-end** (`mask_pipeline.py`, NEW, works): OCR finds container headers
  → subdivide into containers (relative rules, no static sizes, resolution-indep)
  → flood-fill background removal → items isolated on black. Removes the detector's
  panel/UI/world false-positives *before* it runs.
- **Detector**: single-class YOLO on the masked image. Retrained on black-bg,
  non-overlapping synthetic data → masked detection improved (39→44 boxes, cleaner).
  Trains at imgsz 640 / batch 8 to fit the 6 GB laptop GPU (capped 4 epochs in dev).
- **Identification (what)**: the hard, still-open half. Internet-icon-based methods
  (template match, pHash, CNN-on-synthetic) all fight the icon gap. **Must be rebuilt
  on game-sourced references.**

---

## Repo map (current)

| File | Role |
|---|---|
| `mask_pipeline.py` | **main front-end**: OCR containers → subdivide → bg-removal → masked image; `--detect` runs YOLO masked vs original |
| `index.html` | manual box/grid **labeler** (zoom/pan/align-snap, loads/exports YOLO + `*.labels.json`); use via VS Code Live Preview |
| `auto_localize.py` | **GT automation**: takes a "what" list (e.g. ChatGPT `*.labels.json`) and slides each known icon to find precise boxes |
| `variants.py` | renders in-game icon **overlays** (FiR ✓, search highlight, search-category badge, count, durability, rotation); calibration blocked by the icon gap |
| `template_match.py` | open-set icon ID — **negative result** (kept as a logged dead-end) |
| `gen_synth.py` | synthetic YOLO dataset; `--black-frac` for masked-style bg; items never overlap |
| `train_yolo.py` | train detector (imgsz 640 / batch 8 / `DEV_MAX_EPOCHS=4`) |
| `detect_items.py` | detect→classify pipeline + `scan_pil()` API |
| `cls*.py`, `ocr.py`, `compare.py`, `autolabel.py` | classifier + ensemble (synthetic-gap-limited; identification rebuild pending) |
| `fetch_items.py`, `capture.py`, `ui.py` | item metadata, screen-grab, hotkey UI |
| `manuel/` | real reference crops (highlight × found-in-raid combos) — JPG-sourced |
| `refs/` | (empty) drop real PNG reference crops here |

Git-ignored (regenerate): `data/`, `runs/`, `*.pt`, `out/`.

---

## Current state

- ✅ **Mask front-end** works; masked detection is cleaner than raw.
- ✅ **Labeler + auto-localize** give us a path to a measurable ground-truth set.
- ✅ **Variant overlays** modeled (FiR/highlight/search/rotation) — but pixel-faithful
  calibration is blocked by the icon gap.
- ⛔ **Identification** is the bottleneck, and it's blocked on **game-sourced data**.
- ⚠️ No real eval set yet → improvements are eyeballed, not measured.

---

## Plan / next steps (prioritized)

1. **Get game-sourced data (PNG, not JPG).** Capture real rig/backpack screenshots.
   - **Highlight transform** (in progress, user's idea): capture the *same* item
     **with and without** highlight → pixel-diff = the exact highlight effect to
     apply to a game-sourced base. Same trick can isolate FiR, search badge, etc.
2. **Build a game-sourced reference set / training data.**
   - Harvest real item crops from screenshots (use `auto_localize` + `index.html`
     to label, then crop → a *real* icon gallery for the rig+backpack item set), OR
   - **SPT (Single-Player Tarkov)**: stage known inventories, auto-capture with
     ground truth → real labeled boxes *and* crops at scale, no manual labeling.
     Promoted from "parked" to the recommended route.
3. **Real-grid generator.** Define grids on real empty rig/backpack shots, composite
   game-sourced item crops (+ calibrated variants) into them → realistic training
   data with exact auto-labels. Train the detector on that.
4. **Stand up the eval set.** Auto-localize + manual fixups in `index.html` → real
   ground-truth boxes → `eval.py` (TODO) scores detector (masked vs original) so
   "did it help?" becomes a number.
5. **Rebuild identification on game-sourced references.** Then template match /
   embedding retrieval (DINOv2) actually has a fair shot (game→game, not game→internet).

---

## Key lessons (don't re-discover)

- **Internet icons ≠ game render.** The dominant gap; see the realization above.
  Source references/appearance from the game.
- **Masking before detection works** — removes panel/UI/world false positives;
  train the detector on the same masked (black-bg) distribution.
- **Template matching**: useless for open-set ID, but good for **localizing a KNOWN
  icon** (slide → peak) — that's what powers `auto_localize`.
- **Real inventory items never overlap** (grid) — synthetic must not overlap either.
- **pHash needs near-perfect framing**; don't rely on it.
- **6 GB VRAM**: yolov8s @960 batch16 spills (~10× slower). Use imgsz 640 / batch 8.

---

## Setup

```bash
pip install ultralytics imagehash opencv-python keyboard winsdk
# GPU: install CUDA torch, e.g.
pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126

python fetch_items.py                          # → data/items.json + data/icons/
python gen_synth.py --n 3000 --val 300 --black-frac 1.0
python train_yolo.py                           # detector (capped 4 epochs in dev)
python mask_pipeline.py --detect               # front-end + masked-vs-original detect
```

Cloud GPU for bigger runs: Kaggle CLI is configured (see memory). Device-portable
weights (GPU-trained `best.pt` runs on CPU for inference).
