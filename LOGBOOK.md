# Logbook

Experimental log — newest first. Each entry: what we tried, why, result, next.
See `CLAUDE.md` for the format rule.

---

## 2026-06-26 — Repo cleanup: frontend folder, docs/, dead-code removal (`yolo-without-detector`)

**What.** Tidy pass ahead of the exe-packaging direction. (1) HTML moved to
`app/frontend/` (React lands here later); `server.py` serves from a new `WEB` const.
(2) Deleted dead `app/ocr.py` (classifier-autolabel OCR, superseded by `ocr_identify.py`,
imported by nothing). (3) Moved dev docs into `docs/` (STRUCTURE, MODELS, KAGGLE, TODO);
README/CLAUDE/LOGBOOK stay at root. (4) Rewrote the stale `README.md` (its pipeline table
referenced ~10 files that no longer exist) to match the real YOLO+OCR pipeline and state
the exe/GitHub-Actions/runtime-model-download direction. (5) Folded `idea.txt` scratch
notes into `docs/TODO.md` (price-after-correction check, see-through fluke boxes) and
deleted it. (6) Fixed `CLAUDE.md` `STATUS.md` → `docs/STRUCTURE.md`.

**Why.** Separate "the product" (`app/` = engine+backend+frontend) from dev-only tooling,
and clear out junk before building CI packaging on top.

**Result (works).** Kept `app/` Python flat (per request); only the 3 `send_file` paths
changed. Smoke test: `server.py` imports clean, `WEB` resolves, all 3 frontend files found,
`scan`/`fetch_items` import. No engine/backend logic touched.

**Next.** GitHub Actions exe build; model download-on-first-run from release artifacts;
session-storage policy + report-to-server for missed/wrong items (all in `docs/TODO.md`).

---

## 2026-06-25 — Price-basis toggle: 24h avg vs latest flea low (`yolo-without-detector`)

**What.** Header selector in the valuer to pick which flea price drives ₽/slot:
`avg24hPrice` (24h average) or `lastLowPrice` (latest/most-current low). `value_of`
is now mode-aware (`PRICE_MODE` + `set_price_mode`), each flea field falling back to the
other, vendor/base as a floor. `POST /api/price-mode` sets it and re-projects the current
scan live (no re-scan); state carries `price_mode` so the dropdown reflects the server.

**Why.** 24h avg smooths spikes; latest low is closer to what you'd actually get right
now. Wanted to flip between them when ranking keep/ditch.

**Result (works).** M4A1: avg24h 55,864 vs latest low 23,000 — value_of returns the
selected one; bad mode defaults to avg24h.

---

## 2026-06-25 — Prices auto-cache: 24h TTL refresh in the server (`yolo-without-detector`)

**What.** The server now keeps prices fresh on its own. `tools/fetch_items.py` gained
reusable `fetch_items()` / `write_items()`; `scan.py` gained `catalog_age()` /
`invalidate_catalog()`. `server.py` runs a daemon (`price_refresher`) that checks
hourly and, when `data/items.json` is older than `PRICES_TTL` (24h), re-pulls
tarkov.dev prices, rewrites the cache, drops the in-memory catalog, and re-projects the
current scan so on-screen values update live. Manual force via `POST /api/refresh-prices`.

**Why.** Prices were a frozen snapshot from the last manual `fetch_items.py` run (no TTL,
and the running server never saw updates). Wanted set-and-forget freshness.

**Result (works).** Cache was 31.9h old → first non-forced call refreshed 5043 items
end-to-end; a second call skipped (age 0.002h). Icons are NOT re-downloaded (prices-only
path). `data/` is gitignored so the refreshed json stays local.

**Next.** Optional: surface `prices_age_h` in the UI header.

---

## 2026-06-25 — Inspector view: pan/zoom screenshot + detection overlay + mark-missed (`yolo-without-detector`)

