"""
Tarkov stash valuer — F2 capture launcher.

Press F2 (works while the game is focused): grabs the full screen, mints a new
capture SESSION (sessions/<timestamp>/raw.png), and opens the web review tool at
that session. All scanning/identification/correction happens in the one shared
pipeline behind server.py — this app is just the global hotkey + a thin status
window, so F2 and the browser UI can never drift apart again.

The Flask backend is started automatically if it isn't already running.

Run:  python ui.py     (leave it open; press F2 whenever you want to scan)
"""
import os
import socket
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont

import keyboard
from PIL import ImageGrab

import sessionstore as ss

ROOT = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = "127.0.0.1", 5000
URL = f"http://{HOST}:{PORT}"
BG, FG, MUTE, ACC = "#16181d", "#e8e8ea", "#8a8f99", "#39d98a"


def server_up():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, PORT)) == 0


def ensure_server():
    """Start server.py (same interpreter) if nothing is listening yet."""
    if server_up():
        return True
    subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                     cwd=ROOT)
    for _ in range(40):                 # wait up to ~8s for it to come up
        if server_up():
            return True
        time.sleep(0.2)
    return False


class App:
    def __init__(self, root):
        self.root = root
        root.title("Tarkov stash valuer")
        root.configure(bg=BG)
        root.geometry("420x150+40+40")
        root.attributes("-topmost", True)
        f_title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        f_main = tkfont.Font(family="Segoe UI", size=10)

        self.status = tk.Label(root, text="Press  F2  to scan your stash",
                               bg=BG, fg=FG, font=f_title)
        self.status.pack(padx=14, pady=(18, 4), anchor="w")
        self.sub = tk.Label(root, text="captures open in the browser review tool",
                            bg=BG, fg=MUTE, font=f_main)
        self.sub.pack(padx=14, anchor="w")
        btns = tk.Frame(root, bg=BG)
        btns.pack(padx=14, pady=14, anchor="w")
        tk.Button(btns, text="Scan (F2)", command=self.trigger, bg=ACC, fg="#07120c",
                  relief="flat", font=f_main, padx=14, pady=4).pack(side="left")
        tk.Button(btns, text="Open review tool", command=lambda: webbrowser.open(URL),
                  bg="#21242c", fg=FG, relief="flat", font=f_main, padx=12,
                  pady=4).pack(side="left", padx=8)

        self.busy = False
        self.status.config(text="Starting backend…")
        self.root.after(50, self._boot)

    def _boot(self):
        ok = ensure_server()
        self.status.config(text="Press  F2  to scan your stash" if ok
                           else "Backend not reachable — run  python server.py")
        keyboard.add_hotkey("f2", self.trigger)

    def trigger(self):
        if self.busy:
            return
        self.busy = True
        self.status.config(text="Capturing…")
        self.root.withdraw()                  # keep our window out of the shot
        self.root.after(180, self._capture)

    def _capture(self):
        img = ImageGrab.grab()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        try:
            sid = ss.create(img)
            if not server_up():
                ensure_server()
            webbrowser.open(f"{URL}/?session={sid}")
            self.status.config(text=f"Opened session {sid}")
        except Exception as e:
            self.status.config(text=f"Error: {e}")
        finally:
            self.busy = False


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
