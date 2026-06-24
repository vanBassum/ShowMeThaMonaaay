# Logbook

Experimental log — newest first. Each entry: what we tried, why, result, next.
See `CLAUDE.md` for the format rule.

---

## 2026-06-24 — Single-pass multi-class YOLO from the icon cache (`yolo-without-detector`)

**New approach.** Drop the detector→crop→classify/retrieve pipeline. Train ONE
YOLO that outputs box + item-identity in a single pass. "Identity" = the icon
itself (class = icon file number); icon→item-name mapping is deferred (do it
later via tarkov.dev, no retrain).

**Data source (key find).** The live game caches every rendered item icon at
`%LOCALAPPDATA%\Temp\Battlestate Games\EscapeFromTarkov\Icon Cache\live\` —
**3,446 PNGs** (~53 MB) + `index.json` (keys are int32 hashes, not item IDs).
Icons render at ~63px/cell; footprint = `round((px-1)/63)`. All 3446 map cleanly
(1596×1x1, 711×2x1, …). Real game pixels >> synthetic.

**Pipeline (new files).**
- `build_dataset.py` — paste real icons onto `templates/screen1/background.png`
  at valid grid cells (21 containers, 215 cells, ~86px pitch; rescale icons
  64px→86px). Emits YOLO labels with class=icon. `--max-classes`/`--per-class`/
  `--max-objs` (objs/image) control subset + density.
- `train.py` — ultralytics YOLO11, geometry aug off (icons don't flip/rotate).

**Results.**
- *Didn't work:* 200 classes, **30 images**, 3 then 50 epochs → mAP≈0, max
  confidence ~0.01 (collapsed) even on TRAIN images. Cause = too few images
  (dense packing → only 30 scenes), not the multi-class idea.
- *Worked:* 20 classes, **96 sparse images** (`--max-objs 25`), 80 epochs,
  imgsz 1536 → **mAP50 0.995, mAP50-95 0.99, recall 1.0**. Held-out val image:
  25/25 detected, correct identities, high conf.

**Decision / next.** Approach proven. Image COUNT is the lever, not class count —
need ~5k+ sparse images to cover all 3446 classes. Scale up generation + a long
train for the real model. The dev-uses-3-epochs rule does NOT apply to the
multi-class head (needs many more).

---

## 2026-06-23 — Embedding-retrieval voter + review-UI polish (`mask-detect-frontend`)

**Retrieval voter (`retrieval.py`).** Reuse the trained IconNet as a feature
extractor (512-d pre-head activation); embed each crop and match against the
TRUSTED gallery crops (corrected, or OCR-sure) — game→game, so the icon gap
cancels. Wired into `/api/scan` fusion: vote priority **OCR > retrieval > CNN**,
with a reject/uncertain threshold. Empty gallery → silent (verified). As the user
corrects, the gallery fills and retrieval kicks in.

**Fixes.** OCR matcher no longer lets a 2-char short name ("DE") substring-match
inside a long OCR string (caused a wrong pick not even in the suggestions).
Candidates now always lead with the chosen item so the UI can pre-select it.

**Review UI.** Dropped the confusing "current" header — the AI's pick is the
pre-selected (highlighted) row in the suggestion list, change if wrong. Click
cycles through stacked/overlapping boxes (smallest-first). Selected box gets a
white halo + fill; unselected boxes drawn thin. List view = two sortable tables
(grab=most ₽/slot, skip=least ₽/slot) with clickable headers incl. a **conf**
column to surface low-confidence problem items. Clicking a list row corrects
in place (bigger crop preview in the panel) without leaving list view.

**Status: usable review loop; retrieval ready to learn from corrections.**

**Update — no Save button (auto-save).** Every correction/fluke auto-persists
(debounced) with a passive "saved · gallery N" pill; reload restores the corrected
session (api_scan prefers the corrected json). Banking is now **trusted-only**
(corrected or OCR-sure) so untouched AI guesses no longer pollute the gallery —
verified: 1 correction + 17 OCR-sure banked, not all 44.

---

## 2026-06-23 — Review/correct backend + UI (`mask-detect-frontend`)

**Why.** Settled the flywheel UX: detector proposes (high recall), human relabels
wrong classifications via click→search/select; missed boxes out of scope. Needs a
backend (static HTML can't run detection or save).

**Built.**
- `server.py` (Flask): `/api/scan` masks → YOLO detect → per-crop classify
  (**CNN top-5 + gap-immune OCR** of printed name) → JSON, cached to `sessions/`;
  `/api/image`, `/api/icon`, `/api/search` (item lookup w/ thumbnails), `/api/save`.
  Structural flukes dropped by `keep_box`; low-confidence flagged `uncertain` (NOT
  hard-rejected — icon gap makes CNN confidence unreliable).
- `index.html` rewritten as review UI: boxes colored by status, click→suggestions
  +search relabel, list/screenshot toggle, ₽ total, zoom/pan, Save→POST.
- `mask_pipeline.build_masked(pil)` extracted for reuse.

**Result: works end-to-end.** 44 items on test screenshot (~11.5s first scan, then
cached). OCR already rescues items the CNN whiffs (RedRebel/Surv12 at CNN p≈0.01).
CNN guesses often wrong (icon gap, expected) — that's what the UI corrects. Some
boxes over equipment labels OCR'd UI text → flukes the user marks.

**Next:** wire saved corrections into a real-crop gallery + fine-tune; embedding
retrieval voter; then the live F2 capture→store loop. **Status: usable tool.**

---

## 2026-06-23 — KEY REALIZATION: internet icons ≠ game render (`mask-detect-frontend`)

**Finding.** Pulled tarkov.dev icons do not match what the game draws (lighting,
version, scale; manuel crops are JPG too). Measuring a real highlighted cell gave a
cool blue-gray border [57,80,86] — nowhere near assumptions. This gap is the root
cause behind template matching, pHash, the under-confident classifier, and the
failure to render pixel-faithful variants.

**Decision.** Stop treating internet icons as ground truth. Source the
identification reference AND appearance data from the GAME. Scope narrowed to
**rig + backpack** (where haul value is). STATUS.md rewritten to this plan.

**Next (user's idea):** capture the same item WITH and WITHOUT highlight → pixel-diff
= the exact highlight transform, applied to a game-sourced base. Then build a
game-sourced reference set (harvest real crops, or SPT for scale) + real-grid
generator + a measurable eval set. **Status: pivot logged; awaiting real PNG data.**

---

## 2026-06-23 — Icon-variant overlays calibrated from real crops (`mask-detect-frontend`)

**Why.** Clean icons ≠ what the game draws. Plan: model overlays as a generator
feature so training covers them; calibrate against real reference crops (user
provided 6 in `manuel/`, covering all combos of highlight × found-in-raid).

**Calibrated (`variants.py`):**
- **Found-in-Raid** = small light-gray ✓ in the **bottom-right** corner (my first
  guess — green circle top-right — was wrong).
- **Search/pinned highlight** = cell repainted a **warm tan** + lighter border
  (not a bright yellow glow).
- **Search-category badge** = small icon **bottom-left**, present during category
  search; glyph varies per category (generic placeholders for now).
- Also: stack count (br), durability bar (left), name strip (top), rarity tint,
  and **rotation 90°** (user noted items can be turned in the grid).

**Status: overlays match references.** Next: fold these as random augmentations
into `gen_synth` (paste-time), and — for the identifier side — MASK these corner
regions so they don't corrupt matching. Pairs with the real-grid generator plan.

---

## 2026-06-23 — Template matching: open-set ID fails, known-icon LOCALIZE works (`mask-detect-frontend`)

Tried template matching two ways using the icons we already own.

**(a) Open-set identify — FAILED.** `template_match.py`: per loose crop, masked NCC
vs all ~5044 icons. Top-1 wrong on ~all 26 GT boxes, scores 0.15–0.59. Same
brittleness as pHash — full-box NCC needs framing/scale we don't have.

**(b) Known-icon localize — WORKS, and this is the useful route.** Key idea (user's):
ChatGPT is good at *what* is on screen, bad at *where*. So feed the KNOWN icon and
slide it (multi-scale, alpha-masked `matchTemplate`) in a window around the rough
hint → the correlation PEAK is the precise box. `auto_localize.py`: scores jumped to
0.82–0.97 and boxes snap onto items much better than ChatGPT's hints. This
**auto-generates the GT test set**: ChatGPT names + template-refined boxes.

**Two gaps to manage:**
- *Name resolution* (ChatGPT display name → tarkov.dev item) was the bottleneck;
  matching against name+shortName (ratio+token-overlap) fixed most (~20/26 correct).
  Stragglers: X-17, MP-153 variant, tiny Quickbar items.
- `TM_CCORR_NORMED` score isn't discriminative — can't auto-flag a wrong resolution.

**Workflow:** auto_localize → `*.refined.json` → load in `index.html`, eyeball, fix
the few wrong ones → final GT. Mostly automated. Better long-term ID route is still
embedding retrieval (DINOv2). **Status: working pipeline for GT automation.**

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
