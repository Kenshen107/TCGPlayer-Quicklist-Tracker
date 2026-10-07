import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import tracker


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


HDR = "Product Name,Set,Condition,Printing,Lang.,Qty.,Low Price,Market\n"


def test_parse_and_track_lowest(tmp_path):
    f1 = write(tmp_path, "a.csv", HDR + "Konstrari Improviser,Reality Fracture,NM,Foil,EN,1,$0.12,$0.27\n")
    f2 = write(tmp_path, "b.csv", HDR + "Konstrari Improviser,Reality Fracture,NM,Foil,EN,1,$0.09,$0.30\n")
    con = tracker.connect(":memory:")
    assert tracker.record(con, tracker.parse_file(f1)) == 1
    assert tracker.record(con, tracker.parse_file(f1)) == 0  # unchanged -> deduped
    assert tracker.record(con, tracker.parse_file(f2)) == 1
    out = io.StringIO()
    tracker.report(con, out)
    assert "$0.09" in out.getvalue() and "$0.27" in out.getvalue()


def test_json_and_missing_price(tmp_path):
    f = write(tmp_path, "p.json", '{"items":[{"Product Name":"X","Low Price":"-","Market":"$1,000.50"}]}')
    cards = tracker.parse_file(f)
    assert cards[0]["low"] is None and cards[0]["market"] == 1000.50
