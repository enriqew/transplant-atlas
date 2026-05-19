SHELL := /bin/bash
PYTHON ?= python
SNAPSHOT_DATE ?= $(shell date -u +%Y-%m-%d)
DBT_DIR := dbt_project

.PHONY: help install ingest prebuild build test export all clean format lint

help:
	@echo "Targets:"
	@echo "  install   Install dependencies (editable + dev extras)"
	@echo "  ingest    Run all bronze ingest scripts for SNAPSHOT_DATE=$(SNAPSHOT_DATE)"
	@echo "  build     dbt deps + seed + run"
	@echo "  test      dbt test + pytest"
	@echo "  export    Build final JSON/TopoJSON artifacts"
	@echo "  all       ingest + build + test + export"
	@echo "  clean     Remove DuckDB and exports"
	@echo "  format    Run ruff format"
	@echo "  lint      Run ruff check"

install:
	$(PYTHON) -m pip install -e ".[dev]"

ingest:
	$(PYTHON) -m ingest.cenatra_transplants --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.cenatra_donations --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.cenatra_waitlist --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.population_mx --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.population_world --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.godt_world --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.irodat_scraper --snapshot-date $(SNAPSHOT_DATE)
	$(PYTHON) -m ingest.mexico_boundaries --snapshot-date $(SNAPSHOT_DATE)

build: prebuild
	cd $(DBT_DIR) && dbt deps && dbt seed && dbt run

prebuild:
	$(PYTHON) $(DBT_DIR)/analyses/irodat_html_to_csv.py

test:
	cd $(DBT_DIR) && dbt test
	pytest

export:
	$(PYTHON) -m export.build_artifacts --snapshot-date $(SNAPSHOT_DATE)

all: ingest build test export

clean:
	rm -rf data/duckdb data/exports
	cd $(DBT_DIR) && rm -rf target dbt_packages logs

format:
	ruff format ingest export tests

lint:
	ruff check ingest export tests
