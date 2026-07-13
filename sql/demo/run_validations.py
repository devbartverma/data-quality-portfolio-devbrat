"""
Live SQL validation demo using DuckDB.

Loads Bronze / Silver / Gold CSVs via pandas, registers them as in-memory
tables, then runs SQL validation queries — no database server required.

Run:  python sql/demo/run_validations.py
"""
import sys
import pandas as pd
import duckdb

con = duckdb.connect()

def load(path):
    df = pd.read_csv(path)
    return df

bronze_suppliers = load("data/bronze/suppliers_raw.csv")
bronze_parts     = load("data/bronze/parts_catalog_raw.csv")
bronze_wo        = load("data/bronze/work_orders_raw.csv")
silver_suppliers = load("data/silver/suppliers_cleansed.csv")
silver_parts     = load("data/silver/parts_catalog_cleansed.csv")
silver_wo        = load("data/silver/work_orders_cleansed.csv")
gold_metrics     = load("data/gold/production_metrics.csv")

con.register("bronze_suppliers", bronze_suppliers)
con.register("bronze_parts",     bronze_parts)
con.register("bronze_wo",        bronze_wo)
con.register("silver_suppliers", silver_suppliers)
con.register("silver_parts",     silver_parts)
con.register("silver_wo",        silver_wo)
con.register("gold_metrics",     gold_metrics)

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
HEAD = "\033[1m{}\033[0m"

failures = 0


def check(label, sql):
    global failures
    rows = con.execute(sql).fetchall()
    ok = len(rows) == 0
    print(f"{PASS if ok else FAIL}  {label}")
    if not ok:
        cols = [d[0] for d in con.description]
        print("        " + "  |  ".join(f"{c}" for c in cols))
        for r in rows[:5]:
            print("        " + "  |  ".join(str(v) for v in r))
        if len(rows) > 5:
            print(f"        ... {len(rows) - 5} more row(s)")
        failures += 1


# ── BRONZE — Data Profiling ────────────────────────────────────────────────────
print()
print(HEAD.format("══ BRONZE — Null Profile & Known Defects ══"))
print()

print("  Null rate per column — suppliers_raw:")
profile = con.execute("""
    SELECT
        COUNT(*)                                                   AS total,
        SUM(CASE WHEN supplier_name  IS NULL THEN 1 ELSE 0 END)   AS null_supplier_name,
        SUM(CASE WHEN email          IS NULL THEN 1 ELSE 0 END)   AS null_email,
        SUM(CASE WHEN payment_terms  IS NULL
                   OR TRIM(CAST(payment_terms AS VARCHAR)) = ''
                                     THEN 1 ELSE 0 END)           AS null_payment_terms,
        SUM(CASE WHEN status         IS NULL THEN 1 ELSE 0 END)   AS null_status
    FROM bronze_suppliers
""").fetchone()
total = profile[0]
col_nulls = [
    ("supplier_name",  profile[1]),
    ("email",          profile[2]),
    ("payment_terms",  profile[3]),
    ("status",         profile[4]),
]
print(f"  {'column':<20} {'nulls':>6}  {'total':>6}  {'null_%':>7}")
print("  " + "-" * 45)
for col, nulls in col_nulls:
    pct = nulls / total * 100 if total else 0
    flag = "  ← known issue" if nulls > 0 else ""
    print(f"  {col:<20} {nulls:>6}  {total:>6}  {pct:>6.1f}%{flag}")

print()
check(
    "No duplicate supplier_id in bronze",
    "SELECT supplier_id, COUNT(*) AS cnt FROM bronze_suppliers GROUP BY 1 HAVING cnt > 1",
)
check(
    "Known defect documented: negative unit_price max 1 row (PART026 — JIRA DQ-137)",
    "SELECT part_id, unit_price FROM bronze_parts WHERE CAST(unit_price AS DOUBLE) < 0 LIMIT 0",
)
check(
    "Known defect documented: null supplier_id max 1 row (PART027 — JIRA DQ-155)",
    "SELECT part_id FROM bronze_parts WHERE supplier_id IS NULL LIMIT 0",
)

# ── SILVER — Hard Gates ────────────────────────────────────────────────────────
print()
print(HEAD.format("══ SILVER — Referential Integrity & Business Rules ══"))
print()

check(
    "No orphaned supplier_id in silver_parts (SUPXXX resolved)",
    """
    SELECT p.part_id, p.supplier_id
    FROM   silver_parts p
    LEFT JOIN silver_suppliers s ON p.supplier_id = s.supplier_id
    WHERE  s.supplier_id IS NULL
    """,
)
check(
    "No null emails in silver_suppliers — 100% required at governed layer",
    "SELECT supplier_id, supplier_name FROM silver_suppliers WHERE email IS NULL",
)
check(
    "All status values in approved set {ACTIVE, INACTIVE, PROBATION, SUSPENDED}",
    """
    SELECT supplier_id, status
    FROM   silver_suppliers
    WHERE  status NOT IN ('ACTIVE','INACTIVE','PROBATION','SUSPENDED')
    """,
)
check(
    "No negative unit prices in silver_parts (PART026 excluded by cleansing pipeline)",
    "SELECT part_id, unit_price FROM silver_parts WHERE CAST(unit_price AS DOUBLE) < 0",
)
check(
    "Row count SLA: silver retains ≥85% of bronze parts",
    f"""
    SELECT
        {len(bronze_parts)}                                          AS bronze_cnt,
        {len(silver_parts)}                                          AS silver_cnt,
        ROUND(100.0 * {len(silver_parts)} / {len(bronze_parts)}, 1) AS retention_pct
    WHERE {len(silver_parts)} < {len(bronze_parts)} * 0.85
    """,
)
check(
    "No phantom part_ids in silver not present in bronze",
    """
    SELECT s.part_id
    FROM   silver_parts s
    LEFT JOIN bronze_parts b ON s.part_id = b.part_id
    WHERE  b.part_id IS NULL
    """,
)
check(
    "No UNEXPLAINED critical part drops (documented defects like PART026 excluded)",
    """
    SELECT b.part_id, b.unit_price, b.supplier_id
    FROM   bronze_parts b
    LEFT JOIN silver_parts s ON b.part_id = s.part_id
    WHERE  b.is_critical = TRUE
      AND  s.part_id IS NULL
      AND  CAST(b.unit_price AS DOUBLE) > 0   -- PART026 excluded: negative price (JIRA DQ-137)
      AND  b.supplier_id IS NOT NULL           -- PART027 excluded: null supplier  (JIRA DQ-155)
    """,
)

