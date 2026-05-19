"""Verify the JSON Schemas in schemas/ are themselves valid draft 2020-12,
and that example records pass / counter-examples fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "mexico-transplants.schema.json",
        "world-transplants.schema.json",
        "meta.schema.json",
    ],
)
def test_schema_is_well_formed(name: str):
    schema = _load(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"].endswith("draft/2020-12/schema")


def test_mexico_record_passes():
    schema = _load("mexico-transplants.schema.json")
    record = [
        {
            "state_code": "JAL",
            "state_name": "Jalisco",
            "year": 2024,
            "organ": "kidney",
            "donations": 142,
            "transplants": 138,
            "waitlist_end_of_year": 412,
            "rate_pmp": 16.8,
            "donor_type_breakdown": {"deceased": 92, "living": 50},
        }
    ]
    jsonschema.Draft202012Validator(schema).validate(record)


def test_mexico_rejects_bad_organ():
    schema = _load("mexico-transplants.schema.json")
    record = [
        {
            "state_code": "JAL",
            "state_name": "Jalisco",
            "year": 2024,
            "organ": "spleen",  # not in enum
            "donations": 1,
            "transplants": 1,
            "waitlist_end_of_year": 0,
            "rate_pmp": 0.1,
            "donor_type_breakdown": {"deceased": 1, "living": 0},
        }
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(record)


def test_mexico_rejects_lowercase_state_code():
    schema = _load("mexico-transplants.schema.json")
    record = [
        {
            "state_code": "jal",
            "state_name": "Jalisco",
            "year": 2024,
            "organ": "kidney",
            "donations": 1,
            "transplants": 1,
            "waitlist_end_of_year": 0,
            "rate_pmp": 0.1,
            "donor_type_breakdown": {"deceased": 1, "living": 0},
        }
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(record)


def test_world_record_passes():
    schema = _load("world-transplants.schema.json")
    record = [
        {
            "country_iso3": "ESP",
            "country_name": "Spain",
            "year": 2024,
            "total_transplants": 5594,
            "deceased_donors": 2562,
            "living_donors": 419,
            "deceased_donors_pmp": 53.5,
            "living_donors_pmp": 8.7,
            "transplants_pmp": 116.8,
            "source": "GODT",
        }
    ]
    jsonschema.Draft202012Validator(schema).validate(record)


def test_world_rejects_bad_source():
    schema = _load("world-transplants.schema.json")
    record = [
        {
            "country_iso3": "ESP",
            "country_name": "Spain",
            "year": 2024,
            "total_transplants": 1,
            "deceased_donors": 1,
            "living_donors": 0,
            "deceased_donors_pmp": 0.1,
            "living_donors_pmp": 0.0,
            "transplants_pmp": 0.1,
            "source": "INVENTED",
        }
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(record)


def test_meta_record_passes():
    schema = _load("meta.schema.json")
    record = {
        "generated_at": "2026-05-18T14:32:00Z",
        "pipeline_version": "0.1.0",
        "sources": [
            {
                "name": "CENATRA_transplants::trasplantes_2024_T3.csv",
                "url": "https://example.org/file.csv",
                "snapshot_date": "2026-05-15",
                "sha256": "a" * 64,
                "rows_ingested": 100,
                "bytes": 4096,
            }
        ],
        "artifact_row_counts": {
            "mexico_transplants": 100,
            "world_transplants": 200,
        },
        "coverage": {
            "mexico_years": [2018, 2024],
            "world_years": [2010, 2024],
            "countries": 92,
        },
    }
    jsonschema.Draft202012Validator(schema).validate(record)
