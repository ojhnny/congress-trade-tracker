# Does Congress trade what it regulates?

A data pipeline that joins congressional stock trade disclosures to the
committees each member sits on, then asks whether members trade more in the
industries their committees oversee. It also audits STOCK Act filing
deadlines and looks closely at the Michigan delegation.

The findings describe patterns in public disclosures. They are not
accusations of wrongdoing.

**Stack:** Python, Airflow (local, Docker), Google Cloud Storage, BigQuery,
dbt, GitHub Actions, Power BI.

> Work in progress. See [docs/design-report.md](docs/design-report.md) for
> how and why it is built the way it is.

## Run it locally

```bash
cp .env.example .env          # then fill in the blanks
make setup && make test       # local virtualenv and unit tests
make up                       # build and start Airflow at http://localhost:8080
make smoke                    # trigger the setup check DAG

# dashboard (sample data for now)
python -m http.server 8000 -d frontend   # open http://localhost:8000
```

## Layout

```
dags/          Airflow DAGs (orchestration only, no business logic)
src/           the congress_trades Python package (extract, parse, load)
tests/         unit tests for src/
docker/        the Airflow image
credentials/   your GCP service account key (gitignored)
frontend/      public dashboard (static site, reads data/dashboard.json)
docs/          design report
```
