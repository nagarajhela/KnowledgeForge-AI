import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks import ingest_document_task


def test_celery_ingest_task_retries_on_failure() -> None:
    org_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    with patch("app.workers.tasks._run_ingestion", side_effect=RuntimeError("Transient S3 error")):
        with pytest.raises(RuntimeError):
            ingest_document_task.apply(args=(org_id, doc_id, job_id), throw=True)


def test_celery_ingest_task_succeeds() -> None:
    org_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    with patch(
        "app.workers.tasks._run_ingestion",
        new=AsyncMock(return_value={"document_id": doc_id, "status": "completed"}),
    ):
        result = ingest_document_task.apply(args=(org_id, doc_id, job_id)).get()
        assert result["status"] == "completed"
        assert result["document_id"] == doc_id
