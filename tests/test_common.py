"""Unit tests for ingest._common helpers (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest._common import (
    FileRecord,
    SnapshotMeta,
    build_argparser,
    count_csv_rows,
    pipeline_version,
    sha256_of,
    snapshot_dir,
    utcnow_iso,
    write_meta,
)


def test_argparser_defaults_to_today(monkeypatch):
    parser = build_argparser("dummy")
    args = parser.parse_args([])
    assert len(args.snapshot_date) == 10
    assert args.snapshot_date[4] == "-" and args.snapshot_date[7] == "-"
    assert args.force is False
    assert args.dry_run is False


def test_argparser_accepts_flags():
    parser = build_argparser("dummy")
    args = parser.parse_args(
        ["--snapshot-date", "2026-01-15", "--force", "--dry-run"]
    )
    assert args.snapshot_date == "2026-01-15"
    assert args.force is True
    assert args.dry_run is True


def test_snapshot_dir_path():
    target = snapshot_dir("cenatra_transplants", "2026-02-03")
    assert target.as_posix().endswith("data/raw/cenatra_transplants/2026-02-03")


def test_sha256_stable_on_fixture(tmp_path: Path):
    fixture = tmp_path / "fixture.csv"
    fixture.write_bytes(b"state,year,value\nJAL,2024,42\n")
    first = sha256_of(fixture)
    second = sha256_of(fixture)
    assert first == second
    assert len(first) == 64


def test_count_csv_rows(tmp_path: Path):
    fixture = tmp_path / "rows.csv"
    fixture.write_text("h1,h2\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert count_csv_rows(fixture) == 3


def test_count_csv_rows_empty(tmp_path: Path):
    fixture = tmp_path / "empty.csv"
    fixture.write_text("", encoding="utf-8")
    assert count_csv_rows(fixture) == 0


def test_write_meta_roundtrips(tmp_path: Path):
    meta = SnapshotMeta(
        source="dummy",
        snapshot_date="2026-04-01",
        fetched_at=utcnow_iso(),
        pipeline_version="0.1.0",
        files=[
            FileRecord(name="x.csv", url="https://x", sha256="a" * 64, bytes=42, row_count=5),
        ],
    )
    write_meta(tmp_path, meta)
    loaded = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert loaded["source"] == "dummy"
    assert loaded["files"][0]["sha256"] == "a" * 64
    assert loaded["files"][0]["row_count"] == 5


def test_pipeline_version_resolves():
    version = pipeline_version()
    assert version
    assert version != "0.0.0+unknown", "version should be readable from pyproject.toml"
