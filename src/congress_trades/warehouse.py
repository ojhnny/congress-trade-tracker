"""Load raw rows into the warehouse and read marts back out.

- local backend: a DuckDB file at ``DATA_DIR/warehouse.duckdb``, schema ``raw``.
- gcp backend: BigQuery dataset ``BQ_RAW_DATASET``. Rows are written to the
  bucket as newline-delimited JSON first and loaded from there, which is
  free in BigQuery and leaves a copy of exactly what was loaded.

Every load replaces the table (WRITE_TRUNCATE), so loads are idempotent.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from congress_trades.config import Settings
from congress_trades.raw import SCHEMAS

log = logging.getLogger(__name__)

DUCK_TYPES = {
    "STRING": "VARCHAR",
    "INT64": "BIGINT",
    "FLOAT64": "DOUBLE",
    "BOOL": "BOOLEAN",
    "TIMESTAMP": "TIMESTAMP",
}


def _ndjson(name: str, rows: list[dict], loaded_at: str) -> bytes:
    cols = [c for c, _ in SCHEMAS[name]]
    lines = (json.dumps({c: r.get(c) for c in cols} | {"_loaded_at": loaded_at}) for r in rows)
    return ("\n".join(lines) + "\n").encode() if rows else b""


def load_tables(settings: Settings, tables: dict[str, list[dict]]) -> dict[str, int]:
    loaded_at = datetime.now(UTC).isoformat(timespec="seconds")
    if settings.is_local:
        return _load_duckdb(settings, tables, loaded_at)
    return _load_bigquery(settings, tables, loaded_at)


def _load_duckdb(
    settings: Settings, tables: dict[str, list[dict]], loaded_at: str
) -> dict[str, int]:
    import duckdb

    raw_dir = Path(settings.data_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute("create schema if not exists raw")
        for name, rows in tables.items():
            path = raw_dir / f"{name}.jsonl"
            path.write_bytes(_ndjson(name, rows, loaded_at))
            cols = SCHEMAS[name] + [("_loaded_at", "TIMESTAMP")]
            col_sql = ", ".join(f'"{c}" {DUCK_TYPES[t]}' for c, t in cols)
            con.execute(f"create or replace table raw.{name} ({col_sql})")
            if rows:
                spec = "{" + ", ".join(f"'{c}': '{DUCK_TYPES[t]}'" for c, t in cols) + "}"
                con.execute(
                    f"insert into raw.{name} select * from read_json(?, "
                    "format='newline_delimited', "
                    f"columns={spec})",
                    [str(path)],
                )
            counts[name] = con.execute(f"select count(*) from raw.{name}").fetchone()[0]
    log.info("loaded raw tables into %s: %s", settings.duckdb_path, counts)
    return counts


def _load_bigquery(
    settings: Settings, tables: dict[str, list[dict]], loaded_at: str
) -> dict[str, int]:
    from google.cloud import bigquery

    from congress_trades.storage import GCSStore

    client = bigquery.Client(project=settings.gcp_project_id, location=settings.bq_location)
    dataset = bigquery.Dataset(f"{settings.gcp_project_id}.{settings.bq_raw_dataset}")
    dataset.location = settings.bq_location
    client.create_dataset(dataset, exists_ok=True)
    store = GCSStore(settings.gcs_raw_bucket, settings.gcp_project_id)
    run = loaded_at[:10]
    counts = {}
    for name, rows in tables.items():
        key = f"loads/{run}/{name}.jsonl"
        store.write(key, _ndjson(name, rows, loaded_at), "application/x-ndjson")
        schema = [bigquery.SchemaField(c, t) for c, t in SCHEMAS[name]]
        schema.append(bigquery.SchemaField("_loaded_at", "TIMESTAMP"))
        job = client.load_table_from_uri(
            store.uri(key),
            f"{settings.gcp_project_id}.{settings.bq_raw_dataset}.{name}",
            job_config=bigquery.LoadJobConfig(
                schema=schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            ),
        )
        job.result()
        counts[name] = len(rows)
    log.info("loaded raw tables into BigQuery: %s", counts)
    return counts


def query(settings: Settings, sql: str) -> list[dict]:
    """Run a read-only query against the marts and return rows as dicts.

    `sql` may reference `{marts}` and `{analysis}`, which resolve to the
    right schema or dataset for the backend.
    """
    if settings.is_local:
        import duckdb

        sql = sql.format(marts="main_marts", analysis="main_analysis")
        with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    from google.cloud import bigquery

    client = bigquery.Client(project=settings.gcp_project_id, location=settings.bq_location)
    sql = sql.format(
        marts=f"`{settings.gcp_project_id}.marts`", analysis=f"`{settings.gcp_project_id}.analysis`"
    )
    return [dict(row.items()) for row in client.query(sql).result()]
