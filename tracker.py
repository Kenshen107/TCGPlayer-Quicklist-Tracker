#!/usr/bin/env python3
"""Track Low Price / Market price history from TCGplayer Quicklist exports.

Usage:
  tracker.py import FILE            record one export/project file
  tracker.py watch PATH [-i SECS]   poll a file or folder, record on change
  tracker.py quote FILE [-c credit.json]   totals + cash/credit offers
  tracker.py report [--db DB]       lowest Low Price / Market seen per card
  tracker.py history NAME           every reading for cards matching NAME
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

DEFAULT_DB = "prices.db"

# canonical field -> accepted header spellings (normalised: lowercase, alnum only)
ALIASES = {
    "name": ["productname", "product", "name", "cardname", "card"],
    "set": ["set", "setname", "expansion"],
    "condition": ["condition", "cond"],
    "printing": ["printing", "foil"],
    "language": ["language", "lang"],
    "quantity": ["quantity", "qty"],
    "low": ["lowprice", "low", "lowestprice", "tcglowprice"],
    "market": ["marketprice", "market", "tcgmarketprice"],
}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_price(v):
    """'$0.12' -> 0.12; blank/'-'/non-numeric -> None."""
    if v is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    return float(m.group().replace(",", "")) if m else None


def _map_row(row):
    """Map a dict with arbitrary keys onto canonical fields; None if no name+price."""
    lookup = {_norm(k): v for k, v in row.items() if k is not None}
    out = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in lookup and str(lookup[n]).strip() != "":
                out[field] = str(lookup[n]).strip()
                break
    if "name" not in out or ("low" not in out and "market" not in out):
        return None
    return {
        "name": out["name"],
        "set": out.get("set", ""),
        "condition": out.get("condition", ""),
        "printing": out.get("printing", ""),
        "language": out.get("language", ""),
        "quantity": int(parse_price(out.get("quantity")) or 1),
        "low": parse_price(out.get("low")),
        "market": parse_price(out.get("market")),
    }


def _walk_json(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_json(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_json(v)


PRINTED_RE = re.compile(r"Printed\s+(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})")


def parse_pdf(path):
    """Parse a Quicklist 'Print' PDF. Returns (cards, printed_at_iso or None).

    Needs poppler's `pdftotext`. Rows are split on runs of 2+ spaces:
    name | set | cond | printing | lang | "qty #" | low | market
    """
    try:
        text = subprocess.run(
            ["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True
        ).stdout
    except FileNotFoundError:
        raise ValueError("pdftotext not found (install poppler-utils / poppler for Windows)")
    except subprocess.CalledProcessError as e:
        raise ValueError(f"pdftotext failed: {e.stderr.strip()}")
    cards = []
    for line in text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) != 8 or not re.fullmatch(r"\d+\s+\d+", parts[5]):
            continue
        name, set_, cond, printing, lang, qty_no, low, market = parts
        low, market = parse_price(low), parse_price(market)
        if low is None and not market:  # "—" low and $0.00 market = no data
            market = None
        cards.append({"name": name, "set": set_, "condition": cond, "printing": printing,
                      "language": lang, "quantity": int(qty_no.split()[0]),
                      "low": low, "market": market})
    m = PRINTED_RE.search(text)
    printed = None
    if m:
        mo, d, y, h, mi = m.groups()
        printed = f"{y}-{mo}-{d}T{h}:{mi}:00"  # local time as printed
    return cards, printed


def parse_file(path):
    """Return a list of card dicts from a PDF/CSV/TSV/JSON export."""
    if path.lower().endswith(".pdf"):
        return parse_pdf(path)[0]
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        rows = _walk_json(json.loads(text))
    else:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        rows = csv.DictReader(text.splitlines(), dialect=dialect)
    return [c for c in (_map_row(r) for r in rows) if c]


def connect(db):
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY, ts TEXT NOT NULL,
            name TEXT NOT NULL, "set" TEXT, condition TEXT, printing TEXT,
            language TEXT, low REAL, market REAL, source TEXT)"""
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_card ON readings(name, "set", condition, printing, language)'
    )
    return con


