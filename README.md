# Data Quality — Python / Great Expectations / DBT / T-SQL

Enterprise data quality testing framework for an aircraft parts manufacturing supply chain.
Validates a full medallion pipeline (Bronze → Silver → Gold) using Great Expectations expectation
suites, DBT schema and singular tests, Python validator classes with pytest, and T-SQL validation
scripts targeting Azure Synapse / SQL Server.

## Project Structure

```
data-quality-dqa/
├── data/
│   ├── bronze/                          Raw CSV extracts with seeded quality defects
│   │   ├── suppliers_raw.csv            10 known defects across 16 records
│   │   ├── parts_catalog_raw.csv        4 known defects across 30 records
│   │   └── work_orders_raw.csv          2 known defects across 50 records
│   ├── silver/                          Cleansed CSVs — all defects resolved or excluded
│   └── gold/                            Monthly KPI aggregations by supplier
├── great_expectations/
│   ├── great_expectations.yml           File-based datasource (no DB required)
│   ├── expectations/                    5 expectation suites (bronze x2, silver x2, gold x1)
│   └── checkpoints/                     2 pipeline gate checkpoints with Slack alerts
├── dbt/
│   ├── dbt_project.yml                  Per-layer materialization strategy
│   ├── models/{bronze,silver,gold}/     schema.yml with column-level tests per layer
│   └── tests/
│       ├── generic/not_empty_string.sql Custom reusable generic test macro
│       └── singular/                   Two SQL tests — return 0 rows on pass
├── src/
│   ├── utils/data_loader.py             Layer-aware CSV loader
│   └── validators/
│       ├── completeness_validator.py    Null rates, row counts, PK uniqueness, whitespace
│       ├── consistency_validator.py     Accepted values, ranges, date/email format, FK checks
│       ├── reconciliation_validator.py  Row delta, numeric sum match, critical-row retention
│       └── statistical_profiler.py     Z-score, IQR bounds, cardinality, data freshness
├── sql/
│   ├── bronze/                          Completeness and format validation (T-SQL)
│   ├── silver/                          Referential integrity and business rules (T-SQL)
│   └── gold/                            Aggregation reconciliation and KPI checks (T-SQL)
├── tests/
│   ├── conftest.py                      Session-scoped fixtures — DataFrames loaded once
│   ├── bronze/                          24 tests — detects and documents known defects
│   ├── silver/                          24 tests — hard gate, all must pass
│   ├── gold/                            10 tests — KPI validation, blocks dashboard refresh
│   └── integration/                     8 tests — end-to-end pipeline reconciliation
├── .github/workflows/data-quality.yml      GitHub Actions CI pipeline
├── Makefile
├── pytest.ini
└── requirements.txt
```

## Technology Stack

- **Python 3.11+** · **pytest 8.3** · **pandas 2.2**
- **Great Expectations 0.18** — expectation suites, checkpoints, Data Docs
- **dbt-core 1.7** — schema tests, generic tests, singular SQL tests
- **T-SQL** — SQL Server 2019 / Azure Synapse Analytics validation scripts
- **GitHub Actions** — CI pipeline with matrix execution and artifact upload

Defined in [`requirements.txt`](requirements.txt):
`great-expectations` 0.18 · `dbt-core` 1.7 · `pandas` 2.2 · `pytest` 8.3 · `pytest-html` 4.1

## Prerequisites

- Python 3.11 or higher
- pip

## Installation

```bash
cd data-quality-dqa
pip install -r requirements.txt
```

## Running Tests

```bash
# Run by layer
make test-silver      # Silver gate — 24 tests, all green (hard pass required)
make test-gold        # Gold gate  — 10 tests, all green (blocks dashboard refresh)
make test-integration # E2E reconciliation — 8 tests, all green
make test-bronze      # Bronze gate — 24 tests, intentionally detects dirty data

# Run the full suite (66 tests)
make test

# Validate Great Expectations suite JSON files (no database required)
make ge-validate

# Generate GE Data Docs HTML quality report
make ge-docs
```

Or call pytest directly:

```bash
pytest tests/ -v                      # full suite
pytest tests/silver/ -m silver        # silver layer only
pytest tests/ --html=report.html      # with HTML report
```

## 🧪 Test Suite — 66 Tests

**Domain:** Aero parts procurement pipeline · **Target:** Bronze → Silver → Gold medallion layers

---

### 🥉 Bronze Layer — `tests/bronze/` — 24 tests

Bronze tests **detect and document** known defects. Each has a max-allowed violation count tied to a JIRA ticket. Growth beyond that count fails CI and triggers a new remediation task.

**`test_suppliers_bronze.py`** — 12 tests

