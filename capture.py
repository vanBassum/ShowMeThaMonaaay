"""
Capture a screenshot of the game and save it for segmentation.

Usage:
  python capture.py                 # 3s countdown, grab primary screen -> screenshots/stash.png
  python capture.py --delay 5       # longer countdown to tab into the game
  python capture.py --all           # capture across all monitors
  python capture.py -o screenshots/raid.png
  python capture.py --shot          # grab immediately, no countdown

Notes:
- Works for BORDERLESS / windowed-fullscreen Tarkov (recommended).
- Exclusive-fullscreen can capture black; alt-enter to borderless if so.
"""
import os
import sys
import time
from PIL import ImageGrab

OUT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


def main():
    out = os.path.join(OUT_DIR, "stash.png")
    delay = 0 if "--shot" in sys.argv else 3
    all_screens = "--all" in sys.argv
    if "--delay" in sys.argv:
        delay = int(sys.argv[sys.argv.index("--delay") + 1])
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    for s in range(delay, 0, -1):
        print(f"  capturing in {s}... (tab into Tarkov)", end="\r", flush=True)
        time.sleep(1)
    img = ImageGrab.grab(all_screens=all_screens)
    img.save(out)
    print(f"\nsaved {img.size[0]}x{img.size[1]} -> {out}")


if __name__ == "__main__":
    main()