**What.** New third page `/inspect` (`app/inspect.html` + `/api/raw/<ts>`,
`/api/missed`). Shows the latest session's full screenshot in a pan (drag) / zoom
(scroll-to-cursor) stage with every detection drawn as an overlay box (green =
identified w/ short-name + ₽/slot tooltip, red = unidentified). Borders are kept
~constant on screen by scaling `--bw` with zoom. "✂ mark missed" toggles a draw mode:
drag a rectangle over something the detector missed → label it via the same
`/api/search` picker (or "save unlabelled") → crop saved to `gallery/missed/` +
`gallery/missed.jsonl`. Live via the same SSE stream; F2 updates it instantly.

**Why.** Wanted to visually verify detections at full res and harvest misses as
training data (recall gaps: grenades, Snickers). Misses are as valuable as the
correction crops for retraining.

**Result (works).** Routes register; `save_missed()` verified writing crop + labelled
log line against a real session (test sample cleaned). Linked from valuer + compare
headers.

**Next.** Fold `gallery/missed/` + `gallery/corrections/` into `build_dataset.py` as
real positives once enough accumulate.

---

## 2026-06-25 — Manual corrections also captured as real training crops (`yolo-without-detector`)

**What.** When the user clicks a wrong item in the valuer and picks the correct one,
the override now does two things: (1) appends the `manual` link event to
`links.jsonl` (as before), and (2) `save_correction()` crops the on-screen box(es)
for that icon-id out of `sessions/<ts>/raw.png` and writes them to `gallery/crops/`
plus a `gallery/corrections.jsonl` log line `{ts, session, crop, box, icon_id,
item_id, item_name}`.

**Why.** These are precisely the real in-game samples where YOLO's icon-id was wrong
— gold for retraining / fixing the link map. `gallery/` was already reserved (and
gitignored) for "accumulated real-crop gallery (game-sourced training data)".

**Result (works).** Simulated correction against a saved session wrote the crop +
labelled log line (verified, then cleaned the test sample). No re-capture/OCR — runs
inside the existing `/api/override` path. Local only; private (gitignored).

**Next.** Once a handful accumulate, fold them into `build_dataset.py` (real crops as
extra positives for the right class) and/or as link-map ground truth.

---

## 2026-06-25 — OCR identification validated (icon-id -> real item via printed name) (`yolo-without-detector`)

**Works end-to-end (CPU, alongside GPU training).** Windows OCR (winsdk, no
Tesseract) reads the short-name the game prints on each item; fuzzy-match to
`data/items.json` resolves it to a real item + price. game->game => no icon->web
gap. `ocr.py` (restored) + new `ocr_identify.py` (`ocr_words` -> word boxes in
image px; `match_name` -> catalog item).

**Results.** Region OCR of a real stash read Matches/RUB/TP-200/IceGreen/GMcount/
Mustache/PCB/Milk/Crackers/Squash/Caps/Vodka/Wallet/Tushonka/Hawk/Jaeger; 16/16
fuzzy-matched to the correct catalog item (score 1.00 on shortName). Word boxes
land at cell-row tops (y ~73,157,241,325; 84px pitch), so each name maps to its
item box. Misses = stack-count numbers (correctly no match) + a couple
digit-garbled names (TP-200 -> 'Tp-2..'). Per-cell tiny crops fail; OCR needs a
region.

**Caveat / lesson.** OCR works on a REGION, not a 18px single-cell strip.
Plan: OCR whole stash once -> word boxes -> assign each name to the YOLO box
whose top edge it sits on -> majority-vote name per icon-id across detections ->
build a confident OCR-derived icon-id->item map (replaces the shaky visual
matcher). Wire after full_v2 finishes (needs YOLO boxes = GPU).

---

## 2026-06-25 — Full model trained, but SIM-TO-REAL GAP on real screenshots (`yolo-without-detector`)

**Trained.** Full 3446-class yolo11n, 80 epochs @1536, SGD lr0=0.01 (the lr fix
worked). **mAP50 0.917 / best 0.923** on synthetic val. Clean S-curve, no
overfit. Weights: `runs/detect/full/weights/best.pt`.

**Problem — real screenshots detect almost nothing.** On session `raw.png`s the
model finds only ~12 items at conf 0.4, ~26 at conf 0.05, on a stash of ~80.
Detected items are at conf **1.00** (perfect); the rest score ~0 = treated as
background. Synthetic val 0.92 but real ~poor => textbook sim-to-real gap.

