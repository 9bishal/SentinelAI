from pydantic import BaseModel


class DocumentIngestRequest(BaseModel):
    doc_id: str
    doc_version: int = 1
    raw_text: str
    source_metadata: dict = {}


class DocumentIngestResponse(BaseModel):
    doc_id: str
    status: str
    task_id: str | None = None
