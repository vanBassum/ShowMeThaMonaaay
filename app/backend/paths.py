"""Where the app keeps its mutable state.

In a packaged build the exe lives in a read-only install dir (e.g. Program
Files), so downloaded models, the user's correction log, and saved sessions
CANNOT live next to it. They go in a per-user writable directory:

    Windows : %LOCALAPPDATA%\\ShowMeThaMonaaay
    other   : $XDG_DATA_HOME/ShowMeThaMonaaay  (or ~/.local/share/...)

Override the whole base with the SMTM_DATA_DIR env var — handy in dev to point
it at a repo-local scratch folder instead of AppData.

Tracked repo inputs (default link database, overlays, templates) still ship
read-only inside the build; this module is only for things that change at
runtime per user/machine.
"""
import os
from pathlib import Path

APP_NAME = "ShowMeThaMonaaay"


def data_dir() -> Path:
    """Root of all per-user writable state. Created lazily by the helpers below."""
    env = os.environ.get("SMTM_DATA_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    """Downloaded detector models (one subfolder per model name)."""
    return _sub("models")


def links_dir() -> Path:
    """Reserved for the user's future manual-correction store (deferred — links are
    read-only from the model package for now; see docs/TODO.md)."""
    return _sub("links")


def sessions_dir() -> Path:
    """Saved scans (raw screenshot + detections) for replay/review."""
    return _sub("sessions")


def gallery_dir() -> Path:
    """Real-crop training data harvested from corrections and missed boxes."""
    return _sub("gallery")


def reports_dir() -> Path:
    """User-submitted 'this detection was wrong' reports (screenshot + flagged boxes).
    Queued locally for now; an opt-in upload comes later (see docs/REPORTING.md)."""
    return _sub("reports")


if __name__ == "__main__":
    print(f"data dir: {data_dir()}")
