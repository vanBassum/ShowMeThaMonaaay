"""
overlay.py — a transparent, always-on-top, click-through desktop overlay used to draw
keep/ditch boxes straight onto the game screen (F3 shows, Tab hides — see server.py).

The web UI can't paint over the game, so this is a native window. It's a single
fullscreen Tk window whose background is a colour key made fully transparent, so only
the box outlines/labels are visible; a Win32 style tweak (WS_EX_TRANSPARENT) makes the
whole thing click-through so it never eats a click meant for the game.

Tkinter is not thread-safe: the root and every canvas op MUST happen on the one thread
that created it. So this owns a dedicated thread running the Tk mainloop; show()/hide()
just post commands onto a queue that the loop drains via root.after().
"""
import queue
import threading
import time

# Colour key for the transparent background — an unusual near-black that won't collide
# with any box/label colour (whose pixels stay opaque and thus visible).
_KEY = "#010203"


class ScreenOverlay:
    def __init__(self):
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._err = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._err:
            raise self._err

    # --- public API (thread-safe: just enqueues) ---------------------------------
    def show(self, boxes):
        """boxes: iterable of (x0, y0, x1, y1, color, label). Coordinates are primary-
        screen pixels — the same space ImageGrab.grab() and the detector work in."""
        self._q.put(("show", list(boxes)))

    def hide(self, wait=False, timeout=1.0):
        """Withdraw the overlay. wait=True blocks until it's actually off-screen — used
        before a screenshot so the overlay's boxes never land in the capture."""
        if not wait:
            self._q.put(("hide", None))
            return
        done = threading.Event()
        self._q.put(("hide", done))
        done.wait(timeout)
        time.sleep(0.08)      # let the compositor drop the frame before we grab

    # --- overlay thread ----------------------------------------------------------
    def _run(self):
        try:
            import tkinter as tk
            self._tk = tk
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)          # no title bar / borders
            root.attributes("-topmost", True)
            root.config(bg=_KEY)
            self._canvas = tk.Canvas(root, bg=_KEY, highlightthickness=0, bd=0)
            self._canvas.pack(fill="both", expand=True)
            self._root = root
            root.after(50, self._poll)
            self._ready.set()
            root.mainloop()
        except Exception as e:                    # e.g. no display / tkinter missing
            self._err = e
            self._ready.set()

    def _poll(self):
        try:
            while True:
                cmd, arg = self._q.get_nowait()
                if cmd == "show":
                    self._draw(arg)
                elif cmd == "hide":
                    self._root.withdraw()
                    self._root.update_idletasks()
                    if arg is not None:      # a synchronous hide() is waiting on us
                        arg.set()
        except queue.Empty:
            pass
        self._root.after(50, self._poll)

    def _draw(self, boxes):
        sw, sh = self._root.winfo_screenwidth(), self._root.winfo_screenheight()
        self._root.geometry(f"{sw}x{sh}+0+0")
        self._canvas.config(width=sw, height=sh)
        self._canvas.delete("all")
        for x0, y0, x1, y1, color, label in boxes:
            self._canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=3)
            if label:
                # bottom-right of the box, on a dark chip so it reads over any background
                t = self._canvas.create_text(x1 - 6, y1 - 5, anchor="se", text=label,
                                             fill=color, font=("Segoe UI", 10, "bold"))
                bx0, by0, bx1, by1 = self._canvas.bbox(t)
                chip = self._canvas.create_rectangle(bx0 - 3, by0 - 1, bx1 + 3, by1 + 1,
                                                     fill="#000000", outline=color, width=1)
                self._canvas.tag_raise(t, chip)      # keep the text above its chip
        self._root.deiconify()
        self._root.update_idletasks()     # ensure the window is mapped before we grab its HWND
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._make_transparent()

    def _make_transparent(self):
        """Windows: make the key colour transparent AND the whole window click-through.

        We do both ourselves (rather than Tk's -transparentcolor) so ordering is right:
        set the layered + transparent ex-style first, THEN apply the colour key last.
        Changing the ex-style after a colour key is applied would drop the key (opaque
        black), which is exactly the failure this replaces."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
            GA_ROOT, LWA_COLORKEY = 2, 0x00000001
            hwnd = user32.GetAncestor(self._root.winfo_id(), GA_ROOT)  # the real top-level HWND
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                  style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            r, g, b = (int(_KEY[i:i + 2], 16) for i in (1, 3, 5))
            colorref = (b << 16) | (g << 8) | r                        # COLORREF = 0x00BBGGRR
            user32.SetLayeredWindowAttributes(hwnd, colorref, 0, LWA_COLORKEY)
        except Exception:
            pass    # not Windows / no ctypes — overlay still draws, just opaque + not click-through
