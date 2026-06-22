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

### Icon matching

A second, image-based identifier for items whose text is unreadable. Each item's
grid icon is normalized to 64px cells, the name strip and count zone are masked
(the game overlays them; DB icons don't), and pHash/dHash/aHash + an 8×8 colour
signature are stored. A query crop is scored against all candidates, filtered by
cell footprint. Self-test matches DB icons against the DB at ~100% (residual
misses are items that genuinely share an identical icon).

```bash
python build_hashes.py          # one-time: fetch icons + build hash DB
python identify.py --selftest 25
python identify.py crop.png --w 2 --h 2
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

Working v1 identifies and prices labeled items (text) and has a validated
icon-matching engine. Known gaps:

- **Localization** — icon matching needs item crops. Tie it into `scan.py` by
  cropping item regions (from container layout) and identifying unlabeled ones.
- **Deduplication** — items shown twice (e.g. in the quick-use bar) are counted
  twice.
- **Container layout** — for per-cell accounting, look up the equipped
  container's `grids[]` from the API (already fetched) and anchor to its label.
