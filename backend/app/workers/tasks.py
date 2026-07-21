"""
Celery tasks. Thin wrappers around IngestionPipeline — retry with backoff,
progress tracking via task.update_state, and failure recovery (Celery's
task_acks_late + a bind retry) live here; the actual ingestion logic lives
in services/ingestion/pipeline.py so it stays testable without a broker.
"""
import asyncio

from celery import Task

from app.services.ingestion.pipeline import ingestion_pipeline

from .celery_app import celery_app


class IngestionTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3, "countdown": 10}
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True


@celery_app.task(bind=True, base=IngestionTask, name="app.workers.tasks.ingest_document_task")
def ingest_document_task(self, doc_id: str, doc_version: int, raw_text: str, source_metadata: dict):
    self.update_state(state="PROGRESS", meta={"stage": "chunking"})
    result = asyncio.run(
        ingestion_pipeline.ingest_document(doc_id, doc_version, raw_text, source_metadata)
    )
    return result


@celery_app.task(name="app.workers.tasks.batch_ingest_task")
def batch_ingest_task(documents: list[dict]):
    """Fan-out entrypoint for "upload 100 PDFs at once" — dispatches one
    ingest_document_task per document so they process concurrently across
    however many worker replicas are running."""
    job_ids = []
    for doc in documents:
        async_result = ingest_document_task.delay(
            doc["doc_id"], doc["doc_version"], doc["raw_text"], doc["source_metadata"]
        )
        job_ids.append(async_result.id)
    return {"dispatched": len(job_ids), "job_ids": job_ids}
