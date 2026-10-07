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
