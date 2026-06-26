# SMTM — Packaging & model distribution

How SMTM ships and how a trained model reaches the user. The **exe** (built by GitHub
Actions) bundles the engine + backend + frontend. The **model and the data bound to it**
do *not* live in the exe — they're a versioned **release artifact** downloaded on first
run. This keeps the binary small and lets us push new models without rebuilding the app.

Status: **spec / not yet implemented.** See "Build order" at the bottom for the work this implies.

## Three data planes

Everything in the project is one of three kinds, and that decides where it goes:

| Plane | What | Where |
|---|---|---|
| **Model-bound** — must match the model's vocabulary; the user cannot regenerate it | `best.pt` + the **link map** (icon-id → item) + the **icon-hash manifest** | **GitHub release artifact**, versioned *together* |
| **Live catalog** — changes with the game | `items.json` (prices/size/names), item icons | **Fetched from tarkov.dev at runtime** — never shipped |
| **Dev-only** | EFT training-icon cache, synthetic dataset, `runs/`, `gallery/`, `tools/`, overlays | **Never shipped** |

### Why the training icons are NOT shipped
The model's class names *are* the icon-ids (embedded in `best.pt`, read at runtime as
`r.names[cls]`). Identity (icon-id → item) comes from the **link map**. Display uses the
tarkov.dev **catalog icon** per item (`gridImageLink` in `items.json`, fetched on demand).
So the EFT icon-cache PNGs the model trained on are needed only at *training* time and in
the dev "what YOLO saw" debug view — which reads the *user's own local game cache*, free to
ship around. We ship a **hash** of those icons (see below) for provenance, not the images.

## The model archive (combined)

One release asset per model version, e.g. `smtm-model-barry-v3.zip` (≈ 9 MB):

```
model/best.pt              # the detector (~7.6 MB) — class names = icon-ids
links/icon_item_map.json   # icon-id -> {item_id, score, margin}  (visual matcher, ~1 MB)
links/icon_overrides.json  # CURATED manual overrides  (icon-id -> item_id)
links/links.jsonl          # CURATED baseline link events (ours, not the user's)
icons/icon_hashes.json     # per-icon provenance hashes of the TRAINED icon set (<1 MB)
MODEL_CARD.md              # human-readable card: how it was trained, what changed vs predecessor
manifest.json              # machine-readable header that ties it all together (below)
```

The catalog (56 MB of icons, 2.9 MB `items.json`) stays **out** — it's live data.

### Shipped baseline links vs. local user corrections

The link sources in the archive are the **curated baseline** we author (visual matcher +
our own manual fixes). A **user's runtime corrections never ship** — they accumulate in a
*separate local* log in app-data (e.g. `%LOCALAPPDATA%/SMTM/links.jsonl`) and the runtime
projection layers them **on top of** the shipped baseline. This keeps the shipped map clean
and the user's edits private. Those local corrections *may later be shared back* to improve
future models (opt-in, server-side) — but that pipeline (transport, trust, moderation) is
**not yet designed** and is out of scope here.

## manifest.json

The self-describing header. Lets the app verify the parts belong together and detect drift.

```jsonc
{
  "model": "barry",
  "version": "v3",
  "parent": "barry-v2",            // predecessor it warm-started from (null for a root model)
  "classes": 3672,                 // class count == entries in the .pt head
  "icon_count": 3672,
  "icons_fingerprint": "<sha256>", // sha256 of the sorted "id:sha256" lines from icon_hashes.json
  "reports_cutoff": "2026-06-26T...", // reports with ts <= this were folded in (see below)
  "files": {                       // integrity — verified after download
    "model/best.pt":            {"sha256": "..."},
    "links/icon_item_map.json": {"sha256": "..."},
    "icons/icon_hashes.json":   {"sha256": "..."},
    "MODEL_CARD.md":            {"sha256": "..."}
  },
  "built_at": "2026-06-26T...",
  "min_app_version": "0.1.0"       // app refuses an archive it's too old to load
}
```

`icons_fingerprint` is a single value summarising "this model was trained on *this* icon
set" — the runtime compares it (and the per-icon hashes) against the player's live cache.
`reports_cutoff` is the **report-inclusion boundary**: every report whose timestamp is
`<= reports_cutoff` was considered for this model. **Freeze it at the *start* of retraining**
— anything reported during/after training has a later timestamp and automatically rolls to
the next model, so there's no "did this sneak in?" ambiguity. Inclusion is reasoned about
*within an `icons_fingerprint` lineage* (icon-id-based fixes only apply to a matching vocab).

## Model cards & the root index

`manifest.json` is machine-readable; the **cards** are the human story of how a model came
to be. Two levels: one card *per model* (shipped in its archive), and one **root index**
that describes the whole model program.

### Per-model card — `MODEL_CARD.md` (shipped in each archive)

The human companion to `manifest.json`. `tools/pack_model.py` bundles it; the existing
`shared/models/archive/<name>/MODEL_CARD.txt` convention is the seed — formalise it to
Markdown and ship it. Sections:

- **Identity** — name, version, parent, `built_at`, `classes`, `icons_fingerprint`.
- **What changed vs. predecessor** — the single most useful line: the delta from the parent
  (augmentations added, vocabulary change, link/bug fixes, why this is a new *version* or a
  new *name*). E.g. *"v3 = v2 + 90° rotation + colored-cell-bg aug; rotated items 0/24 → 24/24."*
- **Training** — dataset (synthetic gen + the **cumulative** augmentation list), warm-start
  parent, epochs / imgsz / patience, hardware, wall-clock, where it ran (local / Kaggle).
