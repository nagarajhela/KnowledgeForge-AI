.PHONY: dev worker test lint migrate revision up down logs

dev:
	cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd backend && celery -A app.workers.celery_app:celery_app worker --loglevel=info -Q ingestion,maintenance

test:
	cd backend && pytest -v --cov=app --cov-report=term-missing

lint:
	cd backend && ruff check app && mypy app

migrate:
	cd backend && alembic upgrade head

revision:
	cd backend && alembic revision --autogenerate -m "$(message)"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker
