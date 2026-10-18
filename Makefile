.PHONY: help setup test lint up down logs smoke

help:
	@echo "setup  create a local virtualenv with dev tools"
	@echo "test   run unit tests"
	@echo "lint   run ruff"
	@echo "up     build and start local Airflow (http://localhost:8080)"
	@echo "down   stop Airflow (keeps the metadata database)"
	@echo "smoke  trigger the smoke_test DAG"

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check src tests dags

up:
	@test -f .env || (echo "Missing .env. Run: cp .env.example .env" && exit 1)
	mkdir -p logs
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f airflow-scheduler

smoke:
	docker compose exec airflow-scheduler airflow dags unpause smoke_test
	docker compose exec airflow-scheduler airflow dags trigger smoke_test
