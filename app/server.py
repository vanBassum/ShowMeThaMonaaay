"""
server.py — runtime UI backend. Press F2 anywhere -> screenshot -> scan -> the page
shows two lists by price-per-slot (KEEP = highest, DITCH = lowest).

    python app/server.py            # then open http://127.0.0.1:5001  and press F2

Notes:
- Capture uses PIL ImageGrab (primary screen). Run Tarkov in *borderless/windowed*
  (exclusive fullscreen can grab black).
- Model + OCR are loaded once; a scan takes a few seconds (OCR per detected box).
"""
import os, sys, json, time, threading
from flask import Flask, jsonify, send_file
from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan as scanmod  # noqa: E402

MODEL_PATH = scanmod.DEFAULT_MODEL
PORT = 5001
HERE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
_state = {"status": "idle", "result": None, "ts": None, "error": None}
_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(MODEL_PATH)
    return _model


def do_scan():
    if not _lock.acquire(blocking=False):
        return  # a scan is already running
    try:
        _state.update(status="capturing", error=None)
        img = ImageGrab.grab().convert("RGB")
        ts = time.strftime("%Y%m%d-%H%M%S")
        sess = os.path.join("sessions", ts)
        os.makedirs(sess, exist_ok=True)
        img.save(os.path.join(sess, "raw.png"))
        _state.update(status="scanning")
        res = scanmod.scan(img, get_model())
        res["ts"] = ts
        json.dump(res, open(os.path.join(sess, "scan.json"), "w"))
        # annotated copy for later review/tooling (green=identified, red=unidentified)
        scanmod.annotate(img, res).save(os.path.join(sess, "scan.png"))
        _state.update(status="done", result=res, ts=ts)
    except Exception as e:
        _state.update(status="error", error=str(e))
    finally:
        _lock.release()


def trigger():
    threading.Thread(target=do_scan, daemon=True).start()


@app.route("/")
def index():
    return send_file(os.path.join(HERE, "ui.html"))


@app.route("/api/latest")
def latest():
    return jsonify(_state)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    trigger()
    return jsonify(ok=True)


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
