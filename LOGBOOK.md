# Logbook

Experimental log — newest first. Each entry: what we tried, why, result, next.
See `CLAUDE.md` for the format rule.

---

## 2026-06-23 — Retrain detector on black-bg/non-overlap data + VRAM fix (`mask-detect-frontend`)

**What.** Regenerated dataset `--black-frac 1.0` (3000/300) and retrained yolov8s,
4 epochs. Then `mask_pipeline.py --detect` to compare new weights, masked vs original.

**VRAM gotcha (lesson).** First attempt at the legacy `imgsz=960 batch=16` SPILLED on
the 6GB RTX 3060 laptop (~10x slower, ~1hr/epoch) — exactly the STATUS.md warning.
Fixed `train_yolo.py` → `imgsz=640 batch=8` (640 also matches inference TILE=640):
2.6GB used, no spill, 4 epochs in ~22 min.

**Result: retraining helped.** Masked recall **39 → 44 boxes** (old vs new weights) —
the detector now matches the black-bg input distribution. Masked stays clean (tight
boxes, none on empty cells); the original (46 boxes) still shows the panel-sized /
blurry-background false positives masking avoids. Synthetic val mAP50 ~0.995 (same
distribution, so not the real signal — the screenshot comparison is).

**Remaining:** large items (armor/backpack) still split into sub-boxes (NMS/epochs);
a few dark items get flooded away pre-detection (mask gap). **Status: working, clear win.**

---

## 2026-06-23 — Non-overlapping synthetic items + dev epoch cap (`mask-detect-frontend`)

**Why.** Real inventory items never overlap (grid-placed), but `gen_synth.py`
placed free-floating "equipment" items and multiple panels with no overlap check,
teaching the detector a wrong prior. (Grid items within a panel were already
non-overlapping via the occupancy matrix.)

**Change.** Track every placed item box; reject free-floating placements that
overlap an existing item (6 retries then skip), and reject panels that overlap
another panel. Touching is still allowed (strict `<`) so the anti-merge adjacent
pairs survive. Verified: 502 boxes over 40 images, **0 overlapping pairs**.
Also capped `train_yolo.py` at `DEV_MAX_EPOCHS=4` while developing.

**Status: done, not yet retrained.** Next: regenerate dataset + 4-epoch train,
re-run `--detect` to compare against the current weights.

**Update — black-background option added.** `gen_synth.py --black-frac P` renders
fraction P of images on near-black with no world texture, no visible panel grid,
no UI chrome — matching the masked detector input from `mask_pipeline.py`. Verified
visually (`out/_synth_black_*.png`): items isolated on black, non-overlapping,
boxes aligned, anti-merge pairs preserved. **Held off on training (GPU in use).**
When ready, run:
  `python gen_synth.py --n 3000 --val 300 --black-frac 1.0 && python train_yolo.py`
(train is capped at 4 epochs) then `python mask_pipeline.py --detect` to compare.

---

## 2026-06-23 — Pipe masked image into the existing detector (`mask-detect-frontend`)

**What.** Added `--detect` to `mask_pipeline.py`: runs the current YOLO detector
(detection only, no classifier) on the masked image AND the original, writes both
overlays (`4_detect_masked.png` / `4_detect_original.png`), prints box counts.
Masked output is now **black** background for the detector (`3_masked.png`); kept a
**pink** copy (`3_masked_pink.png`) for human viewing. NB: the detector was trained
on full screenshots, so black-bg is a domain shift — testing as-is before retraining.

**Result (test screenshot 1, conf 0.25): masked 39 boxes vs original 44 — masked
is cleaner.** Masking removes the panel-sized / blurry-world false positives the
original produces, and empty cells stop generating boxes (black bg + occupancy
filter). Most of the 5-box difference is dropped junk, not lost items. One real
loss: a dark backpack got flooded away as background (mask gap, not detector).
Large items still split into sub-boxes.

**Verdict: hypothesis holds** — masking makes detection easier even un-retrained.
**Next:** regenerate synthetic detector training data with the same black-bg masking
so train matches inference; fix dark-item flood gaps. **Status: working, promising.**

---

## 2026-06-23 — Relative bounding ruleset for subdivision (`mask-detect-frontend`)

