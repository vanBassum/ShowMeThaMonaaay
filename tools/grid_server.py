"""
grid_server.py — tiny standalone backend for grid_editor.html.

Just enough to (re)calibrate grids visually — no torch/cv2/old pipeline.
Edit either a TEMPLATE (templates/<name>/) or a capture SESSION
(sessions/<id>/). Grids save next to the image as grids.json.

    python grid_server.py            # http://127.0.0.1:5000/
"""
import os, json
from flask import Flask, request, jsonify, send_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (tools/ -> ..)
app = Flask(__name__)


def _src(sid):
    """Map an editor 'session' id to (image_path, grids_json_path)."""
    if sid and sid.startswith("tpl:"):
        d = os.path.join(ROOT, "shared", "templates", sid[4:])
        return os.path.join(d, "background.png"), os.path.join(d, "grids.json")
    d = os.path.join(ROOT, "sessions", sid or "")
    return os.path.join(d, "raw.png"), os.path.join(d, "grids.json")


def _list():
    out = []
    tdir = os.path.join(ROOT, "shared", "templates")
    if os.path.isdir(tdir):
        for n in sorted(os.listdir(tdir)):
            if os.path.exists(os.path.join(tdir, n, "background.png")):
                out.append({"id": f"tpl:{n}", "reviewed": False})
    sdir = os.path.join(ROOT, "sessions")
    if os.path.isdir(sdir):
        for n in sorted(os.listdir(sdir), reverse=True):
            if os.path.exists(os.path.join(sdir, n, "raw.png")):
                out.append({"id": n, "reviewed":
                            os.path.exists(os.path.join(sdir, n, "grids.json"))})
    return out


@app.route("/")
def index():
    return send_file(os.path.join(ROOT, "grid_editor.html"))


@app.route("/api/sessions")
def sessions():
    return jsonify(_list())


@app.route("/api/image")
def image():
    img, _ = _src(request.args.get("session", ""))
    return send_file(img) if os.path.exists(img) else ("not found", 404)


@app.route("/api/grids", methods=["GET", "POST"])
def grids():
    if request.method == "POST":
        d = request.get_json(force=True)
        _, gp = _src(d.get("session", ""))
        json.dump(d.get("grids", []), open(gp, "w"), indent=1)
        return jsonify({"ok": True, "count": len(d.get("grids", []))})
    _, gp = _src(request.args.get("session", ""))
    return jsonify(json.load(open(gp)) if os.path.exists(gp) else [])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
