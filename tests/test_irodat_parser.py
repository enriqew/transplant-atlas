"""Tests for the IRODaT HTML→CSV pre-step parser (analyses/irodat_html_to_csv.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dbt_project" / "analyses" / "irodat_html_to_csv.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("irodat_html_to_csv", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_to_int_handles_commas_and_spaces():
    mod = _load_module()
    assert mod._to_int("1,234") == 1234
    assert mod._to_int("  42 ") == 42
    assert mod._to_int("") is None
    assert mod._to_int("abc") is None


def test_row_extractor_collects_tr_cells():
    mod = _load_module()
    parser = mod._RowExtractor()
    html = """
    <html><body>
      <h1>Spain</h1>
      <table>
        <tr><td>2023</td><td>5,594</td><td>2,562</td><td>419</td></tr>
        <tr><td>2022</td><td>5,383</td><td>2,469</td><td>391</td></tr>
      </table>
    </body></html>
    """
    parser.feed(html)
    assert parser.title == "Spain"
    assert len(parser.rows) == 2
    assert parser.rows[0] == ["2023", "5,594", "2,562", "419"]
