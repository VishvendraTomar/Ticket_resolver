"""Celery application (ADR-0007). Run a worker with:

cd backend && uv run celery -A workers.celery_app worker -Q ingestion -c 2 --loglevel INFO
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("ticket_resolver", broker=settings.celery_broker_url, include=["workers.tasks"])
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="ingestion",
    task_routes={"ingestion.*": {"queue": "ingestion"}, "maintenance.*": {"queue": "maintenance"}},
    # Above the longest task, or Redis redelivers a task that is still running.
    broker_transport_options={"visibility_timeout": settings.parse_timeout_seconds + 900},
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
