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
- `tarkov.py` — fetch/cache the tarkov.dev item DB; `Matcher` for name matching.
- `scan.py` — the pipeline: OCR a screenshot, match, value, annotate.

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

Working v1 identifies and prices the labeled items. Known gaps:

- **Deduplication** — items shown twice (e.g. in the quick-use bar) are counted
  twice.
- **Unlabeled items** — items without visible text need icon matching
  (perceptual hash against tarkov.dev grid icons).
- **Container layout** — for per-cell accounting, look up the equipped
  container's `grids[]` from the API (already fetched) and anchor to its label.
