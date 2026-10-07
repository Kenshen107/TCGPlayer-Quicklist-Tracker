#!/usr/bin/env python3
"""Pop-up window: watches a folder for new Quicklist PDFs, shows totals and
credit offers, and logs prices to the history DB.

  python window.py "C:\\path\\to\\pdf\\folder"
"""
import argparse
import json
import os
import tkinter as tk
from tkinter import ttk

import tracker

POLL_MS = 1500
BASES = ["low", "market", "lower", "higher"]


class App:
    def __init__(self, root, folder, config_path, db):
        self.root, self.folder, self.config_path = root, folder, config_path
        self.con = tracker.connect(db)
        with open(config_path) as f:
            self.config = json.load(f)
        self.cards = []
        self.opt_vars = []  # (basis StringVar, percent StringVar)
        self.seen = {f: m for f, m in self._pdfs()}  # ignore files already there

        root.title("Quicklist Tracker")
        root.attributes("-topmost", True)
        self.status = tk.StringVar(value=f"Waiting for a new PDF in {folder}")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=8, pady=4)

        self.tree = ttk.Treeview(root, show="headings", height=10)
        self.tree.pack(fill="both", expand=True, padx=8)

        self.opts_frame = ttk.Frame(root)
        self.opts_frame.pack(fill="x", padx=8, pady=6)
        self.totals_var = tk.StringVar()
        ttk.Label(root, textvariable=self.totals_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8)
        ttk.Button(root, text="Save credit settings", command=self.save_config).pack(anchor="e", padx=8, pady=6)

        self.build_options()
        self.refresh()
        self.poll()

    def _pdfs(self):
        try:
            for f in os.listdir(self.folder):
                if f.lower().endswith(".pdf"):
                    p = os.path.join(self.folder, f)
                    yield p, os.path.getmtime(p)
        except OSError:
            return

    def build_options(self):
        for w in self.opts_frame.winfo_children():
            w.destroy()
        self.opt_vars = []
        for i, o in enumerate(self.config["options"]):
            ttk.Label(self.opts_frame, text=o["name"], width=14).grid(row=i, column=0, sticky="w")
            b = tk.StringVar(value=o["basis"])
            p = tk.StringVar(value=f"{o['percent']:g}")
            ttk.Combobox(self.opts_frame, textvariable=b, values=BASES, width=8, state="readonly").grid(row=i, column=1, padx=4)
            ttk.Spinbox(self.opts_frame, textvariable=p, from_=0, to=200, increment=5, width=6).grid(row=i, column=2)
            ttk.Label(self.opts_frame, text="%").grid(row=i, column=3)
            for v in (b, p):
                v.trace_add("write", lambda *_: self.apply_vars())
            self.opt_vars.append((b, p))

    def apply_vars(self):
        for o, (b, p) in zip(self.config["options"], self.opt_vars):
            try:
                o["percent"] = float(p.get())
            except ValueError:
                continue  # half-typed value
            o["basis"] = b.get()
        self.refresh()

    def save_config(self):
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)
        self.status.set("Credit settings saved.")

    def refresh(self):
        names = [o["name"] for o in self.config["options"]]
        cols = ["Card", "Cond", "Qty", "Low", "Market", "Lowest seen"] + names
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=230 if c == "Card" else 85, anchor="w" if c == "Card" else "e")
        self.tree.delete(*self.tree.get_children())
        fmt = lambda v: "-" if v is None else f"${v:,.2f}"
        rows, totals, qty, low_t, mkt_t = tracker.compute_offers(self.cards, self.config)
        for c, cells in rows:
            self.tree.insert("", "end", values=[c["name"], c["condition"], c["quantity"], fmt(c["low"]),
                             fmt(c["market"]), fmt(tracker.lowest_seen(self.con, c))] + [fmt(x) for x in cells])
        parts = [f"{n}: {fmt(totals[n])}" for n in names]
        self.totals_var.set(f"{qty} cards   Low {fmt(low_t)}   Market {fmt(mkt_t)}   |   " + "   ".join(parts))

    def load(self, path):
        cards, printed = tracker.parse_pdf(path)
        tracker.record(self.con, cards, os.path.basename(path), printed)
        self.cards = cards
        self.status.set(f"{os.path.basename(path)}  (printed {printed or 'unknown'})")
        self.refresh()
        self.root.deiconify()
        self.root.lift()

    def poll(self):
        for p, m in self._pdfs():
            if self.seen.get(p) == m:
                continue
            try:
                self.load(p)
                self.seen[p] = m
            except (OSError, ValueError):
                pass  # still being written; retry next poll
        self.root.after(POLL_MS, self.poll)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder")
    ap.add_argument("-c", "--config", default="credit.json")
    ap.add_argument("--db", default=tracker.DEFAULT_DB)
    a = ap.parse_args()
    root = tk.Tk()
    App(root, a.folder, a.config, a.db)
    root.mainloop()


if __name__ == "__main__":
    main()
