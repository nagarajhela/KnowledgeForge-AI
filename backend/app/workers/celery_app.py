from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "knowledgeforge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_default_queue="ingestion",
    beat_schedule={
        "enforce-retention-policies-daily": {
            "task": "app.workers.tasks.enforce_retention_policies_task",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "maintenance"},
        }
    },
)
