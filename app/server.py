"""
server.py — runtime UI backend. Press F2 anywhere -> screenshot -> scan -> the page
shows two lists by price-per-slot (KEEP = highest, DITCH = lowest).

    python app/server.py            # then open http://127.0.0.1:5001  and press F2

Notes:
- Capture uses PIL ImageGrab (primary screen). Run Tarkov in *borderless/windowed*
  (exclusive fullscreen can grab black).
- Model + OCR are loaded once; a scan takes a few seconds (OCR per detected box).
"""
import os, sys, io, json, time, threading, argparse, shutil
from flask import Flask, jsonify, send_file, request, abort, Response
from PIL import ImageGrab, Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                            # repo root (anchor file paths here)
WEB = os.path.join(HERE, "frontend")                    # html (react later) — served by Flask
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))         # for fetch_items (price refresh)
import scan as scanmod          # noqa: E402
import fetch_items              # noqa: E402
from backend import models, paths  # noqa: E402

MODEL_PATH = scanmod.DEFAULT_MODEL
PORT = 5001
PRICES_TTL = 24 * 3600      # re-fetch tarkov.dev prices when items.json is older than this
# icon sources for the compare page (absolute — send_file needs absolute paths)
CACHE = os.environ.get("EFT_ICON_CACHE") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "Battlestate Games",
    "EscapeFromTarkov", "Icon Cache", "live")          # YOLO icon-id -> <id>.png
CATALOG_ICONS = os.path.join(ROOT, "data", "icons")    # OCR item-id -> <id>.webp (shipped baseline)
CATALOG_ICONS_CACHE = str(paths.catalog_icons_dir())   # per-user lazy cache (AppData)
# Per-user writable state lives outside the repo/install dir — see backend/paths.py
# (Windows: %LOCALAPPDATA%\ShowMeThaMonaaay; override with SMTM_DATA_DIR).
SESSIONS = str(paths.sessions_dir())                   # saved scans (raw + detections)
GALLERY = str(paths.gallery_dir())                     # real-crop training data
REPORTS = str(paths.reports_dir())                     # user "this was wrong" reports

app = Flask(__name__)
_state = {"status": "idle", "result": None, "ts": None, "error": None,
          "prices_age_h": None, "price_mode": scanmod.PRICE_MODE,
          # model fetch state, surfaced top-right in the UI
          "model": {"name": models.DEFAULT, "state": "checking", "error": None}}
_model = None
_active_model = models.DEFAULT   # which model get_model() loads; switchable from the UI
_lock = threading.Lock()
_cond = threading.Condition()   # wakes SSE subscribers on every state change
_ver = 0
_price_lock = threading.Lock()  # one price refresh at a time


def _set(**kw):
    """Update state and push to SSE subscribers immediately (no client polling)."""
    global _ver
    with _cond:
        _state.update(**kw)
        _ver += 1
        _cond.notify_all()


def get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(str(models.ensure_model(_active_model)))  # fetch from release if absent
    return _model


def set_active_model(name):
    """Switch the active detector model: fetch it (UI shows progress) and drop the
    loaded model so the next scan reloads with the new weights."""
    global _active_model, _model
    if name not in models.MODELS:
        return False
    _active_model = name
    _model = None
    threading.Thread(target=ensure_model_bg, args=(name,), daemon=True).start()
    return True


def ensure_model_bg(name=None):
    """Make sure the detector model is downloaded, pushing fetch progress to the UI
    (checking -> downloading -> ready/error). Runs at startup so the first launch
    visibly fetches the model from GitHub before any scan is attempted."""
    name = name or models.DEFAULT
    try:
        if models.is_present(name):
            _set(model={"name": name, "state": "ready", "error": None})
            return
        _set(model={"name": name, "state": "downloading", "error": None})
        models.ensure_model(name)
        _set(model={"name": name, "state": "ready", "error": None})
    except Exception as e:
        _set(model={"name": name, "state": "error", "error": str(e)})


def do_scan():
    if not _lock.acquire(blocking=False):
        return  # a scan is already running -> ignore (no duplicate screenshot)
    try:
        _set(status="capturing", error=None)
        img = ImageGrab.grab().convert("RGB")
        ts = time.strftime("%Y%m%d-%H%M%S")
        sess = os.path.join(SESSIONS, ts)
        os.makedirs(sess, exist_ok=True)
        img.save(os.path.join(sess, "raw.png"))
        _set(status="scanning", ts=ts)
        res = scanmod.scan(img, get_model())
        res["ts"] = ts
        json.dump(res, open(os.path.join(sess, "scan.json"), "w"))
        # annotated copy for later review/tooling (green=identified, red=unidentified)
        scanmod.annotate(img, res).save(os.path.join(sess, "scan.png"))
        _set(status="done", result=res, ts=ts)
    except Exception as e:
        _set(status="error", error=str(e))
    finally:
        _lock.release()


