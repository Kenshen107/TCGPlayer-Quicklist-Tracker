# TCGplayer Quicklist Tracker

Records the **Low Price** and **Market** values from TCGplayer Quicklist
exports into a local SQLite DB (`prices.db`) so you can see the lowest price
ever seen per card.

```
python tracker.py watch "C:\path\to\exports"   # auto-record when files change
python tracker.py import list.csv              # one-off
python tracker.py report                       # lowest Low/Market per card
python tracker.py history "Konstrari"          # all readings over time
```

A card is identified by name + set + condition + printing + language. A new
reading is stored only when its prices differ from that card's latest one.
**PDFs** (the app's Print/Save-as-PDF output) are the primary format; they need
poppler's `pdftotext` on PATH (Windows: install poppler and add its `bin` to PATH).
The "Printed …" time in the PDF is used as the reading time, a "—" Low Price
means no listing, and a $0.00 Market beside it is treated as no data.
CSV/TSV/JSON columns are matched by header name (Product Name, Set, Condition, Printing,
Lang., Qty., Low Price, Market); CSV/TSV and JSON are supported.
Requires Python 3.8+, no dependencies. Tests: `pytest tests`.

## Totals and credit offers

```
python tracker.py quote list.pdf              # uses credit.json
python tracker.py quote list.pdf -c other.json
```

Prints each card's offer and the totals (quantity, Low, Market, and one column
per option). Edit `credit.json` to change options: each has a `basis`
(`low`, `market`, `lower`, `higher`) and a `percent`; add or remove options
freely. `condition_multipliers` scale offers by condition, and
`min_offer_per_card` sets a floor. Unpriced cards are offered $0 and listed.

## Pop-up window (no extra steps for staff)

```
python window.py "C:\path\to\pdf\folder"
```

Stays on top. When a new Quicklist PDF appears in the folder it jumps to the
front, shows each card with its Low, Market and lowest price ever seen, plus
the totals and each credit option's offer. Change an option's basis or percent
in the window and totals update instantly; "Save credit settings" writes them
to `credit.json`. Every PDF is also logged to the price history.

Setup: install a virtual PDF printer (e.g. PDFCreator) set to auto-save PDFs
to that folder and also forward to the real printer, so staff press Print once
as usual. Needs Python with Tkinter (included with the python.org Windows
installer) and poppler's `pdftotext` on PATH.
