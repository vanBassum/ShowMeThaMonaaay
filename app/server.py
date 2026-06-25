"""
server.py — runtime UI backend. Press F2 anywhere -> screenshot -> scan -> the page
shows two lists by price-per-slot (KEEP = highest, DITCH = lowest).

    python app/server.py            # then open http://127.0.0.1:5001  and press F2

Notes:
- Capture uses PIL ImageGrab (primary screen). Run Tarkov in *borderless/windowed*
  (exclusive fullscreen can grab black).
- Model + OCR are loaded once; a scan takes a few seconds (OCR per detected box).
"""
import os, sys, io, json, time, threading
from flask import Flask, jsonify, send_file, request, abort, Response
from PIL import ImageGrab, Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan as scanmod  # noqa: E402

MODEL_PATH = scanmod.DEFAULT_MODEL
PORT = 5001
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                            # repo root (anchor file paths here)
# icon sources for the compare page (absolute — send_file needs absolute paths)
CACHE = os.environ.get("EFT_ICON_CACHE") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "Battlestate Games",
    "EscapeFromTarkov", "Icon Cache", "live")          # YOLO icon-id -> <id>.png
CATALOG_ICONS = os.path.join(ROOT, "data", "icons")    # OCR item-id -> <id>.webp
SESSIONS = os.path.join(ROOT, "sessions")
GALLERY = os.path.join(ROOT, "gallery")                # real-crop training data (gitignored)

app = Flask(__name__)
_state = {"status": "idle", "result": None, "ts": None, "error": None}
_model = None
_lock = threading.Lock()
_cond = threading.Condition()   # wakes SSE subscribers on every state change
_ver = 0


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
        _model = YOLO(MODEL_PATH)
    return _model


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
    return send_file(os.path.join(HERE, "ui.html"))


@app.route("/api/latest")
def latest():
    return jsonify(_state)


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
    return send_file(os.path.join(HERE, "compare.html"))


@app.route("/inspect")
def inspect():
    return send_file(os.path.join(HERE, "inspect.html"))


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


@app.route("/api/cat-icon/<item_id>")           # what OCR matched (catalog icon)
def cat_icon(item_id):
    p = os.path.join(CATALOG_ICONS, f"{item_id}.webp")
    return send_file(p) if os.path.exists(p) else abort(404)


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


@app.route("/api/missed", methods=["POST"])      # save a drawn rect the detector missed
def missed():
    d = request.get_json(force=True)
    ts, box = d.get("ts") or _state.get("ts"), d.get("box")
    if not box:
        abort(400)
    fn = save_missed(ts, box, d.get("item_id", ""))
    return jsonify(ok=bool(fn), file=fn)


if __name__ == "__main__":
    print("loading model...")
    get_model()
    try:
        import keyboard
        keyboard.add_hotkey("f2", trigger)
        print("F2 = scan.")
    except Exception as e:
        print(f"(F2 hotkey unavailable: {e} — use the Scan button in the UI)")
    print(f"UI: http://127.0.0.1:{PORT}")
    app.run(port=PORT, threaded=True)