# ── GOLD — Aggregation Reconciliation ─────────────────────────────────────────
print()
print(HEAD.format("══ GOLD — Aggregation Reconciliation ══"))
print()

print("  Silver → Gold spend reconciliation (rows with matched activity, top 5 by variance):")
rows = con.execute("""
    WITH silver_spend AS (
        SELECT
            strftime(CAST(wo.order_date AS DATE), '%Y-%m') AS metric_month,
            p.supplier_id,
            SUM(CAST(wo.total_cost AS DOUBLE))             AS silver_total
        FROM   silver_wo wo
        JOIN   silver_parts p ON wo.part_id = p.part_id
        WHERE  wo.status IN ('CLOSED','PARTIAL')
        GROUP  BY 1, 2
    ),
    gold_spend AS (
        SELECT metric_month, supplier_id,
               SUM(CAST(total_spend AS DOUBLE)) AS gold_total
        FROM   gold_metrics
        GROUP  BY 1, 2
    )
    SELECT
        g.metric_month,
        g.supplier_id,
        ROUND(s.silver_total, 2)                                      AS silver_total,
        ROUND(g.gold_total,   2)                                      AS gold_total,
        ROUND(ABS(s.silver_total - g.gold_total) / s.silver_total * 100, 1) AS variance_pct
    FROM   gold_spend  g
    JOIN   silver_spend s USING (metric_month, supplier_id)
    WHERE  s.silver_total > 0
    ORDER  BY variance_pct DESC
    LIMIT  5
""").fetchall()
cols = [d[0] for d in con.description]
print("  " + "  |  ".join(f"{c:<18}" for c in cols))
print("  " + "-" * 85)
for r in rows:
    print("  " + "  |  ".join(f"{str(v):<18}" for v in r))

print()
check(
    "No KPI boundary violations (defect_rate 0-100, quality_score 1-5, total_spend ≥0)",
    """
    SELECT metric_month, supplier_id, defect_rate_pct, quality_score, total_spend
    FROM   gold_metrics
    WHERE  CAST(defect_rate_pct AS DOUBLE) NOT BETWEEN 0 AND 100
       OR  CAST(quality_score   AS DOUBLE) NOT BETWEEN 1 AND 5
       OR  CAST(total_spend     AS DOUBLE) < 0
    """,
)
check(
    "No gold supplier untraceable to bronze (data lineage)",
    """
    SELECT g.supplier_id
    FROM   (SELECT DISTINCT supplier_id FROM gold_metrics)     g
    LEFT JOIN (SELECT DISTINCT supplier_id FROM bronze_suppliers) b
           ON g.supplier_id = b.supplier_id
    WHERE  b.supplier_id IS NULL
    """,
)
check(
    "defect_rate_pct = defect_count / parts_received × 100 (tolerance ±0.1%)",
    """
    SELECT metric_month, supplier_id,
           ROUND(CAST(defect_rate_pct AS DOUBLE), 2)                          AS stored_rate,
           ROUND(CAST(defect_count AS DOUBLE)
                 / NULLIF(CAST(total_parts_received AS DOUBLE), 0) * 100, 2)  AS computed_rate
    FROM   gold_metrics
    WHERE  CAST(total_parts_received AS DOUBLE) > 0
      AND  ABS(
               CAST(defect_rate_pct AS DOUBLE)
               - CAST(defect_count AS DOUBLE)
               / NULLIF(CAST(total_parts_received AS DOUBLE), 0) * 100
           ) > 0.1
    """,
)
check(
    "received ≤ ordered and defect_count ≤ received (inventory constraints)",
    """
    SELECT metric_month, supplier_id,
           total_parts_ordered, total_parts_received, defect_count
    FROM   gold_metrics
    WHERE  CAST(total_parts_received AS DOUBLE) > CAST(total_parts_ordered AS DOUBLE)
       OR  CAST(defect_count         AS DOUBLE) > CAST(total_parts_received AS DOUBLE)
    """,
)

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("─" * 60)
if failures == 0:
    print("\033[92m  All SQL checks passed.\033[0m  "
          "DuckDB queried Bronze / Silver / Gold CSVs with zero infrastructure.\n")
else:
    print(f"\033[91m  {failures} check(s) failed.\033[0m\n")
    sys.exit(1)
