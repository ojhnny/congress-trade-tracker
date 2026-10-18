"""Project settings, read once from environment variables.

Every value that differs between your laptop, CI and anyone else who clones
the repo lives here instead of being hard-coded in pipeline code. Airflow
containers get these variables from the .env file through docker-compose.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    # Google Cloud project that owns the BigQuery datasets and the GCS bucket.
    gcp_project_id: str
    # Bucket where raw source files are stored exactly as downloaded.
    gcs_raw_bucket: str
    # Contact string sent as the User-Agent to government sites. SEC EDGAR
    # rejects requests without one, and it is polite for the others.
    http_user_agent: str
    # BigQuery location. Every dataset in one query must share a location.
    bq_location: str = "US"
    # Dataset that receives parsed rows before dbt touches them.
    bq_raw_dataset: str = "raw"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from environment variables, listing every missing one at once."""
        env = os.environ if env is None else env

        required = {
            "gcp_project_id": "GCP_PROJECT_ID",
            "gcs_raw_bucket": "GCS_RAW_BUCKET",
            "http_user_agent": "HTTP_USER_AGENT",
        }
        optional = {
            "bq_location": "BQ_LOCATION",
            "bq_raw_dataset": "BQ_RAW_DATASET",
        }

        missing = [var for var in required.values() if not env.get(var, "").strip()]
        if missing:
            raise ConfigError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )

        values = {field: env[var].strip() for field, var in required.items()}
        values.update(
            {field: env[var].strip() for field, var in optional.items() if env.get(var, "").strip()}
        )

        if "@" not in values["http_user_agent"]:
            raise ConfigError(
                "HTTP_USER_AGENT must include a contact email, e.g. "
                "'congress-trades research you@example.com'."
            )

        return cls(**values)
