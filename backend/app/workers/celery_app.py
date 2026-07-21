"""
Celery app — RabbitMQ as broker (handles the queue of pending document
ingestion jobs), Redis as result backend. Supports concurrent processing of
up to 100 simultaneous PDF uploads by scaling worker replicas
(docker-compose.yml runs N `worker` containers off the same image).
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sentinelai",
    broker=settings.rabbitmq_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,          # re-deliver to another worker if one crashes mid-task
    worker_prefetch_multiplier=1,  # fair dispatch across workers for long-running ingestion jobs
    task_track_started=True,
    result_expires=86400,
    task_routes={
        "app.workers.tasks.ingest_document_task": {"queue": "ingestion"},
    },
)
