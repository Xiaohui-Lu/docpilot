"""A small, durable job queue on top of the primary database.

- Jobs survive restarts (they live in the ``jobs`` table).
- Workers claim jobs with an atomic compare-and-set UPDATE, so several worker replicas can run safely.
- Failures are retried with exponential backoff; permanent failures stop immediately.
- Jobs whose worker died mid-run are re-queued after ``job_lock_timeout_seconds``.
"""

import logging
import os
import socket
import threading
import time
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document, Job, Organization, utcnow
from app.observability import JOB_DURATION, JOB_QUEUE_DEPTH, JOBS_PROCESSED, log_extra
from app.services.llm.base import LLMError
from app.services.notifications import schedule_digests, send_digest
from app.services.pipeline import PermanentError, process_document

log = logging.getLogger(__name__)
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


def enqueue_document(db: Session, doc: Document) -> Job:
    job = Job(
        org_id=doc.org_id,
        document_id=doc.id,
        kind="process_document",
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    return job


def backoff_seconds(attempt: int) -> float:
    """2s, 4s, 8s, 16s ... capped at 5 minutes."""
    return float(min(2**attempt, 300))


def _claim_next(db: Session) -> Job | None:
    now = utcnow()
    candidates = db.scalars(
        select(Job.id).where(Job.status == "queued", Job.run_after <= now).order_by(Job.created_at).limit(5)
    ).all()
    for job_id in candidates:
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", locked_by=WORKER_ID, locked_at=now, attempts=Job.attempts + 1)
        ).rowcount
        db.commit()
        if claimed == 1:
            return db.get(Job, job_id)
    return None


def requeue_stale(db: Session) -> int:
    cutoff = utcnow() - timedelta(seconds=get_settings().job_lock_timeout_seconds)
    count = db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < cutoff)
        .values(status="queued", locked_by=None, last_error="Worker lock expired; re-queued")
    ).rowcount
    db.commit()
    return count


def _finish(db: Session, job: Job, *, ok: bool, error: str | None = None, retry: bool = False) -> None:
    job.locked_by = None
    job.last_error = error
    doc = db.get(Document, job.document_id) if job.document_id else None
    if ok:
        job.status = "succeeded"
        job.finished_at = utcnow()
    elif retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = utcnow() + timedelta(seconds=backoff_seconds(job.attempts))
        if doc:
            doc.status = "queued"
            doc.error = f"Attempt {job.attempts} failed, retrying: {error}"
    else:
        job.status = "failed"
        job.finished_at = utcnow()
        if doc:
            doc.status = "failed"
            doc.error = error
    db.commit()


def _execute(db: Session, job: Job) -> None:
    if job.kind == "process_document":
        process_document(db, job.document_id)
    elif job.kind == "send_digest":
        org = db.get(Organization, job.org_id)
        if org is None:
            raise PermanentError("Organization no longer exists")
        # Another worker may have sent it already (e.g. a duplicate schedule): don't email twice.
        if org.digest_last_sent_at and org.digest_last_sent_at > utcnow() - timedelta(hours=1):
            return
        send_digest(db, org, raise_on_error=True)
    else:
        raise PermanentError(f"Unknown job kind {job.kind!r}")


def run_one(db: Session) -> bool:
    """Claim and run a single job. Returns False when the queue is empty."""
    job = _claim_next(db)
    if job is None:
        return False
    started = time.perf_counter()
    try:
        _execute(db, job)
        db.refresh(job)
        _finish(db, job, ok=True)
        outcome = "succeeded"
    except PermanentError as exc:
        db.rollback()
        _finish(db, job, ok=False, error=str(exc))
        outcome = "failed"
    except LLMError as exc:  # retryable LLM failures (rate limits, 5xx, timeouts)
        db.rollback()
        _finish(db, job, ok=False, error=str(exc), retry=True)
        outcome = "retried" if job.status == "queued" else "failed"
    except Exception as exc:  # unexpected bug or infra hiccup: retry, then give up
        db.rollback()
        log.exception("job crashed", extra=log_extra(job_id=job.id))
        _finish(db, job, ok=False, error=f"{type(exc).__name__}: {exc}", retry=True)
        outcome = "retried" if job.status == "queued" else "failed"
    JOBS_PROCESSED.labels(job.kind, outcome).inc()
    JOB_DURATION.labels(job.kind).observe(time.perf_counter() - started)
    log.info("job finished", extra=log_extra(job_id=job.id, outcome=outcome, attempts=job.attempts))
    return True


def queue_depth(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")) or 0


def drain(max_jobs: int = 1000) -> int:
    """Run queued jobs until the queue is empty (used by tests and the seed script)."""
    done = 0
    with SessionLocal() as db:
        while done < max_jobs and run_one(db):
            done += 1
    return done


class Worker:
    def __init__(self, poll_seconds: float | None = None):
        self.poll = poll_seconds or get_settings().worker_poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_forever(self) -> None:
        log.info("worker started", extra=log_extra(worker=WORKER_ID))
        last_maintenance = last_schedule = 0.0
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    if time.monotonic() - last_maintenance > 30:
                        requeue_stale(db)
                        JOB_QUEUE_DEPTH.set(queue_depth(db))
                        last_maintenance = time.monotonic()
                    if time.monotonic() - last_schedule > get_settings().digest_check_seconds:
                        schedule_digests(db)
                        last_schedule = time.monotonic()
                    worked = run_one(db)
                    if worked:
                        JOB_QUEUE_DEPTH.set(queue_depth(db))
            except Exception:
                log.exception("worker loop error")
                worked = False
            if not worked:
                self._stop.wait(self.poll)
        log.info("worker stopped")

    def start_background(self) -> None:
        self._thread = threading.Thread(target=self.run_forever, name="docpilot-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
