# Repo structure (planned)

Decided 2026-06-25. **Execute after `full_v2` training finishes** (see caveats
at the bottom). This is the target layout for the `yolo-without-detector` branch.

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

shared/       # artifacts both sides use
  models/           best.pt (active) + archive/        # model in use + history
  catalog/          items.json, icons/                 # tarkov.dev data
  links/            icon_dups.json, links.jsonl, overrides   # the "database"
  templates/        background.png, grids.json
  assets/overlays/

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

## Execution caveats (training is running)

- Safe to move anytime: the `.py` source (running process already loaded it).
- **Do NOT move while training:** `data/yolo/` (dataloader reads it each epoch)
  and `runs/` (training writes; monitor reads `results.csv`).
- Moves into packages need import fixups (future `server.py` importing `ocr`,
  etc.) — do in one pass with a smoke test.
- `data/`, `runs/`, `out/`, `sessions/`, `*.pt` are gitignored build/artifact dirs.