| Test | What it checks | Behaviour |
|---|---|---|
| `test_required_columns_present` | All 11 source columns exist in the raw extract | PASS |
| `test_pk_is_unique` | `supplier_id` has no duplicates | PASS |
| `test_row_count_meets_minimum` | At least 10 supplier records received | PASS |
| `test_supplier_name_no_nulls` | `supplier_name` never null | PASS |
| `test_supplier_id_no_nulls` | `supplier_id` never null | PASS |
| `test_email_null_rate_within_threshold` | Email null rate ≤ 15% (SUP006 + SUP999 known) | PASS — within tolerance |
| `test_accepted_status_values` | Status in approved set — max 1 violation (SUP999: `LEGACY_SYSTEM`) | PASS — within tolerance |
| `test_accepted_payment_terms` | Payment terms in approved set — max 1 violation (SUP999) | PASS — within tolerance |
| `test_quality_rating_in_range` | quality_rating between 1.0–5.0 | PASS |
| `test_contract_date_iso_format` | Date format violations ≤ 2 (SUP004: DD/MM/YYYY · SUP999: -999) | PASS — within tolerance |
| `test_email_format_when_present` | Non-null emails must match valid format | PASS |
| `test_supplier_name_no_leading_trailing_whitespace` | Whitespace violations ≤ 1 (SUP003 known) | PASS — within tolerance |

**`test_parts_bronze.py`** — 12 tests

| Test | What it checks | Behaviour |
|---|---|---|
| `test_required_columns_present` | All 11 source columns present | PASS |
| `test_pk_is_unique` | `part_id` unique across 30 raw parts | PASS |
| `test_row_count_in_expected_range` | Between 25 and 200 parts | PASS |
| `test_part_number_no_nulls` | `part_number` never null | PASS |
| `test_part_name_null_rate_within_threshold` | Null/blank names ≤ 5% (PART028: ERP truncation bug) | PASS — within tolerance |
| `test_accepted_category_values` | Only 8 defined aircraft part categories | PASS |
| `test_accepted_uom_values` | Only 6 approved units of measure | PASS |
| `test_unit_price_positive` | Negative prices ≤ 1 (PART026: -$500 from legacy migration) | PASS — within tolerance |
| `test_lead_time_days_positive` | Lead time 1–365 days | PASS |
| `test_created_date_format` | ISO-8601 date format on all parts | PASS |
| `test_supplier_id_null_rate` | Null supplier_id ≤ 5% (PART027: MDM onboarding pending) | PASS — within tolerance |
| `test_lead_time_iqr_bounds` | Lead times within IQR statistical fence | PASS |

---

### 🥈 Silver Layer — `tests/silver/` — 24 tests

Silver tests **assert** — every test must pass at 100%. Failure blocks the Gold aggregation job.

**`test_suppliers_silver.py`** — 11 tests

| Test Class | Tests | Validates |
|---|---|---|
| `TestSilverSuppliersCompleteness` | 5 | 12 columns present · PK unique · 0% null on id/name/email (combined) · row count 14–16 · no empty strings |
| `TestSilverSuppliersConsistency` | 5 | All categorical columns accepted values (combined) · quality_rating 1.0–5.0 · ISO date + no future dates (combined) · valid email regex · no whitespace padding |
| `TestSilverSuppliersStatistical` | 1 | quality_rating cardinality ≥ 3 · country cardinality 2–20 (combined) |

**`test_parts_silver.py`** — 13 tests

| Test Class | Tests | Validates |
|---|---|---|
| `TestSilverPartsCompleteness` | 4 | Required columns · PK unique · 0% null on part_name + supplier_id (combined, PART028/027 resolved) · row count ≥ 25 |
| `TestSilverPartsConsistency` | 5 | Category/UOM accepted values (combined) · unit_price > 0 (PART026 excluded) · lead time 1–365 · ISO created_date · supplier FK integrity (SUPXXX excluded) |
| `TestSilverPartsReconciliation` | 3 | Bronze→Silver row drop ≤ 15% · no phantom part_ids introduced · all `is_critical=TRUE` parts retained |
| `TestSilverPartsStatistical` | 1 | part_category cardinality 5–15 |

---

### 🥇 Gold Layer — `tests/gold/` — 10 tests

**`test_production_metrics.py`** — 10 tests

| Test Class | Tests | Validates |
|---|---|---|
| `TestGoldMetricsCompleteness` | 4 | Required columns · composite PK unique (metric_month, supplier_id) · no nulls on key fields · row count ≥ 5 |
| `TestGoldMetricsKPIBoundaries` | 4 | All 5 KPI numeric bounds in one test · received ≤ ordered + defect ≤ received (combined) · YYYY-MM date format · supplier FK to silver |
| `TestGoldMetricsAggregationAccuracy` | 1 | defect_rate_pct = defect_count / total_parts_received × 100 (±0.1%) |
| `TestGoldMetricsStatistical` | 1 | quality_score cardinality ≥ 2 |

---

### 🔗 Integration / End-to-End — `tests/integration/` — 8 tests

**`test_pipeline_e2e.py`** — 8 tests

