# money2 — EFT inventory reader

Read an Escape from Tarkov gear/inventory screenshot and value its contents.

## Approach

Earlier attempts tried to reconstruct the cell grid from pixels (flood fill,
edge detection, line projection). That fought noise on a fuzzy overlay and
never converged. This rebuild uses the **strongest signals in the image
instead**:

1. **OCR** the item text the game prints on every item (built-in Windows OCR).
2. Match it against the **tarkov.dev** item database (authoritative identity,
   size, container grid layout, price).
3. Report identified items + total value.

No grid reconstruction — item text + an authoritative DB is far more robust.

```
screenshot -> OCR lines -> drop UI text -> match to item DB -> value + annotate
```

## Modules

- `ocr.py` — Windows OCR wrapper; `read_lines(img)` returns text + boxes.
- `tarkov.py` — fetch/cache the tarkov.dev item DB + grid icons; `Matcher` for
  name matching; `best_price`.
- `scan.py` — text pipeline: OCR a screenshot, match, value, annotate.
- `iconlib.py` — icon normalization + perceptual hashing (overlay-masked).
- `build_hashes.py` — download icons + build `data/hashes.json`.
- `identify.py` — match an item-icon crop against the hash DB (+ `--selftest`).
- `read_inventory.py` — full reader: OCR text matching over the gear panels,
  with an opt-in (`--icons`) experimental icon pass.

### Icon matching (built, but does NOT transfer to this screenshot)

A second, image-based identifier. Each item's grid icon is normalized to 64px
cells, the name strip and count zone are masked, and pHash/dHash/aHash + an 8×8
colour signature are stored; a query crop is scored against all candidates,
filtered by cell footprint.

The engine is validated DB-to-DB (self-test ~100%), **but it does not work
against this gear screenshot**: the in-game gear-screen rendering differs too
much from the flat tarkov.dev grid icons (lighting, the fuzzy backdrop bleeding
in, scale), so even a correct crop scores no better than wrong ones (d≈300).
Background-masking the crop didn't close the gap. Kept as `--icons` for
experimentation; the reliable path here is text.

```bash
python build_hashes.py          # one-time: fetch icons + build hash DB
python identify.py --selftest 25
```

## Usage

```bash
pip install -r requirements.txt
python scan.py                       # scans "test screenshot 1.png"
python scan.py -i other.png
python tarkov.py                     # (re)build the item cache, sanity-check matches
```

Outputs `out/scan.png` (annotated) and a priced item list to stdout. The item
DB caches to `data/items.json` on first run (both dirs are gitignored).

## Status / next

`read_inventory.py` reads and prices the labeled items reliably (text). Notes:

- **Icon matching doesn't transfer** to the gear screen (see above) — the
  screenshot rendering is too unlike the flat grid icons. It would likely work
  on the in-stash inventory view, where cells show the true grid icons.
- **Unlabeled items** therefore aren't read yet. Options: train/tune matching
  on actual in-game cell renders, or read the in-stash view instead.
- **Container layout** — for per-cell accounting, look up the equipped
  container's `grids[]` from the API (already fetched) and anchor to its label.