def trigger():
    threading.Thread(target=do_scan, daemon=True).start()


def refresh_prices(force=False):
    """Re-fetch prices from tarkov.dev when the cache (items.json) is older than the
    TTL, rewrite it, drop the in-memory catalog, and re-project the current scan so the
    on-screen values update. Runs at most one at a time; returns True if it refreshed."""
    if not force and scanmod.catalog_age() < PRICES_TTL:
        return False
    if not _price_lock.acquire(blocking=False):
        return False                                   # a refresh is already running
    try:
        items = fetch_items.fetch_items()              # GraphQL query (prices + metadata)
        fetch_items.write_items(items)                 # overwrite data/items.json
        scanmod.invalidate_catalog()
        age_h = round(scanmod.catalog_age() / 3600, 1)
        if _state.get("result"):                       # reflect fresh prices on screen
            res = scanmod.project(scanmod.dets_of(_state["result"]))
            res["ts"] = _state.get("ts")
            _set(result=res, prices_age_h=age_h)
        else:
            _set(prices_age_h=age_h)
        print(f"prices refreshed ({len(items)} items)")
        return True
    except Exception as e:
        print(f"(price refresh failed: {e})")
        return False
    finally:
        _price_lock.release()


def price_refresher():
    """Background daemon: keep prices fresh. Checks hourly and refreshes past the TTL."""
    while True:
        refresh_prices()
        time.sleep(3600)


def save_missed(ts, box, item_id=""):
    """Save a user-drawn rectangle the detector MISSED as a real training sample.
    Crop goes to gallery/missed/ with a gallery/missed.jsonl line; optionally labelled
    with the correct item (else kept unlabelled for later naming). Negatives/misses are
    as valuable as corrections for improving recall."""
    raw = os.path.join(SESSIONS, ts or "", "raw.png")
    if not ts or not os.path.exists(raw):
        return None
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    miss = os.path.join(GALLERY, "missed")
    os.makedirs(miss, exist_ok=True)
    fn = f"{ts}_{x0}_{y0}_{x1}_{y1}.png"
    Image.open(raw).convert("RGB").crop((x0, y0, x1, y1)).save(os.path.join(miss, fn))
    item = scanmod._catalog().get(item_id, {}) if item_id else {}
    with open(os.path.join(GALLERY, "missed.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": ts,
                            "crop": f"missed/{fn}", "box": [x0, y0, x1, y1],
                            "item_id": item_id, "item_name": item.get("name", "")},
                           ensure_ascii=False) + "\n")
    return fn


def save_correction(ts, icon_id, item_id):
    """When the user manually fixes an icon-id, keep the on-screen crop(s) + the correct
    answer as labeled training data: these are exactly the real in-game samples where
    YOLO's id was wrong, so they're gold for retraining / fixing the link map later.
    Crops + a log line go to gallery/ (gitignored, game-sourced)."""
    res, raw = _state.get("result"), os.path.join(SESSIONS, ts or "", "raw.png")
    if not res or not ts or not os.path.exists(raw):
        return
    boxes = [d["box"] for d in res["items"] + res["unidentified"]
             if str(d["icon_id"]) == str(icon_id)]
    if not boxes:
        return
    item = scanmod._catalog().get(item_id, {})
    crops = os.path.join(GALLERY, "crops")
    os.makedirs(crops, exist_ok=True)
    img = Image.open(raw).convert("RGB")
    with open(os.path.join(GALLERY, "corrections.jsonl"), "a", encoding="utf-8") as f:
        for i, box in enumerate(boxes):
            fn = f"{ts}_{icon_id}_{i}.png"
            img.crop(tuple(box)).save(os.path.join(crops, fn))
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": ts,
                                "crop": f"crops/{fn}", "box": box, "icon_id": str(icon_id),
                                "item_id": item_id, "item_name": item.get("name", "")},
                               ensure_ascii=False) + "\n")


@app.route("/")
def index():
    return send_file(os.path.join(WEB, "ui.html"))


@app.route("/api/latest")
def latest():
    return jsonify(_state)


@app.route("/api/models")                        # list models for the top-right dropdown
def models_list():
    def info(n):
        man = models.read_manifest(n) if models.is_present(n) else None
        return {"name": n, "present": models.is_present(n),
                "fingerprint": (man or {}).get("icons_fingerprint"),
                "classes": (man or {}).get("classes")}
    return jsonify(active=_active_model,
                   active_fingerprint=models.fingerprint(_active_model),
                   available=[info(n) for n in models.MODELS])


