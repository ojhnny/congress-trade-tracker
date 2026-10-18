# Airflow image for the congress-trades pipeline.
#
# Two Python environments live in this image on purpose:
#   1. Airflow's own environment, which also gets our `congress_trades`
#      package, installed against Airflow's official constraint file so
#      nothing we add can silently upgrade a library Airflow depends on.
#   2. A separate virtualenv at /opt/dbt-venv for dbt. dbt and Airflow pin
#      overlapping libraries differently, and keeping them apart is the
#      approach both projects recommend.
FROM apache/airflow:3.3.2-python3.12

ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12
ARG CONSTRAINTS_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir "dbt-core~=1.12.0" "dbt-bigquery~=1.12.0" \
    && chown -R airflow:root /opt/dbt-venv \
    && mkdir -p /opt/project && chown airflow:root /opt/project
ENV PATH="${PATH}:/opt/dbt-venv/bin"

USER airflow
COPY --chown=airflow:root pyproject.toml README.md /opt/project/
COPY --chown=airflow:root src /opt/project/src
# Editable install: docker-compose mounts ./src over /opt/project/src, so code
# edits on your machine show up in Airflow without rebuilding the image.
RUN pip install --no-cache-dir --constraint "${CONSTRAINTS_URL}" -e /opt/project
