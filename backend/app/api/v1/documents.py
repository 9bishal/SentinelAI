# pyrefly: ignore [missing-import]
from fastapi import APIRouter

# pyrefly: ignore [missing-import]
from app.schemas.document import DocumentIngestRequest, DocumentIngestResponse
# pyrefly: ignore [missing-import]
from app.workers.tasks import ingest_document_task

router = APIRouter()


@router.post("/ingest", response_model=DocumentIngestResponse)
async def ingest_document(body: DocumentIngestRequest) -> DocumentIngestResponse:
    """Enqueues ingestion on Celery/RabbitMQ rather than processing inline —
    keeps the API responsive for the "100 PDFs at once" bulk-upload case."""
    async_result = ingest_document_task.delay(
        body.doc_id, body.doc_version, body.raw_text, body.source_metadata
    )
    return DocumentIngestResponse(doc_id=body.doc_id, status="queued", task_id=async_result.id)


@router.get("/ingest/{task_id}/status")
async def ingestion_status(task_id: str):
    from app.workers.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    return {"task_id": task_id, "state": result.state, "info": result.info}