**Cause.** Training pastes BARE cache icons. Real in-game items carry overlays
the model never saw: stack-count numbers, durability/resource bars, found-in-raid
corner, selection highlight, price/▶ tags, slight render/lighting diff. Items
without overlays detect perfectly; items with them are missed.

**Fix (next).** Make synthetic look real: in `build_dataset.py` randomly overlay
stack counts, durability bars, FiR/marked tags (assets/overlays/ already exist),
selection highlight, + stronger HSV/brightness jitter. Optionally fine-tune on a
few hand-labeled real screenshots. Retrain. Detection coverage is the blocker
before OCR identification is useful (OCR can only ID what YOLO detects).

---

## 2026-06-24 — Full 3446-class train: parallel gen + speed reality check (`yolo-without-detector`)

**Generator parallelized.** `build_dataset.py` now `--workers` (default all cores)
+ per-worker in-RAM icon cache (decode each icon once, reuse across all its
images, vs re-`Image.open` per paste). Full build: **3455 images in 54s** on 16
cores (was ~30 min single-thread).

**Full train attempted, then paused.** `train.py --name full --epochs 80
--imgsz 1536` (yolo11n, 3446 classes, 3455 imgs). Reality: **~530s/epoch (~9
min)** => 80 epochs ≈ **11h**, not the ~3h estimated. GPU-bound: 100% util,
11.7/12.3 GB at imgsz 1536. Levers = imgsz (quadratic) + epochs; data caching
won't help (compute-bound). First 3 epochs: box_loss 1.72→0.81, cls_loss
7.12→6.79, mAP still 0 (normal — 3446-class head starts slow; demo took ~10+ ep
to register). **Decision: stop, run overnight later at full quality.**

**Resume command (dataset already in `data/yolo`, or regenerate in ~1 min):**
`python build_dataset.py --per-class 35 --max-objs 35 --workers 16 --seed 7`
then `python train.py --name full --epochs 80 --imgsz 1536`.
Note: demo plateaued ~ep45/100 with 200 imgs; with 17x more imgs/epoch here,
convergence likely well before 80 — consider `patience` early-stop to save hours.

---

## 2026-06-24 — Icon# → item linking (names/prices) + manual-fix layer (`yolo-without-detector`)

**Problem.** The detector outputs `#icon` (cache file number), not a real item.
Need icon# → {name, price, size}. Also some icons are shared/near-identical
(keys, dogtags, armband colors, currency) — defer those to OCR.

**Approach (visual match, NOT hash reverse).** Both sources render at 64px/cell.
`fetch_items.py` (reused) pulls 5044 tarkov.dev items (name/size/prices/
gridImageLink) → `data/items.json` + `data/icons/<id>.webp`. `match_icons.py`:
pre-filter candidates by cell footprint, then score masked-L2 ONLY inside the
cache icon's alpha silhouette (so the bg difference — cache transparent vs dev
baked-dark — can't poison it). This is reliable here because we match clean
render↔clean render (unlike the old crop↔icon "gap" that sank `retrieval.py`).

**Result.** All 3446 icons matched (0 no-candidate). score (RMS color, lower
better): med 21, p90 33. margin (gap to 2nd): med 2.4; **2192 have margin<5** =
the shared/near-twin icons (top-1 often still right, sibling close behind) → OCR
later. Random montage + sample (Armband, Dogtag BEAR, MS2000, Surv12, Epsilon,
Eberlestock) visually correct.

**Manual-fix layer (`icon_map.py`).** Effective map = auto + manual, manual wins
and survives re-matching:
- `data/icon_item_map.json` auto (gitignored, regenerated)
- `icon_overrides.json` manual fixes (tracked, override auto)
- CLI: `review [N]` -> `out/icon_review.html` (cache→dev images, worst-ambiguity
  first), `set <#> "<name|id>"`, `find`, `show`, `unset`. Roundtrip verified.

**Next.** Full 3446-class train can run in parallel (class→item collapse happens
at OUTPUT via this map, so no retrain needed if matches change). Then OCR pass
for margin<5 icons.

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