KEY = ("name", "set", "condition", "printing", "language")


def record(con, cards, source="", ts=None):
    """Insert a reading per card unless its prices match that card's latest reading."""
    ts = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for c in cards:
        last = con.execute(
            'SELECT low, market FROM readings WHERE name=? AND "set"=? AND condition=? '
            "AND printing=? AND language=? ORDER BY id DESC LIMIT 1",
            [c[k] for k in KEY],
        ).fetchone()
        if last == (c["low"], c["market"]):
            continue
        con.execute(
            'INSERT INTO readings (ts,name,"set",condition,printing,language,low,market,source) '
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, *[c[k] for k in KEY], c["low"], c["market"], source),
        )
        added += 1
    con.commit()
    return added


def report(con, out=sys.stdout):
    rows = con.execute(
        """SELECT name, "set", condition, printing, language,
                  MIN(low), MIN(market), COUNT(*),
                  (SELECT low FROM readings r2 WHERE r2.name=r.name AND r2."set"=r."set"
                     AND r2.condition=r.condition AND r2.printing=r.printing
                     AND r2.language=r.language ORDER BY id DESC LIMIT 1)
           FROM readings r GROUP BY name, "set", condition, printing, language
           ORDER BY name"""
    ).fetchall()
    if not rows:
        print("No readings yet.", file=out)
        return
    fmt = lambda v: "-" if v is None else f"${v:.2f}"
    print(f"{'Card':32} {'Set':20} {'Cond':4} {'Print':7} {'Lang':4} {'Lowest Low':>10} {'Lowest Mkt':>10} {'Latest Low':>10} {'N':>3}", file=out)
    for n, s, c, p, l, lo, mk, cnt, latest in rows:
        print(f"{n[:32]:32} {s[:20]:20} {c:4} {p:7} {l:4} {fmt(lo):>10} {fmt(mk):>10} {fmt(latest):>10} {cnt:>3}", file=out)


def history(con, name, out=sys.stdout):
    rows = con.execute(
        'SELECT ts,name,"set",condition,printing,low,market FROM readings '
        "WHERE name LIKE ? ORDER BY name, ts",
        (f"%{name}%",),
    ).fetchall()
    fmt = lambda v: "-" if v is None else f"${v:.2f}"
    for ts, n, s, c, p, lo, mk in rows:
        print(f"{ts}  {n} [{s}, {c}, {p}]  low {fmt(lo)}  market {fmt(mk)}", file=out)
    if not rows:
        print("No matching readings.", file=out)


def ingest(con, path):
    """Parse one file and record it; PDFs use their printed timestamp."""
    ts = None
    if path.lower().endswith(".pdf"):
        cards, ts = parse_pdf(path)
    else:
        cards = parse_file(path)
    return record(con, cards, os.path.basename(path), ts), len(cards)


def _basis_price(c, basis):
    low, mkt = c["low"], c["market"]
    vals = [v for v in (low, mkt) if v is not None]
    if basis == "low":
        return low
    if basis == "market":
        return mkt
    if not vals:
        return None
    return min(vals) if basis == "lower" else max(vals)


def compute_offers(cards, config):
    """Per-card offers and totals. Returns (rows, totals, qty, low_total, market_total).

    rows: list of (card, [line total per option or None]); totals: {option name: total}.
    """
    opts = config["options"]
    mult = config.get("condition_multipliers", {})
    floor = config.get("min_offer_per_card", 0.0)
    totals = {o["name"]: 0.0 for o in opts}
    qty = low_t = mkt_t = 0
    rows = []
    for c in cards:
        q = c["quantity"]
        qty += q
        low_t += (c["low"] or 0) * q
        mkt_t += (c["market"] or 0) * q
        cm = mult.get(c["condition"], 1.0)
        cells = []
        for o in opts:
            base = _basis_price(c, o["basis"])
            if base is None:
                cells.append(None)
                continue
            line = max(base * o["percent"] / 100 * cm, floor) * q
            totals[o["name"]] += line
            cells.append(line)
        rows.append((c, cells))
    return rows, totals, qty, low_t, mkt_t


