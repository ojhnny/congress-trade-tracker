"""A throwaway DAG that proves the local Airflow setup works end to end.

It checks the three things every real DAG will rely on: our package imports
inside Airflow, the .env settings reach the containers, and dbt is installed
in its own virtualenv. Delete it once the first real DAG exists.
"""

import pendulum
from airflow.sdk import dag, task


@dag(
    schedule=None,  # only runs when triggered by hand
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["setup"],
)
def smoke_test():
    @task
    def check_settings() -> str:
        from congress_trades.config import Settings

        settings = Settings.from_env()
        print(f"GCP project: {settings.gcp_project_id}")
        print(f"Raw bucket:  {settings.gcs_raw_bucket}")
        print(f"BigQuery:    {settings.bq_location} / {settings.bq_raw_dataset}")
        return settings.gcp_project_id

    @task.bash
    def check_dbt() -> str:
        return "/opt/dbt-venv/bin/dbt --version"

    check_settings() >> check_dbt()


smoke_test()
