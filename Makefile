.PHONY: install validate-bronze validate-silver validate-gold validate-all \
        test test-bronze test-silver test-gold test-integration \
        ge-validate ge-docs clean reports-dir

PYTHON  := python
PYTEST  := pytest
PIP     := pip

# ── Setup ─────────────────────────────────────────────────────────────
install:
	$(PIP) install -r requirements.txt

# ── pytest targets ────────────────────────────────────────────────────
reports-dir:
	@mkdir -p reports

test-bronze: reports-dir
	@echo "▶ Running Bronze layer DQ tests (expects known issues)..."
	$(PYTEST) tests/bronze/ -v -m bronze \
		--html=reports/bronze_report.html --self-contained-html \
		--junitxml=reports/bronze_junit.xml

test-silver: reports-dir
	@echo "▶ Running Silver layer DQ tests (must all pass)..."
	$(PYTEST) tests/silver/ -v -m silver \
		--html=reports/silver_report.html --self-contained-html \
		--junitxml=reports/silver_junit.xml

test-gold: reports-dir
	@echo "▶ Running Gold layer DQ tests..."
	$(PYTEST) tests/gold/ -v -m gold \
		--html=reports/gold_report.html --self-contained-html \
		--junitxml=reports/gold_junit.xml

test-integration: reports-dir
	@echo "▶ Running integration / E2E pipeline tests..."
	$(PYTEST) tests/integration/ -v -m integration \
		--html=reports/integration_report.html --self-contained-html \
		--junitxml=reports/integration_junit.xml

test: reports-dir
	@echo "▶ Running full DQ test suite..."
	$(PYTEST) tests/ -v \
		--html=reports/full_dq_report.html --self-contained-html \
		--junitxml=reports/full_junit.xml

# Aliases matching the plan's validate-* naming
validate-bronze:  test-bronze
validate-silver:  test-silver
validate-gold:    test-gold
validate-all:     test

# ── Great Expectations ────────────────────────────────────────────────
ge-validate:
	@echo "▶ Validating GE expectation suite JSON syntax..."
	$(PYTHON) -c " \
	import json, glob, sys; \
	suites = glob.glob('great_expectations/expectations/*.json'); \
	[print('OK', f) or json.load(open(f)) for f in suites]; \
	print(f'All {len(suites)} suites valid.') \
	"

ge-docs:
	@echo "▶ Running GE checkpoints and generating Data Docs..."
	cd great_expectations && \
	great_expectations checkpoint run bronze_checkpoint && \
	great_expectations checkpoint run silver_checkpoint && \
	great_expectations docs build

# ── DBT ───────────────────────────────────────────────────────────────
dbt-debug:
	@echo "▶ DBT debug (connection test)..."
	cd dbt && dbt debug

dbt-test:
	@echo "▶ Running DBT schema + singular tests..."
	cd dbt && dbt test

# ── Cleanup ───────────────────────────────────────────────────────────
clean:
	@rm -rf reports/ great_expectations/uncommitted/validations/ \
		    great_expectations/uncommitted/data_docs/ \
		    dbt/target/ .pytest_cache/ __pycache__/ \
		    src/__pycache__/ src/**/__pycache__/ tests/**/__pycache__/
	@echo "Cleaned."
