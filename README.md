# ShowMeThaMonaaay

Tarkov (PvE) inventory valuer — screenshot your stash/loot, detect and identify the
items, and rank them by **₽-per-slot** so you can decide what to keep and what to ditch.

Calibrated for **2560×1440**, Windows (uses the built-in Windows OCR).

## How it works

A screenshot goes through a two-part pipeline that keeps detection and identification
independent:

1. **Detect (engine)** — a YOLO model finds every item box and its icon-id.
2. **Identify** — OCR reads the item name printed *inside each box* and matches it to the
   tarkov.dev catalog (price + grid size). A non-OCR `icon-id → item` link map is the
   primary identity; OCR is the cross-check and the trigger for manual corrections.
3. **Value** — `₽/slot = price / (width × height)` from the catalog, ranked KEEP↓ / DITCH↑.

See [docs/STRUCTURE.md](docs/STRUCTURE.md) for the full architecture and the linking model.

## Layout

| Path | What |
|------|------|
| `app/` | **the product** — engine ([scan.py](app/scan.py), [ocr_identify.py](app/ocr_identify.py)), backend ([server.py](app/server.py)), frontend ([app/frontend/](app/frontend/)) |
| `tools/` | dev-only / offline: dataset gen, training, catalog fetch, grid calibration |
| `shared/` | curated tracked inputs: models, link "database", templates, overlays |
| `experiments/` | throwaway exploration |
| `docs/` | [STRUCTURE](docs/STRUCTURE.md) · [MODELS](docs/MODELS.md) · [KAGGLE](docs/KAGGLE.md) · [TODO](docs/TODO.md) |
| `LOGBOOK.md` | dated experiment log (what worked / what didn't) |

`data/`, `out/`, `runs/`, `sessions/`, `gallery/`, and `*.pt` weights are gitignored
(regenerable or downloaded).

## Run it (dev)

```bash
pip install -r requirements.txt
python tools/fetch_items.py      # tarkov.dev catalog -> data/items.json + data/icons/ (PvE flea)
# place a trained detector at shared/models/best.pt  (see docs/MODELS.md)
python app/server.py             # then open http://127.0.0.1:5001 and press F2 to scan
```

> Run scripts **from the repo root** — paths like `data/`, `sessions/` resolve relative to CWD.
> Run Tarkov in **borderless/windowed** mode (exclusive fullscreen can capture black).

## Direction

The goal is a single distributable: **GitHub Actions builds an exe** bundling the engine +
backend + frontend (React, replacing the HTML in `app/frontend/`). The trained model lives in
GitHub release artifacts and is **downloaded on first run**, so the binary stays small. Users
will be able to report missed / wrongly-identified items back to a server to feed future
training. All of this is incremental — tracked in [docs/TODO.md](docs/TODO.md).

🤖 Built iteratively with Claude Code.
