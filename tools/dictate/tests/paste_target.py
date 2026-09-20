#!/usr/bin/env python3
"""paste_target.py <window-id-file> <result-file> [settle-seconds]

Opens a Tk window with a text field, publishes its X window id, then records
whatever is pasted into it. Writes the result once the text has stopped
changing for <settle-seconds> (or after a hard timeout).
"""
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

id_file, result_file = sys.argv[1], sys.argv[2]
settle = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5

root = tk.Tk()
root.title("dictate paste target")
root.geometry("760x200+80+80")

frame = ttk.Frame(root, padding=12)
frame.pack(fill="both", expand=True)
ttk.Label(frame, text="paste here:").pack(anchor="w")
txt = tk.Text(frame, height=6, width=80)
txt.pack(fill="both", expand=True)
txt.focus_set()
root.update()

wid = root.winfo_id()
try:
    out = subprocess.run(
        ["xdotool", "search", "--name", "dictate paste target"],
        capture_output=True, text=True, timeout=5,
    ).stdout.split()
    if out:
        wid = out[-1]
except Exception:
    pass

with open(id_file, "w") as fh:
    fh.write(str(wid))
print(f"window id {wid}", flush=True)

TICK_MS = 100
HARD_LIMIT_TICKS = 400  # 40 s
state = {"ticks": 0, "stable": 0, "last": None}


def poll():
    state["ticks"] += 1
    content = txt.get("1.0", "end").strip()

    if content and content == state["last"]:
        state["stable"] += 1
    else:
        state["stable"] = 0
    state["last"] = content

    done = bool(content) and state["stable"] >= int(settle * 1000 / TICK_MS)
    expired = state["ticks"] > HARD_LIMIT_TICKS

    if done or expired:
        with open(result_file, "w") as fh:
            fh.write(content)
        lines = content.count("\n") + 1 if content else 0
        tag = "RECEIVED" if content else "TIMEOUT(empty)"
        print(f"{tag}: {lines} line(s), {len(content)} chars -> {content[:300]!r}", flush=True)
        root.destroy()
        return

    root.after(TICK_MS, poll)


root.after(TICK_MS, poll)
root.mainloop()
