# TODO

Living checklist of deferred work. Newest context in LOGBOOK.md. Big pieces have full
specs in `docs/`; the granular lists below feed them.

## Plans to execute — see the linked specs

- [ ] **Packaging & distribution** — [PACKAGING.md](PACKAGING.md). *Built:* `pack_model.py`
      assembler, `backend/models.py` download-from-release → AppData. *Pending:* promote
      `icon_item_map.json` out of `data/` *(blocker)*, emit `icon_hashes.json` from
      `build_dataset.py`, sha256/compat verification on download, CI release workflow,
      `MODEL_CARD.md` + `parent`/`reports_cutoff`, root `models-index.json`.
- [ ] **Read-only app + report → repackage loop** — [REPORTING.md](REPORTING.md). *Built:*
      analysis/diagnose page + `CorrectionDialog`, per-session `fixes.json` (read-only),
      `reports_dir()` reserved. *Pending:* build the **report bundle** from fixes, transport
      (local export → server), `tools/apply_reports.py` assessor → baseline links → new
      package, `reports_cutoff`.
- [ ] **Clean app ⊥ training split** — [STRUCTURE.md](STRUCTURE.md): `scan.py` already
      reads links from the package ✓; remaining coupling = `server.py` imports
      `tools/fetch_items` (fold into `backend/`) + cosmetic `--model` default. Then rename
      `shared/ → training/`, move captures, update tool paths, smoke-test.
- [ ] **Model lineage / root index** — [MODELS.md](MODELS.md): human root card + a
      machine-readable `models-index.json` for the app's model picker.
- [ ] **Identity resolution alignment** — move `scan._resolve` off visual-matcher
      margin/score certainty onto the curated-link + ambiguous-dup-group model
      (STRUCTURE.md "Linking model"; no separate doc yet).
- [ ] **Branch reconciliation** — design docs originated on `yolo-without-detector`;
      implementation lives on `feat/sessions-analysis-and-appdata-runtime` (this branch,
      now carrying both). Fold back / retire the stale branch.

## Done (this branch — feat)

- [x] **React UI** (`app/smtm-ui`, shadcn): app shell + left rail, scan panel, sessions
      card grid, analysis tab, model-status (top-right). Replaces the old `app/frontend` HTML.
- [x] **Standalone runtime**: model downloaded from a GitHub release into AppData
      (`backend/models.py`); all writable state under `%LOCALAPPDATA%\ShowMeThaMonaaay`
      (`backend/paths.py`): models / links / sessions / gallery / reports / icons.
- [x] **Analysis / diagnose page**: click a box → search catalog → flag what it should be,
      propagate to same-icon-id boxes; saved per session as read-only `fixes.json`.
- [x] **Read-only enforced**: removed the legacy `/api/override` + `add_manual_link` write
      path and the legacy `app/frontend` HTML; `scan.py` reads the link map from the package.
- [x] **barry v3** trained + archived (rotation + colored-bg augs); active model.

## Detector recall — undetected items (investigate)

- [ ] **Investigate items YOLO doesn't detect.** A list of known recall failures exists
      (captured by the user; file TBD — drop it under `experiments/` or `docs/`). Work out
      *why* each is missed (size/footprint, rotation, dark/colored bg, rare icon, overlay
      occlusion?) and whether it's an augmentation gap or a training-data gap → feed back
      into `build_dataset.py` augs / more samples.

## Training-data augmentations (build_dataset.py) — cumulative, kept in git

- [x] Overlays: name text / stack count / FiR / marked.
- [x] **90° rotation** (P=0.5, swap footprint) — rotated items were invisible (0/24). 81ff491.
- [x] **Colored cell background** (P=0.30, real EFT tints). 85f400d.
- [ ] **Image-noise augmentation** (JPEG/blur/brightness/compression jitter). NEXT aug.

## Dedupe: collapse exact-duplicate icons (separate, LATER run)

- [ ] **Collapse exact-duplicate icon groups into ONE class.** Map every icon in a
      `links/icon_dups.json` (exact) group to the same class index in `build_dataset.py`
      → ~3672 → ~3476. Merged class = flagged ambiguous → OCR resolves. New class count =
      new head → near-from-scratch run (the "mona" model line; see MODELS.md, KAGGLE.md).

## Linking / independent linkers (icon-id → real item)

- [ ] **api_match linker**: render a grid of tarkov.dev API icons (known item per cell) →
      run YOLO → icon-id↔item, no OCR. Tests if cache-trained YOLO recognizes API icons.
      Multi-source agreement = higher certainty.
- [ ] Spike: reverse the EFT `index.json` hash → template id? (clean independent linker).
- Note: the event-sourced linking design now lives in STRUCTURE.md / REPORTING.md /
  PACKAGING.md rather than a separate LINKING.md.

## Manual corrections — DEFERRED, needs design (see REPORTING.md)

Decision: the link map is **read-only from the model package** — we use whatever `links/`
the package ships and never overwrite it.
- [ ] **User override store** kept separate from the package, keyed to the model's
      `icons_fingerprint` (manual links are icon-id based; icon-ids only mean something
      within one class set). `paths.links_dir()` is reserved; `scan.user_links_log()` exists.
- [x] Dormant `/api/override` + `add_manual_link` write path removed → true read-only.

## Runtime app — improvements

- [ ] Per-icon-id majority vote across detections; aggregate stacks.
- [ ] Show unidentified boxes more clearly; let the user flag them (feeds reports).

## UI bugs / polish

- [ ] Make the unidentified ("fluke") boxes see-through / less of an eyesore.

## Minor / nice-to-have

- [ ] Marked overlay: cut each tile's bottom-left category glyph, stamp unstretched
      (instead of the whole stretched tile). Low priority (noise).
