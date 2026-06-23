# Logbook

Experimental log — newest first. Each entry: what we tried, why, result, next.
See `CLAUDE.md` for the format rule.

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