@app.route("/api/model", methods=["POST"])       # switch the active model
def model_select():
    name = (request.get_json(force=True) or {}).get("name")
    if not name or not set_active_model(name):
        abort(400)
    return jsonify(ok=True, active=name)


@app.route("/api/sessions")                 # saved scans, newest first (replay in the UI)
def sessions_list():
    """Each saved scan as a card-friendly summary (newest first): id + the totals the
    grid shows (₽ total, identified/detections). Reads the stored scan.json — cheap for
    the handful of sessions we keep; falls back to bare id if a file is unreadable."""
    if not os.path.isdir(SESSIONS):
        return jsonify([])
    ids = sorted((d for d in os.listdir(SESSIONS)
                  if os.path.exists(os.path.join(SESSIONS, d, "scan.json"))), reverse=True)
    out = []
    for ts in ids:
        card = {"id": ts, "total": None, "identified": None, "detections": None}
        try:
            s = json.load(open(os.path.join(SESSIONS, ts, "scan.json"), encoding="utf-8"))
            card.update(total=s.get("total"), identified=s.get("identified"),
                        detections=s.get("detections"))
        except Exception:
            pass
        out.append(card)
    return jsonify(out)


def load_session(ts):
    """Replay a saved session into state WITHOUT capturing/scanning — re-projects the
    stored detections so prices/links are current (falls back to the stored result).
    Lets the frontend be developed against real data with no game/model running."""
    p = os.path.join(SESSIONS, ts or "", "scan.json")
    if not ts or not os.path.exists(p):
        return False
    stored = json.load(open(p, encoding="utf-8"))
    try:
        res = scanmod.project(scanmod.dets_of(stored))
    except Exception:
        res = stored
    res["ts"] = ts
    _set(status="done", result=res, ts=ts, error=None)
    return True


@app.route("/api/load-session/<ts>", methods=["POST"])   # replay a saved session into state
def load_session_route(ts):
    return jsonify(ok=load_session(ts))


@app.route("/api/report", methods=["POST"])     # save a "these detections were wrong" report
def save_report():
    """Persist a user report locally (NOT sent anywhere yet — see docs/REPORTING.md):
    a bundle of flagged boxes ('this box should be item X') plus the whole screenshot,
    so we can triage offline later. The app stays read-only — this never edits the link
    map; that's a separate, deliberate action."""
    d = request.get_json(force=True) or {}
    ts, flags = d.get("session_ts"), d.get("flags") or []
    if not ts or not flags:
        abort(400)
    rid = time.strftime("%Y%m%d-%H%M%S")
    rdir = os.path.join(REPORTS, rid)
    os.makedirs(rdir, exist_ok=True)
    raw = os.path.join(SESSIONS, ts, "raw.png")
    has_shot = os.path.exists(raw)
    if has_shot:
        shutil.copy(raw, os.path.join(rdir, "raw.png"))   # whole screenshot, self-contained
    bundle = {"report_id": rid, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "session_ts": ts, "screenshot": "raw.png" if has_shot else None,
              "model": {"name": _active_model,
                        "icons_fingerprint": models.fingerprint(_active_model)},
              "flags": flags}
    json.dump(bundle, open(os.path.join(rdir, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"report saved: {rid} ({len(flags)} flag(s)) -> {rdir}")
    return jsonify(ok=True, report_id=rid)


@app.route("/api/stream")           # Server-Sent Events: push state on every change
def stream():
    def gen():
        last = -1
        while True:
            with _cond:
                if _ver == last:
                    _cond.wait(timeout=20)
                cur, data = _ver, json.dumps(_state)
            if cur != last:
                last = cur
                yield f"data: {data}\n\n"
            else:
                yield ": ping\n\n"      # heartbeat keeps the connection open
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/compare")
def compare():
    return send_file(os.path.join(WEB, "compare.html"))


@app.route("/inspect")
def inspect():
    return send_file(os.path.join(WEB, "inspect.html"))


@app.route("/api/raw/<ts>")                      # full screenshot for the inspector
def raw(ts):
    p = os.path.join(SESSIONS, ts, "raw.png")
    return send_file(p) if os.path.exists(p) else abort(404)


def _png(img):
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/yolo-icon/<icon_id>")          # what YOLO saw (cache icon)
def yolo_icon(icon_id):
    p = os.path.join(CACHE, f"{icon_id}.png")
    return send_file(p) if os.path.exists(p) else abort(404)


def _cat_icon_path(item_id):
    """Resolve a catalog (grid) icon: per-user cache first, then the shipped baseline,
    else lazily download it from tarkov.dev (gridImageLink) into the cache. Returns the
    path to serve, or None if the item has no icon link / the fetch failed."""
    fn = f"{item_id}.webp"
    for p in (os.path.join(CATALOG_ICONS_CACHE, fn), os.path.join(CATALOG_ICONS, fn)):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    item = scanmod._catalog().get(item_id)
    url = item.get("gridImageLink") if item else None
    if not url:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "smtm"})
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
        dst = os.path.join(CATALOG_ICONS_CACHE, fn)
        with open(dst, "wb") as f:
            f.write(blob)
        return dst
    except Exception as e:
        print(f"(cat-icon fetch failed {item_id}: {e})")
        return None


