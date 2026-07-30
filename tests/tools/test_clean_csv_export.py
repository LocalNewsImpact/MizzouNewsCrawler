"""CSV exports must open correctly in Excel and read one row per line.

Three real problems this guards, all observed on exports from this repo:

1. A valid UTF-8 file with NO byte-order mark: Excel assumes cp1252, so every
   smart quote renders as "â€™" and every em dash as "â€”". One 206-row export
   carried 5,308 such characters across 25 distinct code points -- the whole
   file looks corrupted while being perfectly valid UTF-8.
2. Embedded newlines inside quoted article bodies: correct RFC 4180, but a
   216-row export spanned 10,473 physical lines, so "row 32" in an editor was
   the middle of logical row 2.
3. Control characters that break Excel's parser outright.
"""

import csv
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "clean_csv_export.py"
_spec = importlib.util.spec_from_file_location("_clean_csv_export", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
clean_cell = _mod.clean_cell
clean_csv = _mod.clean_csv


class TestCleanCell:
    def test_embedded_newlines_become_spaces(self):
        assert clean_cell("First para.\n\nSecond para.") == "First para. Second para."

    def test_control_characters_are_stripped(self):
        assert clean_cell("good\x00text\x0c here") == "goodtext here"

    def test_tabs_survive(self):
        assert "\t" in clean_cell("a\tb")

    def test_curly_punctuation_is_NOT_transliterated(self):
        """The BOM makes these display correctly, so rewriting a publisher's
        punctuation would corrupt the very text we are preserving."""
        original = "Clayton’s Greyhounds — they won “big”"
        assert clean_cell(original) == original

    def test_empty_and_none_pass_through(self):
        assert clean_cell("") == ""
        assert clean_cell(None) is None


class TestCleanCsv:
    def _write(self, tmp_path, rows, encoding="utf-8"):
        p = tmp_path / "export.csv"
        with p.open("w", encoding=encoding, newline="") as fh:
            csv.writer(fh).writerows(rows)
        return p

    def test_bom_is_added(self, tmp_path):
        p = self._write(tmp_path, [["url", "text"], ["u", "hello"]])
        assert p.read_bytes()[:3] != b"\xef\xbb\xbf"
        clean_csv(p)
        assert p.read_bytes()[:3] == b"\xef\xbb\xbf"

    def test_one_logical_row_per_physical_line(self, tmp_path):
        p = self._write(
            tmp_path,
            [["url", "text"], ["u", "line one\nline two\nline three"]],
        )
        # Before: the quoted field spans 3 physical lines.
        assert sum(1 for _ in p.open(encoding="utf-8")) > 2
        clean_csv(p)
        assert sum(1 for _ in p.open(encoding="utf-8-sig")) == 2

    def test_row_and_column_counts_are_unchanged(self, tmp_path):
        rows = [["a", "b", "c"], ["1", "2\n2", "3"], ["4", "5", "6"]]
        p = self._write(tmp_path, rows)
        stats = clean_csv(p)
        assert stats["rows"] == 2
        assert stats["cols"] == 3
        parsed = list(csv.reader(p.open(encoding="utf-8-sig")))
        assert len(parsed) == 3
        assert all(len(r) == 3 for r in parsed)

    def test_content_is_otherwise_untouched(self, tmp_path):
        """Only newlines and control chars change -- nothing else."""
        rows = [["url", "text"], ["https://x/y", "Café — “quoted”"]]
        p = self._write(tmp_path, rows)
        clean_csv(p)
        parsed = list(csv.reader(p.open(encoding="utf-8-sig")))
        assert parsed[1] == ["https://x/y", "Café — “quoted”"]

    def test_empty_file_does_not_crash(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        assert clean_csv(p)["rows"] == 0
