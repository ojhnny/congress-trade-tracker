# credentials/

Put your Google Cloud service account key here as `gcp-service-account.json`.
Everything in this folder except this README is gitignored, and docker-compose
mounts it read-only into the Airflow containers.

The setup steps for creating the service account are in `docs/design-report.md`
under "Google Cloud setup".
