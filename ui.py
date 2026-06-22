"""
Tarkov stash valuer UI.

Press F2 (works while the game is focused) -> grabs the screen, segments the
stash, identifies items, and lists them ordered by PvE-flea value PER SLOT,
with icons. Guns are excluded (custom builds can't be valued from one icon).

Run:  python ui.py
"""
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont

import keyboard
from PIL import Image, ImageTk, ImageGrab

import detect_items

BG, CARD, FG, MUTE = "#16181d", "#21242c", "#e8e8ea", "#8a8f99"
KEEP, DROP = "#7ee081", "#e08a86"   # green = keep, red = drop
ICON_PX = 36
COL_W = 360
results_q = queue.Queue()
_icons = []  # keep PhotoImage refs alive


def fmt(n):
    return f"{n:,}".replace(",", " ")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Tarkov stash valuer")
        root.configure(bg=BG)
        root.geometry("780x760+40+40")
        root.attributes("-topmost", True)

        self.f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_main = tkfont.Font(family="Segoe UI", size=10)
        self.f_mono = tkfont.Font(family="Consolas", size=10, weight="bold")
        self.f_small = tkfont.Font(family="Segoe UI", size=8)

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        self.status = tk.Label(head, text="Press  F2  to scan your stash",
                               bg=BG, fg=FG, font=self.f_title)
        self.status.pack(side="left")
        tk.Button(head, text="Scan (F2)", command=self.trigger, bg=CARD, fg=FG,
                  relief="flat", font=self.f_main, padx=10).pack(side="right")
        tk.Button(head, text="Overlay", command=self.open_overlay, bg=CARD, fg=MUTE,
                  relief="flat", font=self.f_main, padx=10).pack(side="right", padx=6)
        self.total = tk.Label(root, text="", bg=BG, fg=KEEP, font=self.f_main)
        self.total.pack(fill="x", padx=12, anchor="w")

        # scrollable list
        wrap = tk.Frame(root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.list = tk.Frame(self.canvas, bg=BG)
        self.list.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.list, anchor="nw", width=750)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))

        keyboard.add_hotkey("f2", self.trigger)
        self.busy = False
        self.root.after(120, self.poll)

    def trigger(self):
        if self.busy:
            return
        self.busy = True
        self.status.config(text="Scanning…")
        self.root.withdraw()                  # hide our window from the screenshot
        self.root.after(180, self._capture)

    def _capture(self):
        img = ImageGrab.grab()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        threading.Thread(target=self._work, args=(img,), daemon=True).start()

    def _work(self, img):
        try:
            # save debug artifacts so the scan can be inspected after the fact:
            #   out/last_scan.png    - the raw screen grab
            #   out/last_overlay.png - detected item boxes + labels
            #   out/last_items.json  - the identified item data
            os.makedirs("out", exist_ok=True)
            img.save("out/last_scan.png")
            items = detect_items.scan_pil(img)
            overlay = detect_items.draw_overlay(img, items)
            import cv2
            cv2.imwrite("out/last_overlay.png", overlay)
            json.dump([{k: v for k, v in x.items() if k != "box"} for x in items],
                      open("out/last_items.json", "w"))
            results_q.put(items)
        except Exception as e:
            results_q.put(e)

    def open_overlay(self):
        try:
            os.startfile(os.path.abspath("out/last_overlay.png"))
        except Exception as e:
            self.status.config(text=f"No overlay yet: {e}")

    def poll(self):
        try:
            res = results_q.get_nowait()
        except queue.Empty:
            self.root.after(120, self.poll)
            return
        self.busy = False
        if isinstance(res, Exception):
            self.status.config(text=f"Error: {res}")
        else:
            self.render(res)
        self.root.after(120, self.poll)

    def build_card(self, parent, x, accent):
        row = tk.Frame(parent, bg=CARD)
        try:
            im = Image.open(x["icon"]).convert("RGBA")
            im.thumbnail((ICON_PX, ICON_PX))
            ph = ImageTk.PhotoImage(im)
            _icons.append(ph)
            tk.Label(row, image=ph, bg=CARD).pack(side="left", padx=6, pady=3)
        except Exception:
            tk.Label(row, text="?", bg=CARD, fg=MUTE, width=4).pack(side="left")

        mid = tk.Frame(row, bg=CARD)
        mid.pack(side="left", fill="x", expand=True)
        cnt = f"  ×{x['count']}" if x["count"] > 1 else ""
        tk.Label(mid, text=x["name"] + cnt, bg=CARD, fg=FG, font=self.f_main,
                 anchor="w").pack(fill="x")
        tk.Label(mid, text=f"{x['w']}x{x['h']}  ·  {fmt(x['stack_total'])} ₽ total",
                 bg=CARD, fg=MUTE, font=self.f_small, anchor="w").pack(fill="x")
        tk.Label(row, text=f"{fmt(x['perslot'])}\n₽/slot", bg=CARD, fg=accent,
                 font=self.f_mono, justify="right").pack(side="right", padx=8)
        return row

    def render(self, items):
        _icons.clear()
        for w in self.list.winfo_children():
            w.destroy()

        # dedupe identical items -> one row with a ×count and summed total
        agg = {}
        for x in items:
            if x["weapon"] or x["perslot"] <= 0 or not x.get("sure", True):
                continue
            a = agg.get(x["id"])
            if a:
                a["count"] += 1
                a["stack_total"] += x["price"]
            else:
                agg[x["id"]] = dict(x, count=1, stack_total=x["price"])
        uniq = sorted(agg.values(), key=lambda x: x["perslot"], reverse=True)
        grand = sum(x["stack_total"] for x in uniq)
        guns = sum(1 for x in items if x["weapon"])
        self.status.config(text=f"{len(uniq)} unique items  ·  {guns} gun(s) skipped")
        self.total.config(text=f"Stash value ≈ {fmt(grand)} ₽  (PvE flea)")

        # left column = most valuable (keep), right = least valuable (drop)
        mid = (len(uniq) + 1) // 2
        left = uniq[:mid]                 # high ₽/slot, best at top
        right = list(reversed(uniq[mid:]))  # low ₽/slot, worst at top

        self.list.grid_columnconfigure(0, weight=1, uniform="col")
        self.list.grid_columnconfigure(1, weight=1, uniform="col")
        tk.Label(self.list, text="KEEP — high ₽/slot", bg=BG, fg=KEEP,
                 font=self.f_title).grid(row=0, column=0, sticky="w", padx=6, pady=(0, 4))
        tk.Label(self.list, text="DROP — low ₽/slot", bg=BG, fg=DROP,
                 font=self.f_title).grid(row=0, column=1, sticky="w", padx=6, pady=(0, 4))
        for i in range(max(len(left), len(right))):
            if i < len(left):
                self.build_card(self.list, left[i], KEEP).grid(
                    row=i + 1, column=0, sticky="ew", padx=4, pady=2)
            if i < len(right):
                self.build_card(self.list, right[i], DROP).grid(
                    row=i + 1, column=1, sticky="ew", padx=4, pady=2)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
