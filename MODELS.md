# Models & lineage

How we name and track detector models. Weights are gitignored; archived metadata
lives in `shared/models/archive/<name>/` (model card + args + results + classes).

## Naming convention

- **Root** = defines a class vocabulary and is trained to convergence. Named with a
  stable codename + number: `mona1`, `mona2`, … A new root is minted when the class
  set changes meaningfully (dedupe collapse, a big batch of newly-cached icons).
- **Fine-tune** = a shorter adaptation on top of a root (more real data, new icons,
  new augmentation), same or near-same vocabulary: `mona1-ft1`, `mona1-ft2`, …
- Augmentations live in `build_dataset.py` and are **cumulative** — every regen
  includes all of them, so later models are supersets of earlier improvements.
- Weights carry across fine-tunes (warm start from the parent's `best.pt`). A class
  count change reinitialises the detection head but the **backbone still transfers**.

## Lineage

### mona — the real lineage
| model | parent | classes | dataset / augs | where | status |
|---|---|---|---|---|---|
| **mona1** (root) | full_v2 backbone | ~3476 (deduped) | overlays + rotation + bg + **dup-collapse**; ~25 ep @1536 | **Kaggle** | pending |

### full — experimental pre-history (kept in archive, not the mona line)
| model | parent | classes | dataset / augs | where | result |
|---|---|---|---|---|---|
| full_v1 | yolo11n (scratch) | 3446 | bare icons, 80 ep | local | mAP50 0.923; big sim-to-real gap |
| full_v2 | full_v1 | 3446 | + overlays, 32 ep | local | mAP50 0.924; real stash 54-56 dets |
| full_v3 | full_v2 | 3672 (cache grew) | + rotation + bg, 7 ep | local | in progress |

## Why mona1 is a new root
The exact-duplicate collapse (`build_dataset.py --collapse-dups`, using
`shared/links/icon_dups.json`) merges 236 byte-identical icons (40 groups) into 40
shared classes → ~3672 → ~3476. That changes the class vocabulary, so it starts a
new lineage. Merged classes are flagged **ambiguous** in `classes.json`
(`class_icons` lists the candidate icon#s) → OCR/manual resolves which real item.
See [[rotation-aug-essential]], STRUCTURE.md, and KAGGLE.md (how to train it).
