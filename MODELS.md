# Models & lineage

How we name and track detector models. Weights are gitignored; archived metadata
lives in `shared/models/archive/<name>/` (model card + args + results + classes).

## Naming convention

- A **model** is a named line that evolves through numbered **progressions**:
  `barry v1 → v2 → v3 …`. The name stays; the version increments each retrain.
- A **new name** (barry → mona) is only for a deliberately different model — e.g. a
  different class vocabulary (the dedupe collapse). Routine changes (more augs, more
  data, newly-cached icons, a head re-init) are just the next **version** of the
  same model, not a new name.
- Augmentations live in `build_dataset.py` and are **cumulative** — every regen
  includes all of them, so a later version is a superset of earlier improvements.
- Versions warm-start from the previous `best.pt`; the backbone transfers even when
  the class count changes (the detection head re-inits).

## Lineage

### barry — the working model (local; archive/run ids are `full_v*`)
The friendly name is **barry**; on-disk ids stay `full_v*` (renaming the live run +
mona's warm-start reference mid-flight would break them).
| version | id | parent | classes | dataset / augs | result |
|---|---|---|---|---|---|
| barry v1 | full_v1 | yolo11n (scratch) | 3446 | bare icons, 80 ep | mAP50 0.923; big sim-to-real gap |
| barry v2 | full_v2 | barry v1 | 3446 | + overlays, 32 ep | mAP50 0.924; real stash 54-56 dets |
| **barry v3** (current) | full_v3 | barry v2 | 3672 (cache grew) | + rotation + bg, 7 ep | in progress (local) |

### mona — the deduped model (new name: different class vocabulary)
| version | id | parent | classes | dataset / augs | where |
|---|---|---|---|---|---|
| **mona v1** | mona1 | barry v2 backbone | ~3476 (deduped) | overlays + rotation + bg + **dup-collapse**; ~25 ep @1536 | Kaggle (pending) |

## Why mona is a separate model (not barry v4)
The exact-duplicate collapse (`build_dataset.py --collapse-dups`, using
`shared/links/icon_dups.json`) merges 236 byte-identical icons (40 groups) into 40
shared classes → ~3672 → ~3476. That's a **different class vocabulary**, so it's a
new name rather than the next barry version. Merged classes are flagged
**ambiguous** in `classes.json` (`class_icons` lists the candidate icon#s) →
OCR/manual resolves which real item. See [[rotation-aug-essential]], STRUCTURE.md,
and KAGGLE.md (how to train it).
