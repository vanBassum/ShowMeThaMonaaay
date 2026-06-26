# TODO (yolo-without-detector)

Living checklist of deferred work. Newest context in LOGBOOK.md.

## Training-data augmentations (build_dataset.py) — cumulative, all kept in git
- [x] Overlays: name text / stack count / FiR / marked (full_v2).
- [x] **90° rotation** (P=0.5, swap footprint) — rotated items were invisible
      (0/24 in test). Commit 81ff491. In full_v3.
- [x] **Colored cell background** (P=0.30, real EFT tints) — ammo/assigned-bg
      items. Commit 85f400d. In full_v3.
- [ ] **Image-noise augmentation** (deferred — JPEG/blur/brightness/compression
      jitter). NEXT aug to add; stacks on top of the above on the next regen.

## full_v3 (rotation + bg) — fine-tune from full_v2, ~1h  ⏳ in progress 2026-06-25
- [~] Regenerate dataset (rotation+bg, ~3640 imgs) → fine-tune from full_v2
      (same 3446 classes) 8 ep / patience 3 / imgsz 1536. Then archive + re-eval
      rotated items on real screenshots (expect the 0/24 to jump).

## Dedupe: collapse exact-duplicate icons (separate, LATER run)
- [ ] **Collapse exact-duplicate icon groups into ONE class.** Identical pixels
      with different labels = contradictory signal. Map every icon in a
      `shared/links/icon_dups.json` (exact) group to the same class index in
      `build_dataset.py` → ~3446 → ~3250 classes. Merged class = flagged ambiguous
      → OCR resolves which real item.
      NOTE: changes the class count → new model head → can't fine-tune from v2/v3,
      needs a longer near-from-scratch run. That's why it's kept separate.

## Repo restructure  ✅ done 2026-06-25 (commit 8e98199)
- [x] Executed STRUCTURE.md layout (app / tools / shared / experiments). All entry
      points smoke-tested; predict.py defaults to shared/models/best.pt (full_v2).

## Linking system (icon-id -> real item)
- [ ] Write **LINKING.md** (event-sourced design: sources, scoring, projection).
- [ ] Event log `links.jsonl` (append-only) + projection in code (manual override,
      weight×certainty, corroboration option B `1-∏(1-p)`, conflict flagging).
- [ ] **api_match linker**: render a grid of tarkov.dev API icons (known item per
      cell) → run YOLO → icon-id↔item, no OCR. Test if cache-trained YOLO
      recognizes API icons (the gap). Multi-source agreement = higher certainty.
- [ ] Spike: can we reverse the EFT `index.json` hash → template id? (clean
      independent linker if so).

## Runtime app (UI)
- [x] **Scan pipeline** (`app/scan.py`): YOLO boxes + OCR-in-box → catalog match →
      ₽/slot. OCR only reads inside boxes (kills false matches). 54/82 identified
      on a real shot.
- [x] **F2 server + UI** (`app/server.py`, `app/ui.html`): F2 → screenshot → scan →
      two lists by ₽/slot (keep ↓ / ditch ↑). Saves sessions/<ts>/{raw.png,
      scan.json, scan.png} for later tooling.
- [ ] Improve: per-icon-id majority vote across detections; aggregate stacks;
      show unidentified boxes in the UI (let user name them).
- [ ] Review/correct UI + manual-link button ("OCR & YOLO agree → confirm" →
      writes a `manual` link event). Links still come from non-OCR sources
      (keep YOLO ⊥ OCR independent).

## UI bugs / polish (from idea.txt)
- [ ] **Price not re-valued after a manual correction?** Verify `/api/override`
      re-projects and the new ₽/slot shows in the UI (it should call `project()`).
- [ ] Make the unidentified ("fluke") boxes see-through / less of an eyesore.

## Minor / nice-to-have
- [ ] Marked overlay: cut each tile's bottom-left category glyph, stamp
      unstretched (instead of the whole stretched tile). Low priority (noise).