@app.route("/api/cat-icon/<item_id>")           # catalog icon (OCR match / picker / compare)
def cat_icon(item_id):
    p = _cat_icon_path(item_id)
    return send_file(p) if p else abort(404)


@app.route("/api/crop/<ts>")                     # on-screen crop, box=x0,y0,x1,y1
def crop(ts):
    raw = os.path.join(SESSIONS, ts, "raw.png")
    if not os.path.exists(raw):
        abort(404)
    try:
        box = tuple(int(v) for v in request.args["box"].split(","))
    except Exception:
        abort(400)
    return _png(Image.open(raw).convert("RGB").crop(box))


@app.route("/api/scan", methods=["POST"])
def api_scan():
    trigger()
    return jsonify(ok=True)


@app.route("/api/search")                        # catalog search for manual correction
def search():
    return jsonify(scanmod.search_items(request.args.get("q", "")))


@app.route("/api/override", methods=["POST"])    # correct an icon-id -> item (manual event)
def override():
    d = request.get_json(force=True)
    icon_id, item_id = d.get("icon_id"), d.get("item_id")
    if not icon_id or not item_id:
        abort(400)
    scanmod.add_manual_link(icon_id, item_id, note=d.get("note", ""))
    save_correction(_state.get("ts"), icon_id, item_id)   # keep crop + right answer for training
    # re-project the current scan with the new link (no re-capture / re-OCR)
    if _state.get("result"):
        res = scanmod.project(scanmod.dets_of(_state["result"]))
        res["ts"] = _state["ts"]
        _set(result=res, status="done")
    return jsonify(ok=True)


@app.route("/api/price-mode", methods=["POST"])  # pick flea basis: avg24h vs latest low
def price_mode():
    mode = scanmod.set_price_mode((request.get_json(force=True) or {}).get("mode"))
    if _state.get("result"):                          # re-value the current scan, push live
        res = scanmod.project(scanmod.dets_of(_state["result"]))
        res["ts"] = _state.get("ts")
        _set(result=res, price_mode=mode)
    else:
        _set(price_mode=mode)
    return jsonify(ok=True, price_mode=mode)


@app.route("/api/refresh-prices", methods=["POST"])   # force a price re-fetch now
def refresh_prices_now():
    ok = refresh_prices(force=True)
    return jsonify(ok=ok, prices_age_h=_state.get("prices_age_h"))


@app.route("/api/missed", methods=["POST"])      # save a drawn rect the detector missed
def missed():
    d = request.get_json(force=True)
    ts, box = d.get("ts") or _state.get("ts"), d.get("box")
    if not box:
        abort(400)
    fn = save_missed(ts, box, d.get("item_id", ""))
    return jsonify(ok=bool(fn), file=fn)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="preload a saved session id into state (dev/testing)")
    ap.add_argument("--no-model", action="store_true",
                    help="skip the eager model load at startup (frontend dev). F2 is still "
                         "registered and a scan lazy-loads/fetches the model on demand.")
    args = ap.parse_args()
    # fetch the model in the background so first start visibly shows "fetching"
    threading.Thread(target=ensure_model_bg, daemon=True).start()
    if not args.no_model:
        print("loading model...")
        get_model()
    age = scanmod.catalog_age()
    print(f"prices cached {age/3600:.1f}h ago (auto-refresh > {PRICES_TTL//3600}h)")
    threading.Thread(target=price_refresher, daemon=True).start()  # 24h price cache
    if args.session:
        print(f"loaded session {args.session}" if load_session(args.session)
              else f"(session {args.session} not found)")
    # F2 always captures a screenshot; the model (if missing) is fetched/loaded on scan.
    try:
        import keyboard
        keyboard.add_hotkey("f2", trigger)
        print("F2 = scan.")
    except Exception as e:
        print(f"(F2 hotkey unavailable: {e} — use the Scan button in the UI)")
    print(f"UI: http://127.0.0.1:{PORT}")
    app.run(port=PORT, threaded=True)
