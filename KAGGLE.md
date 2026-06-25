# Training on Kaggle (free tier)

Offload long runs (e.g. the `mona1` deduped root) to Kaggle's free GPU so the local
machine stays free. Free tier: P100/T4 16GB, ~30 GPU-h/week, 12h max session — our
runs (~25 ep fine-tune, a few hours) fit one session.

We upload only the small **inputs** and generate the synthetic set on Kaggle (the
dataset is multi-GB; the inputs are ~200MB).

## One-time

- Kaggle CLI is installed; auth is configured (user `vanbassum`, ACCESS_TOKEN in
  `~/.kaggle`). Verify: `kaggle datasets list --mine`.

## 1. Stage + upload the inputs dataset

```
python tools/pack_for_kaggle.py            # -> kaggle_pkg/ (icon cache, shared/, tools/, warm-start .pt)
cd kaggle_pkg
kaggle datasets create -p . --dir-mode zip # first time  (private)
# later refreshes (cache grew, new dup groups, code change):
kaggle datasets version -p . -m "refresh" --dir-mode zip
```

Dataset id: `vanbassum/showmethamonaaay-inputs` (set in dataset-metadata.json).

## 2. Push + run the training kernel

```
cd tools/kaggle
kaggle kernels push -p .                    # creates/updates vanbassum/mona1-train
```

`kernel-metadata.json` already requests GPU + internet and attaches the inputs
dataset. The kernel (`kaggle_train.py`) installs ultralytics, runs
`build_dataset.py --collapse-dups` (overlays + rotation + bg + dedupe), then trains
`mona1` (warm start from the full_v2 backbone, ~25 ep @1536, patience 6).

Watch / fetch:
```
kaggle kernels status vanbassum/mona1-train
kaggle kernels output vanbassum/mona1-train -p ./mona1_out   # mona1_best.pt, _classes.json, _results.csv
```

## 3. Bring mona1 home

Drop the downloaded `mona1_best.pt` into the archive and register it:
```
mkdir -p shared/models/archive/mona1
cp mona1_out/mona1_best.pt   shared/models/archive/mona1/best.pt
cp mona1_out/mona1_classes.json shared/models/archive/mona1/classes.json
cp mona1_out/mona1_results.csv  shared/models/archive/mona1/results.csv
# write a MODEL_CARD.txt, update MODELS.md, optionally set active:
cp shared/models/archive/mona1/best.pt shared/models/best.pt
```

## Notes

- Generating on Kaggle uses 4 CPU cores (~few min). If RAM is tight, lower
  `--per-class` in `kaggle_train.py`.
- T4 is slower than P100 — if a run looks like it won't finish in 12h, drop
  `--epochs` (patience early-stops anyway) or accept a resume next session.
- Keep the dataset **private** — it's your account's icon cache.