| Test | Layer Transition | What it validates |
|---|---|---|
| `test_row_count_slas` | Bronze → Silver | Silver retains ≥ 90%/85%/94% of bronze rows for suppliers/parts/work orders (3 entities, 1 test) |
| `test_no_phantom_pks_in_silver` | Bronze → Silver | No PKs in Silver that don't exist in Bronze — suppliers, parts, work orders (3 entities, 1 test) |
| `test_gold_spend_sourced_from_silver_closed_orders` | Silver → Gold | Gold total_spend reconciles to Silver closed order totals within 10% |
| `test_all_silver_suppliers_with_orders_have_gold_metrics` | Silver → Gold | Every supplier with closed orders in Gold months appears in Gold |
| `test_gold_defect_counts_non_negative` | Gold | No negative defect counts in the curated layer |
| `test_gold_month_continuity` | Gold | No gaps > 1 month in the Gold time series |
| `test_every_gold_supplier_traceable_to_bronze` | Bronze → Gold (lineage) | All Gold supplier_ids trace back to the bronze source — detects injected records |
| `test_work_order_part_ids_traceable_to_bronze_parts` | Bronze lineage | All work order part_ids exist in parts catalog (excluding known orphan PARTXXX) |

---

## Known Bronze Data Quality Issues

Intentional defects seeded in Bronze to demonstrate real detection and triage behaviour.

| Record | Field | Issue | JIRA |
|---|---|---|---|
| `SUP003` | `supplier_name` | Leading whitespace from ERP extract | DQ-130 |
| `SUP004` | `contract_start_date` | DD/MM/YYYY format (non-ISO) | DQ-133 |
| `SUP006` | `email` | Null — procurement contact not in ERP | DQ-141 |
| `SUP999` | multiple | Ghost record from decommissioned legacy system | DQ-145 |
| `PART026` | `unit_price` | Negative price from legacy migration (-$500) | DQ-137 |
| `PART027` | `supplier_id` | Null — supplier MDM onboarding in progress | DQ-155 |
| `PART028` | `part_name` | Blank — ERP extract truncation bug | DQ-142 |
| `PART030` | `supplier_id` | Orphaned reference `SUPXXX` (decommissioned supplier) | DQ-160 |
| `WO-2024-042` | `part_id` | Orphaned `PARTXXX` from legacy system | DQ-162 |
| `WO-2024-050` | `actual_delivery` | CLOSED status with null delivery date | DQ-165 |

Silver tests assert all of these are **absent** before data is promoted.

---

## Great Expectations

| Suite | Layer | Strictness |
|---|---|---|
| `bronze_suppliers_suite.json` | Bronze | `mostly: 0.90` on email, `mostly: 0.97` on price — documented tolerances |
| `bronze_parts_suite.json` | Bronze | `mostly` thresholds matching known defect counts |
| `silver_suppliers_suite.json` | Silver | 100% — exact schema match enforced |
| `silver_parts_suite.json` | Silver | 100% — no tolerance |
| `gold_production_suite.json` | Gold | Hard KPI boundary checks — failure blocks dashboard publish |

## DBT Tests

- **Schema tests** — `not_null`, `unique`, `accepted_values`, `relationships` (FK), `dbt_utils.expression_is_true` (KPI bounds)
- **Custom generic test** — `not_empty_string.sql` reusable across all models
- **Singular tests** — `assert_silver_parts_referential_integrity.sql` and `assert_gold_metrics_reconciliation.sql` — return 0 rows on pass

## T-SQL Validation Scripts

| Script | Purpose |
|---|---|
| `sql/bronze/01_completeness_checks.sql` | NULL counts and null rate % per column; whitespace detection |
| `sql/bronze/02_format_validation.sql` | Date format diagnosis; email regex; numeric range violations |
| `sql/silver/01_referential_integrity.sql` | LEFT JOIN orphan detection across all FK relationships |
| `sql/silver/02_business_rules.sql` | Supplier/parts/work-order domain rule enforcement |
| `sql/gold/01_aggregation_reconciliation.sql` | Silver→Gold spend, defect count, order count reconciliation with variance % |
| `sql/gold/02_kpi_boundary_checks.sql` | KPI boundary violations; defect rate math consistency; SLA breach alerting |

## CI / CD

GitHub Actions runs on every push to `main` or `feature/**` — see [`.github/workflows/data-quality.yml`](.github/workflows/data-quality.yml).

```
push / pull_request
        │
        ▼
┌──────────────────────────────────────────────────┐
│  python-dq-tests                                 │
│  Matrix: Python 3.11 · 3.12                      │
│  pytest per layer · HTML + JUnit XML artifacts   │
└──────────────────────────┬───────────────────────┘
                           │ on success
              ┌────────────┴────────────┐
              ▼                         ▼
┌─────────────────────┐   ┌─────────────────────────┐
│  great-expectations │   │  dbt-schema-check        │
│  JSON syntax check  │   │  YAML syntax validation  │
│  on all 5 suites    │   │  no database required    │
└─────────────────────┘   └─────────────────────────┘
```

## Author

**Devbrat Verma** — Senior QA / SDET · Data Quality

## License

MIT — see the repository `LICENSE`