def quote(cards, config, out=sys.stdout):
    """Print per-card offers and totals for each credit option in `config`."""
    opts = config["options"]
    rows, totals, qty, low_t, mkt_t = compute_offers(cards, config)
    fmt = lambda v: "-" if v is None else f"${v:,.2f}"
    head = f"{'Card':38} {'Cond':4} {'Qty':>3} {'Low':>8} {'Market':>8}" + "".join(f" {o['name'][:12]:>12}" for o in opts)
    print(head, file=out)
    unpriced = []
    for c, cells in rows:
        if all(x is None for x in cells):
            unpriced.append(c["name"])
        print(f"{c['name'][:38]:38} {c['condition']:4} {c['quantity']:>3} {fmt(c['low']):>8} {fmt(c['market']):>8}" + "".join(f" {fmt(x):>12}" for x in cells), file=out)
    print("-" * len(head), file=out)
    print(f"{'TOTAL':38} {'':4} {qty:>3} {fmt(low_t):>8} {fmt(mkt_t):>8}" + "".join(f" {fmt(totals[o['name']]):>12}" for o in opts), file=out)
    if unpriced:
        print(f"Note: no price for {len(unpriced)} card(s), offered $0: {', '.join(unpriced)}", file=out)
    return totals


def lowest_seen(con, c):
    """Lowest Low Price ever recorded for this card (None if never priced)."""
    row = con.execute(
        'SELECT MIN(low) FROM readings WHERE name=? AND "set"=? AND condition=? '
        "AND printing=? AND language=?",
        [c[k] for k in KEY],
    ).fetchone()
    return row[0]


def _candidates(path):
    if os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith((".pdf", ".csv", ".tsv", ".json", ".txt")):
                yield os.path.join(path, f)
    else:
        yield path


def watch(path, db, interval):
    con = connect(db)
    seen = {}
    print(f"Watching {path} every {interval}s (Ctrl+C to stop)")
    while True:
        for f in _candidates(path):
            try:
                mtime = os.path.getmtime(f)
                if seen.get(f) == mtime:
                    continue
                seen[f] = mtime
                n = ingest(con, f)
                print(f"{datetime.now():%H:%M:%S} {os.path.basename(f)}: {n[0]} new reading(s) from {n[1]} card(s)")
            except (OSError, ValueError, csv.Error) as e:
                print(f"skipping {f}: {e}", file=sys.stderr)
        time.sleep(interval)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import").add_argument("file")
    w = sub.add_parser("watch")
    w.add_argument("path")
    w.add_argument("-i", "--interval", type=float, default=5)
    q = sub.add_parser("quote")
    q.add_argument("file")
    q.add_argument("-c", "--config", default="credit.json")
    sub.add_parser("report")
    sub.add_parser("history").add_argument("name")
    a = ap.parse_args(argv)

    if a.cmd == "watch":
        try:
            watch(a.path, a.db, a.interval)
        except KeyboardInterrupt:
            pass
        return 0
    if a.cmd == "quote":
        try:
            with open(a.config) as f:
                config = json.load(f)
            quote(parse_file(a.file), config)
        except (OSError, ValueError, KeyError) as e:
            print(f"quote failed: {e}", file=sys.stderr)
            return 1
        return 0
    con = connect(a.db)
    if a.cmd == "import":
        try:
            added, total = ingest(con, a.file)
        except (OSError, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
        if not total:
            print("No cards with a name and Low/Market price found in the file.", file=sys.stderr)
            return 1
        print(f"{added} new reading(s) from {total} card(s)")
    elif a.cmd == "report":
        report(con)
    elif a.cmd == "history":
        history(con, a.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
