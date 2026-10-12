from datetime import timedelta

import pytest
from sqlalchemy import update

from app.db import SessionLocal
from app.models import Document, Job, utcnow
from app.services import jobs
from app.services.llm import get_provider
from app.services.llm.base import LLMError
from tests.conftest import auth_headers, register, upload


def _make_due():
    with SessionLocal() as db:
        db.execute(update(Job).values(run_after=utcnow() - timedelta(seconds=1)))
        db.commit()


def _job_for(doc_id: str) -> Job:
    with SessionLocal() as db:
        return db.query(Job).filter(Job.document_id == doc_id).one()


@pytest.fixture
def flaky_provider(monkeypatch):
    provider = get_provider()
    real = provider.extract
    calls = {"n": 0, "fail_times": 1, "retryable": True}

    def extract(text, filename, policies=()):
        calls["n"] += 1
        if calls["n"] <= calls["fail_times"]:
            raise LLMError("simulated 529 overloaded", retryable=calls["retryable"])
        return real(text, filename, policies)

    monkeypatch.setattr(provider, "extract", extract)
    return calls


def test_backoff_schedule():
    assert [jobs.backoff_seconds(n) for n in (1, 2, 3, 4)] == [2, 4, 8, 16]
    assert jobs.backoff_seconds(20) == 300


def test_retryable_error_is_retried_with_backoff(client, flaky_provider):
    h = auth_headers(register(client))
    doc = upload(client, h, "01")

    assert jobs.drain() == 1  # first attempt fails and is re-queued in the future
    job = _job_for(doc["id"])
    assert job.status == "queued" and job.attempts == 1
    assert job.run_after > utcnow()
    assert "simulated 529" in job.last_error
    assert client.get(f"/api/documents/{doc['id']}", headers=h).json()["status"] == "queued"

    assert jobs.drain() == 0  # not due yet
    _make_due()
    assert jobs.drain() == 1
    job = _job_for(doc["id"])
    assert job.status == "succeeded" and job.attempts == 2
    assert client.get(f"/api/documents/{doc['id']}", headers=h).json()["status"] == "ready"


def test_permanent_error_fails_fast(client, flaky_provider):
    flaky_provider["retryable"] = False
    h = auth_headers(register(client))
    doc = upload(client, h, "01")
    jobs.drain()
    job = _job_for(doc["id"])
    assert job.status == "failed" and job.attempts == 1
    detail = client.get(f"/api/documents/{doc['id']}", headers=h).json()
    assert detail["status"] == "failed" and "simulated" in detail["error"]


def test_gives_up_after_max_attempts(client, flaky_provider):
    flaky_provider["fail_times"] = 99
    h = auth_headers(register(client))
    doc = upload(client, h, "01")
    for _ in range(10):
        _make_due()
        if not jobs.drain():
            break
    job = _job_for(doc["id"])
    assert job.status == "failed"
    assert job.attempts == job.max_attempts == 4


def test_unreadable_file_is_permanent_failure(client):
    h = auth_headers(register(client))
    r = client.post("/api/documents", headers=h, files={"file": ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    jobs.drain()
    detail = client.get(f"/api/documents/{r.json()['id']}", headers=h).json()
    assert detail["status"] == "failed"
    assert "PDF" in detail["error"]


def test_stale_running_jobs_are_requeued(client):
    h = auth_headers(register(client))
    doc = upload(client, h, "02")
    with SessionLocal() as db:
        db.execute(
            update(Job).values(status="running", locked_by="dead-worker", locked_at=utcnow() - timedelta(hours=1))
        )
        db.commit()
        assert jobs.requeue_stale(db) == 1
    assert jobs.drain() == 1
    with SessionLocal() as db:
        assert db.get(Document, doc["id"]).status == "ready"


def test_claim_is_exclusive(client):
    h = auth_headers(register(client))
    upload(client, h, "02")
    with SessionLocal() as a, SessionLocal() as b:
        first = jobs._claim_next(a)
        second = jobs._claim_next(b)
    assert first is not None and second is None