- **Results** — mAP50 + real-stash detection counts / eval notes; honest about regressions.
- **Class vocabulary** — count, ambiguous (exact-dup) handling, dedupe collapse if any.
- **Reports included** — `reports_cutoff` timestamp **and** the report/fix batch IDs folded
  in, so the model is auditable down to its training inputs (a bad link traces to a report).

### Root index — the "lots of info" master

One authoritative record *above* individual packages: the whole model line, for both humans
and the app's model picker. This is what `docs/MODELS.md` (lineage) becomes, plus a
machine-readable twin:

- **Every model line + version**, parent lineage (`barry v1 → v2 → v3 …`), each version's
  `icons_fingerprint` + release tag (`model-<name>`), and a pointer to its `MODEL_CARD.md`.
- **Cumulative augmentation history** and why each new *name* (a deliberate vocabulary change).
- **Reports-inclusion timeline** — the `reports_cutoff` per version, i.e. full provenance of
  which reports shaped which model across the whole line.
- **Shared context** — the link-database model and the live-catalog source (tarkov.dev).

Ship it two ways: `docs/MODELS.md` stays the human root card (in-repo), and publish a
machine-readable **`models-index.json`** (its own release tag, e.g. `models-index`) so the
app can discover available models, their lineage, fingerprints, and compatibility without
downloading each archive first.

## Icon-hash provenance (`icon_hashes.json`)

So that if Tarkov changes something on their side we can still link the model's classes back
to real icons. **Generated inside `build_dataset.py`, atomic with the model** — right after
`load_icons()` (and the dup-collapse) selects the exact icon set that becomes the classes, so
the manifest reflects *precisely* what was trained. Reuses the hashing already in
`tools/icon_dups.py` (`sig()`), over **decoded RGBA pixels** (not file bytes, so a harmless
re-compression doesn't read as a change).

Two hashes per icon — they answer different questions:

- **`sha256`** (exact) — "byte-identical?" Detects *any* change; also matches a re-keyed
  icon (same art, new id).
- **`dhash`** (perceptual) — "meaningfully different art, or just a re-save / 1px shift?"
  The Hamming distance is the *retrain-worthy vs cosmetic* threshold.

```jsonc
// icon_hashes.json
{ "<icon_id>": {"sha256": "...", "dhash": "...", "w": 1, "h": 1}, ... }
```

### What it buys us
After a patch/wipe, re-hash the player's current cache and diff against `icon_hashes.json`:

| Situation | Detection | Action |
|---|---|---|
| Art changed, **same id** | same id, `sha256` differs **and** `dhash` distance large | model stale for that class → retrain signal; degrade trust, prefer OCR |
| Re-encoded only (cosmetic) | `sha256` differs, `dhash` distance ≈ 0 | ignore — model still valid |
| Icon **re-keyed** (same art, new id) | `sha256` matches a trained icon under a *different* id | remap the link automatically |
| Icon removed | trained id absent from cache | drop / flag the class |

Bonuses: a hash mismatch on a user's machine is exactly the **report-to-server** signal we
want later (a pre-labeled retraining sample), and `icon_dups.json` becomes *derivable* from
this (group ids by `sha256`), so the manifest subsumes the dup set.

## Runtime: first-run & updates

1. **First run / new version:** the app reads the target model version (pinned in app config
   or "latest"), downloads the matching release asset, extracts to an **app-data dir** (not
   the repo, e.g. `%LOCALAPPDATA%/SMTM/models/<model>-<version>/`), and verifies every file's
   `sha256` against the manifest. A mismatch aborts the load.
2. **Catalog:** fetch `items.json` from tarkov.dev on first launch (the server already
   auto-refreshes every 24 h — first launch just triggers it). No snapshot is shipped.
3. **Item icons:** fetch `gridImageLink` on demand, cache locally.
4. **Compatibility check:** app refuses the archive if `min_app_version` > app version, or if
   the link map's class assumptions don't match `classes`.

## Not shipped (dev-only)

EFT training-icon cache, the synthetic YOLO dataset (`data/yolo`), `runs/`, `gallery/`,
`out/`, `sessions/`, `tools/`, `experiments/`, overlays, templates.

## Build order (what this spec implies)

1. **Promote `icon_item_map.json`** out of gitignored `data/` into a shippable/built
   location — it's currently the visual-matcher output and is not packageable as-is. *(blocker)*
2. **Emit `icon_hashes.json`** from `build_dataset.py` (reuse `icon_dups.sig`), atomic with
   the trained class set.
3. **Assembler script** `tools/pack_model.py` — collect model + link map + hashes, write
   `manifest.json` with sha256s + fingerprint, zip it. *(built; extend per #7–8)*
4. **CI release workflow** — on a model tag, run the assembler and attach the zip to a GitHub
   release.
5. **First-run downloader** in the app — fetch by version, verify, extract, load; plus the
   catalog/icon fetch-on-demand path. *(model registry + download built in `backend/models.py`)*
6. **Drift check** (later) — re-hash live cache vs `icon_hashes.json`; feed report-to-server.
7. **Bundle `MODEL_CARD.md`** in the archive (formalise the `MODEL_CARD.txt` convention to
   Markdown) and add `parent` + `reports_cutoff` to `manifest.json`. `pack_model.py` emits both.
8. **Root index** — make `docs/MODELS.md` the human root card and generate a machine-readable
   `models-index.json` (own release tag) for the app's model picker / lineage discovery.
