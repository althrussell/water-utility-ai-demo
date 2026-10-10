"""Job task 1: generate the synthetic Seqwater dataset and publish it to Unity Catalog.

Runs on serverless. Regenerates all history relative to today (Brisbane) so the demo is
always current, documents every table and column, and declares primary/foreign keys.
Agent write-backs (agent_actions) are preserved and merged into work_orders.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ if "__file__" in globals() else sys.argv[0])))

import pandas as pd  # noqa: E402
from pyspark.sql import SparkSession, functions as F  # noqa: E402
from pyspark.sql.types import DoubleType, FloatType  # noqa: E402

import seqwater_synth  # noqa: E402
from catalog_docs import TABLES  # noqa: E402


def _sql_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _to_spark(spark, pdf: pd.DataFrame, columns: dict):
    pdf = pdf.copy()
    for c in pdf.columns:
        if pdf[c].dtype == object:
            pdf[c] = pdf[c].astype(object).where(pd.notna(pdf[c]), None)
    df = spark.createDataFrame(pdf)
    for f in df.schema.fields:
        if isinstance(f.dataType, (DoubleType, FloatType)):
            df = df.withColumn(f.name, F.when(F.isnan(F.col(f.name)), None).otherwise(F.col(f.name)))
    for c, comment in columns.items():
        if c in df.columns:
            df = df.withMetadata(c, {"comment": comment})
    return df


def _try(spark, stmt: str) -> None:
    try:
        spark.sql(stmt)
    except Exception as e:  # constraints are informational; never fail the build on them
        print(f"WARN: {stmt[:120]}... -> {str(e).splitlines()[0][:200]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--seed", type=int, default=20261010)
    args = ap.parse_args()

    spark = SparkSession.builder.getOrCreate()
    fq = f"`{args.catalog}`.`{args.schema}`"
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {fq} COMMENT 'Seqwater AI demo - synthetic operating data (Databricks)'")

    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {fq}.agent_actions (
          action_id STRING, created_at TIMESTAMP, action_type STRING, status STRING, site_id STRING,
          asset_id STRING, incident_id STRING, priority STRING, title STRING, details STRING,
          requested_by STRING, reference_id STRING)
        COMMENT '{_sql_str(TABLES["agent_actions"]["comment"])}'
    """)
    for c, comment in TABLES["agent_actions"]["columns"].items():
        _try(spark, f"ALTER TABLE {fq}.agent_actions ALTER COLUMN {c} COMMENT '{_sql_str(comment)}'")

    tables = seqwater_synth.build(seed=args.seed)
    print(f"Generated {len(tables)} tables, data through {tables['demo_metadata'].data_through_date.iloc[0]}")

    # Foreign keys reference primary keys, so drop FKs before tables are replaced.
    existing = {r.tableName for r in spark.sql(f"SHOW TABLES IN {fq}").collect()}
    for name, meta in TABLES.items():
        if name in existing:
            for col in meta.get("fk", {}):
                _try(spark, f"ALTER TABLE {fq}.{name} DROP CONSTRAINT IF EXISTS fk_{name}_{col}")

    for name, pdf in tables.items():
        meta = TABLES[name]
        if name == "work_orders":
            agent_wo = spark.sql(f"""
                SELECT reference_id AS work_order_id, asset_id, site_id, 'Corrective' AS work_type, priority,
                       'Open' AS status, CAST(created_at AS DATE) AS raised_date,
                       date_add(CAST(created_at AS DATE), CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 7 ELSE 28 END) AS due_date,
                       title AS description
                FROM {fq}.agent_actions WHERE action_type = 'WORK_ORDER' AND reference_id IS NOT NULL
            """).toPandas()
            if len(agent_wo):
                agent_wo["completed_date"] = None
                agent_wo["labour_hours"] = None
                agent_wo["cost_aud"] = None
                agent_wo["source_system"] = "Seqwater Operations Agent"
                pdf = pd.concat([pdf, agent_wo[pdf.columns]], ignore_index=True)
        if name == "reservoir_offtakes":
            chosen = spark.sql(f"""
                SELECT replace(asset_id, 'BPD-OFFTAKE-', '') AS level FROM {fq}.agent_actions
                WHERE action_type = 'OFFTAKE_CHANGE' ORDER BY created_at DESC LIMIT 1""").collect()
            if chosen:
                pdf = pdf.assign(in_service=pdf.offtake_level == chosen[0].level)
        df = _to_spark(spark, pdf, meta["columns"])
        (df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{fq}.{name}"))
        spark.sql(f"COMMENT ON TABLE {fq}.{name} IS '{_sql_str(meta['comment'])}'")
        print(f"  wrote {name:28s} {len(pdf):>8,d} rows")

    for name, meta in TABLES.items():
        if pk := meta.get("pk"):
            _try(spark, f"ALTER TABLE {fq}.{name} ALTER COLUMN {pk} SET NOT NULL")
            _try(spark, f"ALTER TABLE {fq}.{name} DROP CONSTRAINT IF EXISTS pk_{name}")
            _try(spark, f"ALTER TABLE {fq}.{name} ADD CONSTRAINT pk_{name} PRIMARY KEY ({pk})")
    for name, meta in TABLES.items():
        for col, ref in meta.get("fk", {}).items():
            _try(spark, f"ALTER TABLE {fq}.{name} ADD CONSTRAINT fk_{name}_{col} FOREIGN KEY ({col}) "
                        f"REFERENCES {fq}.{ref} ({TABLES[ref]['pk']})")

    for name in tables:
        _try(spark, f"ALTER TABLE {fq}.{name} SET TAGS ('demo' = 'seqwater-ai-demo', 'data_classification' = 'synthetic')")
    print("Foundation complete.")


if __name__ == "__main__":
    main()
