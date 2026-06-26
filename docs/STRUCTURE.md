# Repo structure

**Executed 2026-06-25** on the `yolo-without-detector` branch. This is the
as-built layout (one deviation from the original plan, noted below).

> **Run scripts from the repo root** (e.g. `python tools/predict.py ...`).
> Sources moved into folders but resolve `data/`, `out/`, `runs/`, `sessions/`
> relative to CWD; `__file__`-anchored paths were re-anchored to the repo root.

## Layout

```
app/          # THE PRODUCT (engine + backend + frontend) — used while gaming.
              # This is what will ship in the exe (GitHub Actions, later).
  ocr_identify.py                          # identification: read printed name -> catalog item
  scan.py                                  # engine: screenshot -> YOLO boxes -> OCR-in-box -> ₽/slot
  server.py                                # backend: Flask, F2 hotkey -> scan, SSE, correction API
  frontend/                                # the UI — plain HTML now, React later
    ui.html  compare.html  inspect.html    # keep/ditch lists · icon compare · session inspector

tools/        # one-time / offline (dev-only, NOT shipped)
  build_dataset.py   train.py             # synthetic dataset gen + YOLO training
  fetch_items.py                          # pull tarkov.dev catalog
  grid_server.py     grid_editor.html     # grid calibration
  icon_dups.py                            # compute the ambiguous-icon (exact-dup) set
  predict.py                              # offline inference / debug

shared/       # curated inputs both sides use (tracked)
  models/           best.pt (active) + archive/        # model in use + history
  links/            icon_dups.json, icon_overrides.json (+ future links.jsonl)  # the "database"
  templates/screen1/  background.png, grids.json
  assets/overlays/

data/         # DEVIATION: regenerable catalog cache stays here (gitignored)
  items.json, icons/   # tarkov.dev catalog — regenerate: python tools/fetch_items.py
  yolo/                # generated training dataset (build_dataset.py)

experiments/  # throwaway exploration ("tests")
  match_icons.py + icon_map.py review      # the visual-match attempt (demoted)
  dups_*.html, icon_review.html, out/*     # algorithm comparisons, debug images
  Examples/

docs/         # project docs (this file, MODELS.md, KAGGLE.md, TODO.md)
              # README.md / CLAUDE.md / LOGBOOK.md stay at the repo root
```

Old dead-pipeline files (`cls.py`, `cls_model.py`, `train_cls.py`, `retrieval.py`,
`detect_items.py`, `mask_pipeline.py`, `gen_synth.py`, `gen_screenshot.py`,
`make_dataset.py`, `extract_overlays.py`, `autolabel.py`, and `app/ocr.py` — the
classifier-autolabel OCR, superseded by `app/ocr_identify.py`) stay deleted — in
git history if ever needed.

## Planned: clean app ⊥ training split (not yet executed)

**Why.** The app is now **standalone** — it downloads its model + curated links as a
package from a GitHub release and reads them from AppData
(`%LOCALAPPDATA%\ShowMeThaMonaaay\`). So nothing the app needs at runtime is "shared"
with training anymore — `shared/` is a misnomer. We split cleanly into two domains:
**`app/` = the product**, everything else = **training/dev**. (A training UI, if ever
needed, is just more `tools/`.)

**Target layout:**

```
app/            # PRODUCT — standalone; reads only AppData + the fetched package
training/       # everything training/dev (was "shared/", honestly named)
  models/       # best.pt + archive (model cards, lineage)        [was shared/models]
  links/        # icon_overrides + links.jsonl + icon_dups        [was shared/links] — curated baseline pack_model ships
  templates/    # screen1 (background + grids)                    [was shared/templates]
  overlays/     # name/count/FiR/marked                           [was shared/assets/overlays]
  captures/     # game-captured real crops                        [was gallery/, parked in shared/captures]
  icons/        # EFT icon-cache snapshot (~68 MB) — the synthetic-data input  [decision: track vs external]
tools/          # training scripts (build_dataset, train, fetch_items, pack_model…)
experiments/ · docs/
```

**The real work is code decoupling, not just `mv`.** Today the app still reaches into the
training side, so a bare rename would break it:

- `app/scan.py` still reads `shared/models/best.pt`, `shared/links/*`, `data/items.json`,
  `data/icon_item_map.json` → must read from the **downloaded package + AppData** (via
  `app/backend/paths.py`).
- `app/server.py` still `import`s `tools/fetch_items` for the price refresh → fold that
  fetch **into `app/backend/`** so the app has **no `tools/` import**.

Only after that decoupling is the directory reorg safe; then update `tools/` path refs
(`pack_model.py`, `build_dataset.py`, `icon_dups.py`, `predict.py`) `shared/ → training/`
and smoke-test every entry point (as in the 2026-06-25 restructure).

**Open decisions (confirm before executing):**

- **`tools/` placement** — top-level (recommended, less churn) vs. nested under `training/`.
- **Icon-cache snapshot (68 MB)** — track in `training/icons/` (in-repo, durable) vs. keep
  external (the Kaggle inputs dataset already bundles it via `pack_for_kaggle.py`). Lean: track once.
- **Branch** — do this on `feat/sessions-analysis-and-appdata-runtime` (the standalone code);
  first merge the design docs over from `yolo-without-detector`. The two lines are not yet
  reconciled.

## Database: JSON / JSONL (not SQLite, for now)

Data is small (5k items, ~3.7k icons, a few hundred links) and read-mostly. The
event-sourced **link log is append-only JSONL** — git-diffable, human-readable,
fully traceable, and a manual adjustment is one appended line. The projection
(log -> resolved icon-id->item map) lives in **code**, so storage can be swapped
later without touching the model. Revisit SQLite only if the live UI needs
concurrent/transactional writes or real querying.

## Linking model (recap, see also memory + future LINKING.md)

- icon-id -> item map built from NON-OCR sources to keep YOLO ⊥ OCR independent.
- Sources, append-only events `{icon_id,item_id,source,certainty,evidence,ts}`:
  `manual` (hard override) / `api_match` / `hash` / `visual`. OCR is NOT a stored
  link source — it's the runtime cross-check and the trigger for a `manual` event.
- Resolution = projection in code: `score = weight x certainty/100`; manual wins
  outright; independent agreement corroborates (option B: `1-∏(1-p)`); near-ties
  flagged as conflicts. Same-source repetition is folded first (one verdict per
  source) so a chatty source can't fake corroboration.
- Ambiguous icons = the **exact** (byte-identical) duplicate groups in
  `icon_dups.json` (236 icons / 6%); those need OCR/manual. Everything else: YOLO.

## As-built notes

- Active model: `shared/models/best.pt` = a copy of `full_v2/best.pt`
  (gitignored, like all `*.pt`). `predict.py` defaults to it.
- `icon_dups.json` is now tracked under `shared/links/` (moved out of gitignored
  `data/`) — it's part of the linking "database", not a throwaway artifact.
- Path handling: `data/`, `out/`, `runs/`, `sessions/` resolve relative to CWD,
  so **run scripts from the repo root**. `fetch_items.py`, `grid_server.py`,
  `match_icons.py` re-anchor `__file__` to the repo root for their fixed dirs.
- Still gitignored build/artifact dirs: `data/`, `runs/`, `out/`, `sessions/`, `*.pt`.
