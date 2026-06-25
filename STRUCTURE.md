# Repo structure

**Executed 2026-06-25** on the `yolo-without-detector` branch. This is the
as-built layout (one deviation from the original plan, noted below).

> **Run scripts from the repo root** (e.g. `python tools/predict.py ...`).
> Sources moved into folders but resolve `data/`, `out/`, `runs/`, `sessions/`
> relative to CWD; `__file__`-anchored paths were re-anchored to the repo root.

## Layout

```
app/          # runtime: used while gaming + manual adjustments
  ocr.py            ocr_identify.py        # live identification (OCR POV)
  (future) server.py, ui.html             # scan + review/correct UI, manual-link button
  (future) scan.py                        # YOLO+OCR fusion, link projection (reader)

tools/        # one-time / offline
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
```

Old dead-pipeline files (`cls.py`, `cls_model.py`, `train_cls.py`, `retrieval.py`,
`detect_items.py`, `mask_pipeline.py`, `gen_synth.py`, `gen_screenshot.py`,
`make_dataset.py`, `extract_overlays.py`, `autolabel.py`) stay deleted — in git
history if ever needed.

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
