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


def test_to_int_lenient():
    mod = _load_module()
    assert mod._to_int("1,234") == 1234
    assert mod._to_int("  42 ") == 42
    assert mod._to_int("") is None
    assert mod._to_int("-") is None
    assert mod._to_int("—") is None
    assert mod._to_int("abc") is None


def test_country_name_strips_suffix():
    mod = _load_module()
    html = "<html><body><h1>Mexico deceased organ donor evolution</h1></body></html>"
    assert mod._country_name(html, "fallback") == "Mexico"


def test_country_name_falls_back():
    mod = _load_module()
    assert mod._country_name("<html></html>", "country_es_spain") == "country_es_spain"


def test_extract_one_spain_fixture():
    mod = _load_module()
    # Minimal fixture mirroring IRODaT's real layout: detailed donations table + transplants table.
    html = """
    <html><body>
      <h1>Spain deceased organ donor evolution</h1>
      <table>
        <tr><th>ORGAN DONATIONS</th><th>2024</th><th>Actual Deceased Donors</th>
            <th>Utilized Deceased Donors</th><th>Actual DCD Donors</th>
            <th>Utilized DCD Donors</th><th>Living Donors</th><th></th></tr>
        <tr><td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td>
            <td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td></tr>
        <tr><td></td><td></td><td>2562</td><td>53.93</td><td>2278</td><td>47.95</td>
            <td>1316</td><td>27.71</td><td>1149</td><td>24.19</td><td>405</td><td>8.53</td></tr>
      </table>
      <table>
        <tr><th>ORGAN TRANSPLANTS</th><th>2024</th><th>KIDNEY</th><th>LIVER</th>
            <th>PANCREAS</th><th>HEART</th><th>LUNG</th><th>HEART LUNG</th></tr>
        <tr><td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td>
            <td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td><td>NUM</td><td>PMP</td></tr>
        <tr><td></td><td>DECEASED</td><td>3651</td><td>76.86</td><td>1336</td><td>28.13</td>
            <td>97</td><td>2.04</td><td>347</td><td>7.30</td><td>623</td><td>13.11</td>
            <td>-</td><td>-</td></tr>
        <tr><td></td><td>LIVING</td><td>398</td><td>8.38</td><td>7</td><td>0.15</td>
            <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
      </table>
    </body></html>
    """
    record = mod._extract_one(html, "fallback")
    assert record is not None
    assert record["country_name"] == "Spain"
    assert record["report_year"] == 2024
    assert record["deceased_donors"] == 2562
    assert record["living_donors"] == 405
    # Total = 3651 + 1336 + 97 + 347 + 623 (DECEASED row) + 398 + 7 (LIVING row, ignoring '-')
    assert record["total_transplants"] == 3651 + 1336 + 97 + 347 + 623 + 398 + 7


def test_extract_one_returns_none_on_empty():
    mod = _load_module()
    assert mod._extract_one("<html></html>", "fallback") is None
