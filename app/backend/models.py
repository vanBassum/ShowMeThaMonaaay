"""Fetch detector models from GitHub releases into the user data dir.

Models are NOT bundled in the exe: they're large, change independently of the
app, and a user may switch between them. Each model is published as a GitHub
release whose asset is a zip containing the weights (best.pt) plus metadata
(classes.json, model card). On first use we download + extract it into
`paths.models_dir()/<name>/` and cache it there.

    from backend import models
    weights = models.ensure_model()        # -> Path to best.pt (downloads if absent)

CLI:
    python -m app.backend.models           # ensure the default model
    python -m app.backend.models barry-v3 --force
"""
import io
import json
import sys
import threading
import zipfile
from pathlib import Path

import requests

try:                       # works as a package import...
    from . import paths
except ImportError:        # ...and when run as a loose script
    import paths

REPO = "vanBassum/ShowMeThaMonaaay"

# Model registry: name -> the GitHub release tag that publishes it.
# The release's zip asset is expected to contain a *.pt weights file.
MODELS = {
    "barry-v3": {"tag": "model-barry-v3"},
}
DEFAULT = "barry-v3"

_API = f"https://api.github.com/repos/{REPO}/releases/tags/"
_dl_lock = threading.Lock()   # never download the same model twice concurrently


def is_present(name: str = DEFAULT) -> bool:
    """True if `name`'s weights are already downloaded (no network)."""
    dest = paths.models_dir() / name
    return dest.exists() and _weights_in(dest) is not None


def read_manifest(name: str = DEFAULT) -> dict | None:
    """The downloaded model package's manifest.json (None if absent/unreadable).
    Holds `icons_fingerprint` (the class-set identity), `classes`, version, etc."""
    dest = paths.models_dir() / name
    for m in dest.rglob("manifest.json"):
        try:
            return json.loads(m.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
    return None


def fingerprint(name: str = DEFAULT) -> str | None:
    """The model's icon/class-set fingerprint. Manual corrections (icon-id based)
    are only valid against the model whose set produced this fingerprint."""
    man = read_manifest(name)
    return man.get("icons_fingerprint") if man else None


def _release(tag: str) -> dict:
    r = requests.get(_API + tag, headers={"Accept": "application/vnd.github+json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _pick_asset(release: dict) -> dict:
    """Prefer a .zip asset (weights + metadata), fall back to a bare .pt."""
    assets = release.get("assets", [])
    for ext in (".zip", ".pt"):
        for a in assets:
            if a["name"].lower().endswith(ext):
                return a
    raise RuntimeError(f"release {release.get('tag_name')!r} has no .zip/.pt asset")


def _download(url: str) -> bytes:
    r = requests.get(url, timeout=300, allow_redirects=True)
    r.raise_for_status()
    return r.content


def _weights_in(folder: Path) -> Path | None:
    """Find the weights file in an extracted model folder (best.pt preferred)."""
    best = folder / "best.pt"
    if best.exists():
        return best
    return next(iter(sorted(folder.rglob("*.pt"))), None)


def ensure_model(name: str = DEFAULT, force: bool = False) -> Path:
    """Return the path to `name`'s weights, downloading from its release if absent."""
    if name not in MODELS:
        raise ValueError(f"unknown model {name!r}; known: {sorted(MODELS)}")
    dest = paths.models_dir() / name
    if not force:
        existing = _weights_in(dest) if dest.exists() else None
        if existing:
            return existing

    with _dl_lock:
        if not force:                       # re-check: another thread may have fetched it
            existing = _weights_in(dest) if dest.exists() else None
            if existing:
                return existing
        return _download_model(name, dest)


def _download_model(name: str, dest: Path) -> Path:
    asset = _pick_asset(_release(MODELS[name]["tag"]))
    size_mb = asset.get("size", 0) / 1e6
    print(f"downloading {asset['name']} ({size_mb:.1f} MB) -> {dest} ...", flush=True)
    blob = _download(asset["browser_download_url"])

    dest.mkdir(parents=True, exist_ok=True)
    if asset["name"].lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            z.extractall(dest)
    else:
        (dest / "best.pt").write_bytes(blob)

    weights = _weights_in(dest)
    if not weights:
        raise RuntimeError(f"no .pt weights found after extracting {asset['name']}")
    print(f"model ready: {weights}", flush=True)
    return weights


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    model = args[0] if args else DEFAULT
    print(ensure_model(model, force=force))
