# TODO (yolo-without-detector)

Living checklist of deferred work. Newest context in LOGBOOK.md.

## Next training run
- [ ] **Collapse exact-duplicate icon groups into ONE class** before training.
      Identical pixels with different labels = contradictory signal. Map every
      icon in an `icon_dups.json` (exact) group to the same class index in
      `build_dataset.py` → ~3446 → ~3250 classes. Merged class = flagged
      ambiguous → OCR resolves which real item.
- [ ] Optional: image-noise augmentation (deferred — JPEG/blur/brightness jitter).

## After full_v2 finishes
- [ ] Archive `full_v2` (weights + model card), like `full_v1`.
- [ ] Eval on real session screenshots — the sim-to-real gap test (overlays +
      square grid). Compare coverage vs `full_v1`.
- [ ] Confidence check: unique icons (expect high) vs near-identical pairs;
      add any YOLO-confused non-exact pairs to the OCR-fallback set.

## Repo restructure
- [ ] Execute the layout in **STRUCTURE.md** (app / tools / shared / experiments).
      Do AFTER training. Don't move `data/yolo` or `runs/` while training.

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
- [ ] Scan pipeline: YOLO boxes + OCR names → fuse. OCR only reads inside boxes
      (kills false matches); per icon-id majority — but links come from non-OCR
      sources (keep YOLO ⊥ OCR independent).
- [ ] Review/correct UI + manual-link button ("OCR & YOLO agree → confirm" →
      writes a `manual` link event).

## Minor / nice-to-have
- [ ] Marked overlay: cut each tile's bottom-left category glyph, stamp
      unstretched (instead of the whole stretched tile). Low priority (noise).
