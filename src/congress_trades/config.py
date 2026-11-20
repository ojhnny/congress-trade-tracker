"""Project settings, read once from environment variables.

Every value that differs between your laptop, CI and anyone else who clones
the repo lives here instead of being hard-coded in pipeline code. Airflow
containers get these variables from the .env file through docker-compose.

Two storage backends share the same code:

- ``local`` (default): raw files land under ``DATA_DIR/landing`` and the
  warehouse is a DuckDB file. Needs no cloud account, so anyone can clone
  the repo and build the dashboard from real data.
- ``gcp``: raw files land in a GCS bucket and the warehouse is BigQuery.
  This is the production target described in the design report.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BACKENDS = ("local", "gcp")


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    # Contact string sent as the User-Agent to government sites. SEC EDGAR
    # rejects requests without one, and it is polite for the others.
    http_user_agent: str
    # Where raw files and the warehouse live: "local" or "gcp".
    storage_backend: str = "local"
    # Google Cloud project that owns the BigQuery datasets and the GCS bucket.
    gcp_project_id: str = ""
    # Bucket where raw source files are stored exactly as downloaded.
    gcs_raw_bucket: str = ""
    # BigQuery location. Every dataset in one query must share a location.
    bq_location: str = "US"
    # Dataset that receives parsed rows before dbt touches them.
    bq_raw_dataset: str = "raw"
    # Local backend: root folder for landed files and the DuckDB warehouse.
    data_dir: str = "data"
    # First trade date the project covers.
    coverage_start: str = "2024-01-01"
    # Seconds to wait between requests to the same site.
    request_delay: float = 0.5

    @property
    def is_local(self) -> bool:
        return self.storage_backend == "local"

    @property
    def duckdb_path(self) -> Path:
        return Path(self.data_dir) / "warehouse.duckdb"

    @property
    def coverage_start_date(self) -> date:
        return date.fromisoformat(self.coverage_start)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from environment variables, listing every missing one at once."""
        env = os.environ if env is None else env

        def get(var: str) -> str:
            return env.get(var, "").strip()

        backend = get("STORAGE_BACKEND") or "local"
        if backend not in BACKENDS:
            choices = ", ".join(BACKENDS)
            raise ConfigError(f"STORAGE_BACKEND must be one of {choices}, not {backend!r}.")

        required = {"http_user_agent": "HTTP_USER_AGENT"}
        if backend == "gcp":
            required |= {"gcp_project_id": "GCP_PROJECT_ID", "gcs_raw_bucket": "GCS_RAW_BUCKET"}
        optional = {
            "gcp_project_id": "GCP_PROJECT_ID",
            "gcs_raw_bucket": "GCS_RAW_BUCKET",
            "bq_location": "BQ_LOCATION",
            "bq_raw_dataset": "BQ_RAW_DATASET",
            "data_dir": "DATA_DIR",
            "coverage_start": "COVERAGE_START",
            "request_delay": "REQUEST_DELAY",
        }

        missing = [var for var in required.values() if not get(var)]
        if missing:
            raise ConfigError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )

        values: dict = {"storage_backend": backend}
        values.update({field: get(var) for field, var in required.items()})
        values.update({field: get(var) for field, var in optional.items() if get(var)})

        if "@" not in values["http_user_agent"]:
            raise ConfigError(
                "HTTP_USER_AGENT must include a contact email, e.g. "
                "'congress-trades research you@example.com'."
            )
        try:
            date.fromisoformat(values.get("coverage_start", cls.coverage_start))
        except ValueError as err:
            raise ConfigError("COVERAGE_START must be a date like 2024-01-01.") from err
        if "request_delay" in values:
            try:
                values["request_delay"] = float(values["request_delay"])
            except ValueError as err:
                raise ConfigError("REQUEST_DELAY must be a number of seconds.") from err

        return cls(**values)