**Follow-up — 100-class demo (`predict.py`).** 100 classes, 200 sparse images,
100 epochs, imgsz 1536 → **mAP50 0.983, mAP50-95 0.968** (plateaued ~0.98 by
epoch ~45; ~7s/epoch on GPU). Per-epoch curve was the clean S-shape: cls_loss
5.43→0.60, mAP50 0→0.98. Annotated synth val img = all items boxed + correct
`#icon` IDs in one pass. 300-class/30-epoch attempt earlier was weak (mAP50
0.06) — too few instances/class AND too few epochs; fix = more epochs +
per-class instances, not fewer classes. NOTE: on a REAL screenshot the 100-class
demo finds ~0 (its 100 random icons aren't the user's items) — only the full
3446-class model makes real screenshots work.

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

---

## 2026-06-25 — full_v2 fine-tune done: overlays closed the sim-to-real gap

`full_v2` = fine-tune of `full_v1/best.pt` on the regenerated synthetic set, this
time **with in-game overlays** (random top-right name text, stack count, FiR tile,
"marked" selection tile — all per-instance random and decorrelated from icon-id so
the model can't cheat by reading text; that stays OCR's job, kept independent).
3680 imgs, imgsz 1536, SGD lr0 0.01 (pinned), 32 epochs (cap), ~4.7 h.

- **Synthetic val:** best ep30 mAP50 0.924 / mAP50-95 0.924 (≈ v1's 0.923).
- **Real screenshots (the point):** stash-heavy views now **54 / 56 detections**
  vs full_v1's ~12-26. Detected-item confidence median **0.972** (mean 0.875).
  Gear/character screens detect few items — expected, they have few grid icons.
  => overlay augmentation substantially closed the gap diagnosed last entry.
- **Confidence check (unique vs ambiguous):** no exact-dup icons appeared in the
  test stashes (they're niche keys/dogtags). Unique icons read very confidently
  (median 0.972). A bare-icon synthetic probe was invalid (off-grid + no overlay =
  out-of-distribution, both groups ~0.06) so it proves nothing — but by
  construction exact-dups are unresolvable (identical pixels under N labels →
  softmax splits). Hence the NEXT-TRAIN plan: collapse each exact-dup group to one
  class (~3446→~3250), flag merged classes ambiguous, resolve via OCR/manual.

Archived to `archive/full_v2_2026-06-25/` (MODEL_CARD + metadata committed; .pt
gitignored). Next: collapse-dups retrain, then linking system + repo restructure.

---

## 2026-06-25 — barry v3: rotation+bg fix; lineage rename; mona on Kaggle

**Diagnosed the dominant miss cause = ROTATION.** Controlled in-distribution test
(24 non-square icons, overlays on): barry v2 detected canonical 24/24 but ROTATED
**0/24** — rotated stash items were invisible (cache stores one orientation; we
pasted only that). Added to build_dataset.py: 90deg rotation (P=0.5, footprint
swapped) + colored cell background (P=0.30, real EFT tints). Both cumulative.

**barry v3** = fine-tune of barry v2 (7 ep, imgsz 1536, ~1h). Cache had grown
3446->3672 (more icons cached in-game) so the head re-initialised; backbone
transferred. Result: mAP50 0.885; **rotated 0/24 -> 24/24**; real stash detections
182907 54->82, 183051 56->82, 183733 13->17. The fix works.

**Naming/lineage (MODELS.md):** one model "barry" with progressions v1/v2/v3
(was full_v1/v2/v3 — archives renamed to barry-v{1,2,3}). A new *name* (mona) is
only for a different class vocabulary. Active model = barry v3.

**mona v1 (deduped) offloaded to Kaggle.** New model = barry+dedupe: --collapse-dups
merges 236 byte-identical icons (40 groups) -> nc 3476; merged classes flagged
ambiguous in classes.json. Trains on Kaggle (free GPU) via a single bundle.zip of
inputs; ultralytics installs offline from bundled wheels (kernel internet/GPU need
phone verification — now done). See KAGGLE.md, MODELS.md.

**Repo tidy:** new top-level `training/` for AI scratch (base weights, kaggle build;
dataset+runs to follow once the VS Code file lock on fresh images clears).
