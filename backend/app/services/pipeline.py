"""Document processing pipeline: parse -> chunk -> extract (LLM) -> validate & ground -> persist."""

import logging
import time

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document, utcnow
from app.observability import LLM_COST, LLM_LATENCY, LLM_REQUESTS, LLM_TOKENS, log_extra
from app.services.grounding import check_grounding
from app.services.llm import get_provider
from app.services.llm.base import LLMError
from app.services.parsing import UnsupportedDocument, chunk_text, parse_document
from app.services.rules import ai_policies, apply_to_document, enabled_rules

log = logging.getLogger(__name__)


class PermanentError(Exception):
    """Processing failed in a way retrying will not fix."""


def process_document(db: Session, document_id: str) -> None:
    settings = get_settings()
    doc = db.get(Document, document_id)
    if doc is None:
        raise PermanentError(f"Document {document_id} no longer exists")

    started = time.perf_counter()
    doc.status = "processing"
    doc.error = None
    db.commit()

    try:
        parsed = parse_document(doc.raw, doc.content_type)
    except UnsupportedDocument as exc:
        raise PermanentError(str(exc)) from exc

    chunks = chunk_text(parsed, settings.chunk_size_chars, settings.chunk_overlap_chars)

    provider = get_provider()
    rules = enabled_rules(db, doc.org_id)
    llm_started = time.perf_counter()
    try:
        # Plain-English company rules are evaluated by the model in the same call.
        extraction = provider.extract(parsed.text, doc.filename, ai_policies(rules))
    except LLMError as exc:
        LLM_REQUESTS.labels(provider.name, "extract", "error").inc()
        if exc.retryable:
            raise
        raise PermanentError(str(exc)) from exc
    LLM_LATENCY.labels(provider.name, "extract").observe(time.perf_counter() - llm_started)
    LLM_REQUESTS.labels(provider.name, "extract", "ok").inc()

    insights = extraction.insights
    usage = extraction.usage
    LLM_TOKENS.labels(provider.name, "input").inc(usage.input_tokens)
    LLM_TOKENS.labels(provider.name, "output").inc(usage.output_tokens)
    LLM_COST.labels(provider.name).inc(usage.cost_usd)

    # Replace any chunks from a previous attempt (idempotent re-processing).
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    for c in chunks:
        db.add(
            Chunk(
                document_id=doc.id,
                org_id=doc.org_id,
                idx=c.idx,
                text=c.text,
                start_char=c.start_char,
                end_char=c.end_char,
                page=c.page,
            )
        )

    doc.text = parsed.text
    doc.page_count = parsed.page_count
    doc.title = insights.title or doc.filename
    doc.doc_type = insights.doc_type
    doc.overall_risk = insights.overall_risk
    doc.insights = insights.model_dump()
    doc.grounding = check_grounding(insights, parsed.text)
    doc.llm_provider = provider.name
    doc.llm_model = usage.model
    apply_to_document(doc, rules, parsed.text)
    doc.input_tokens += usage.input_tokens
    doc.output_tokens += usage.output_tokens
    doc.cost_usd = round(doc.cost_usd + usage.cost_usd, 6)
    doc.status = "ready"
    doc.processed_at = utcnow()
    doc.processing_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    log.info(
        "document processed",
        extra=log_extra(
            document_id=doc.id,
            chunks=len(chunks),
            risks=len(insights.risks),
            policy_violations=doc.policy_violations,
            grounding=doc.grounding["score"],
            ms=doc.processing_ms,
        ),
    )
