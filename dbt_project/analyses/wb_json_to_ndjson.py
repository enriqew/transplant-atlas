"""Pre-step for stg_population_world: convert the World Bank JSON envelope to NDJSON.

The World Bank indicator API returns a top-level array of exactly two elements:
  [ metadata_object, rows_array ]

`read_json_auto` doesn't handle this shape gracefully (each top-level element has
a wildly different schema), so we pre-flatten the rows_array into one record per
line and let DuckDB read it via `read_json('*.ndjson', format='newline_delimited')`.

Reads the latest `data/raw/population_world/<date>/sp.pop.totl.json`,
writes a sibling `sp.pop.totl.rows.ndjson`.

Failure modes:
  - No bronze snapshot → exit non-zero
  - JSON shape not the expected [meta, rows] array → exit non-zero
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "population_world"


def _latest_snapshot() -> Path:
    if not RAW_ROOT.exists():
        raise SystemExit(f"no World Bank snapshots under {RAW_ROOT}")
    candidates = sorted(p for p in RAW_ROOT.iterdir() if p.is_dir())
    if not candidates:
        raise SystemExit(f"no dated subdirectories under {RAW_ROOT}")
    return candidates[-1]


def main() -> int:
    snapshot = _latest_snapshot()
    src = snapshot / "sp.pop.totl.json"
    if not src.exists():
        print(f"ERROR: missing {src}", file=sys.stderr)
        return 1

    with src.open(encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
        print(
            f"ERROR: unexpected WB JSON shape in {src} — expected [meta, rows]",
            file=sys.stderr,
        )
        return 1

    rows = payload[1]
    dest = snapshot / "sp.pop.totl.rows.ndjson"

    written = 0
    with dest.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            written += 1

    print(f"wrote {written} rows -> {dest}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