**Problem.** Pure geometric neighbour rules can't size the fixed equipment-doll
slots: e.g. BODY ARMOR's bottom should stop at ON SLING (below it), but DOGTAG
(beside it, nearer in y) wrongly bounded it; SPECIAL SLOTS overran past BACKPACK.

**Fix.** Added `BOUND_RULES` — an explicit, extensible table that bounds a
container's edge at the *nearest neighbour of a named type in that direction,
within the same panel*. Still resolution-independent (references detected header
positions, not pixels). Key property: if no ref exists in that direction, it
falls back to the geometric default, so **one rule covers both screens** — e.g.
`SHEATH.bottom = TACTICAL RIG below` stops the right-panel sheath at the rig, and
the left-doll sheath (no rig below) just falls back. Rules added so far: DOGTAG,
BODY ARMOR, SPECIAL SLOTS, SHEATH.

**Result: works.** All four corrections verified on test screenshot 1. More rules
to add (e.g. left-doll SHEATH bottom). **Status: working, iterating.**

---

## 2026-06-23 — Classical mask front-end for detection (`mask-detect-frontend`)

**Context.** Re-examined the whole approach. Detection (grid-free YOLO) is the
flakiest stage — panel-sized boxes, merges, misses — because it's using ML to
find rectangles on a rigid, game-drawn grid. Decided to test a **classical
front-end** that masks the screenshot down to item pixels *before* the detector,
shrinking the detector's job to "split adjacent items."

Pipeline = OCR-find-containers → subdivide → background removal. Reused proven
building blocks from old branches: `read_lines` (Windows OCR word boxes) from
`money2-rebuild`, `flood_background` region-grow, and the container **ruleset**
from `detectors.py` (commit 349fcbe). New file: `mask_pipeline.py`, emits numbered
intermediates `1_ocr_containers`, `2_subdivision`, `3_bg_mask`, `3_masked`.

**Results (on `test screenshot 1.png`, 2560×1440 GEAR/inspect screen):**
- **Step 1 — OCR container detection: works well.** 22 headers found via fuzzy
  match (`difflib`, cutoff 0.82) against known container NAMES.
- **Step 3 — flood-fill background removal: works well.** Items come out as clean
  silhouettes/blobs; validates that a masked image is a far cleaner detector input.
- **Step 2 — subdivision: was the weak link, now fixed.** First cut (crude x-column
  clustering) gave overlapping/wrong regions. Then ported `detectors.py`'s static
  `GEOM` table (worked, but resolution-locked @2560×1440). Then **dropped GEOM**
  for a **resolution-independent** version: every header gets a neighbour-bounded
  search region (extend to next label / panel gutter), tolerances relative to OCR
  line height; panels from dark vertical gutters.

**Fixes this session:** removed `LOOT` (not a container); detect the `QUICK USE`
bar via OCR and use its y as the working bottom (don't mask the quick-use strip /
HUD); masked output paints removed background **bright pink** for clarity.

**Known limitation / next:** with larger header-to-header regions, the flood seeds
only from the region border, so interior **empty grid cells** stay "kept" (dark
clutter) because gridlines wall the flood out. Fix candidates: (a) add interior
flood seeds on a grid; (b) keep only connected components above a min size. Then:
feed `3_masked.png` into the detector, and regenerate synthetic training data with
the same masking so train matches inference.

**Status: partial — promising.** Front-end works; cleanup + detector wiring pending.

---

## Earlier (pre-logbook) — summarized from STATUS.md & branches

- **Grid + perceptual-hash** (`349fcbe`, `f99dddf`): original approach — detect the
  cell grid, pHash each cell against icon DB. **Abandoned:** pHash too brittle
  (1–2px offset explodes distance), grid was resolution-locked. Deterministic grid
  detection was difficult and never fully worked.
- **OCR + tarkov.dev text match** (`money2-rebuild`): OCR printed item names →
  fuzzy match DB; flood panels → icon-match blobs. **Worked reasonably well** —
  source of the building blocks reused above.
- **Grid-free YOLO + CNN classifier** (`grid-free`, current `master` lineage):
  single-class YOLO detector + MobileNetV3 classifier, fused with OCR/pHash/ORB.
  **Key finding:** detection isn't the naming bottleneck — the CNN is *right but
  under-confident* on real crops (synthetic→real calibration gap). Real labels >
  more synthetic epochs. Proposed but not yet tried: **embedding/retrieval against
  the icon gallery** (DINOv2/CLIP) instead of softmax classification.
