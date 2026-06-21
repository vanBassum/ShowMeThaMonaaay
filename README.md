# ShowMeThaMonaaay

Tarkov (PvE) inventory valuer — screenshot your inventory/loot, identify items, and
rank them by **₽-per-slot** so you can decide what to keep and what to ditch.

Calibrated for **2560×1440**.

## Setup

```bash
pip install -r requirements.txt
python fetch_items.py      # download item metadata + grid icons from tarkov.dev (PvE flea prices)
python build_hashes.py     # build the perceptual-hash + colour-signature DB
```

`data/` (icons + hashes) and `out/` (debug overlays) are gitignored — regenerate with the two commands above.

## Pipeline

| Stage | File | What it does |
|-------|------|--------------|
| Fetch | `fetch_items.py` | tarkov.dev GraphQL → `data/items.json` + `data/icons/*.webp` (PvE flea) |
| Hash DB | `build_hashes.py` / `iconlib.py` | pHash/dHash/aHash + 8×8 colour signature per icon |
| Identify | `identify.py` | vectorised match of a crop against the DB, filtered by cell footprint |
| OCR | `ocr.py` | Windows OCR (winsdk) — reads cell name text + container headers |
| Capture | `capture.py` | grab the screen to `screenshots/` |
| Container map | `containers.py` + `detectors.py` | OCR headers → split into panels → per-type static box for slots, header-to-header bounds for grids |
| Grid finder | `gridfinder.py` | find the cell grid (and sub-grid outlines) inside a container box |
| Single-grid valuer | `analyze.py` | stash-style single grid → segment → identify → ₽/slot table |
| UI | `ui.py` | always-on-top window, **F2** to scan and list items by ₽/slot with icons |

## Status / notes

- **Container detection** (slots + grids, 3-panel split) works well on the GEAR/loadout screen.
- **Sub-grid outlining** (e.g. a rig's individual mag pouches) via Canny contours + lattice snapping — separates adjacent identical items.
- Prices are tarkov.dev **PvE flea** averages; weapons (custom builds) are excluded from valuation.
- Grid layout is calibrated for 2560×1440 (`detectors.GEOM`).

🤖 Built iteratively with Claude Code.
