"""
sessionstore.py — every screenshot is its own session FOLDER, so a scan can be
traced after the fact. Shared by the F2 capture (ui.py) and the review backend
(server.py) so both speak the same on-disk layout.

  sessions/<id>/
    raw.png         the screenshot exactly as captured
    scan.json       the model's first pass (cached; safe to delete to re-scan)
    corrected.json  the human-reviewed labels (auto-saved by the UI)
    overlay.png     optional rendered boxes (written on first scan)

<id> is a capture timestamp (YYYYMMDD-HHMMSS), with -2, -3… on same-second
collisions, so folders sort chronologically.
"""
import datetime
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SESSIONS = os.path.join(ROOT, "sessions")


def sdir(sid):
    return os.path.join(SESSIONS, sid)


def raw_path(sid):
    return os.path.join(sdir(sid), "raw.png")


def scan_path(sid):
    return os.path.join(sdir(sid), "scan.json")


def corrected_path(sid):
    return os.path.join(sdir(sid), "corrected.json")


def overlay_path(sid):
    return os.path.join(sdir(sid), "overlay.png")


def new_id():
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    sid, n = ts, 1
    while os.path.exists(sdir(sid)):
        n += 1
        sid = f"{ts}-{n}"
    return sid


def create(img):
    """Make a fresh session from a PIL image; returns its id."""
    sid = new_id()
    os.makedirs(sdir(sid), exist_ok=True)
    img.save(raw_path(sid))
    return sid


def exists(sid):
    return bool(sid) and os.path.exists(raw_path(sid))


def list_ids():
    """Session ids newest-first (only folders that actually hold a raw.png)."""
    if not os.path.isdir(SESSIONS):
        return []
    return sorted((d for d in os.listdir(SESSIONS) if exists(d)), reverse=True)
