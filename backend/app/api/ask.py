import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Document, Question, User
from app.observability import LLM_COST, LLM_LATENCY, LLM_REQUESTS, LLM_TOKENS
from app.schemas import AskIn, AskOut, Citation
from app.security import get_current_user
from app.services import audit
from app.services.llm import get_provider
from app.services.llm.base import LLMError, Source
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/api/ask", tags=["ask"])


@router.post("", response_model=AskOut)
def ask(body: AskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AskOut:
    """Retrieval-augmented Q&A over the organization's documents, with citations."""
    if body.document_id:
        owned = db.scalar(select(Document.id).where(Document.id == body.document_id, Document.org_id == user.org_id))
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    started = time.perf_counter()
    hits = search_chunks(
        db, user.org_id, body.question, top_k=get_settings().retrieval_top_k, document_id=body.document_id
    )
    sources = [
        Source(
            ref=i + 1,
            document_id=h.chunk.document_id,
            document_title=h.document_title,
            chunk_id=h.chunk.id,
            chunk_index=h.chunk.idx,
            text=h.chunk.text,
        )
        for i, h in enumerate(hits)
    ]
    provider = get_provider()
    try:
        result = provider.answer(body.question, sources)
    except LLMError as exc:
        LLM_REQUESTS.labels(provider.name, "answer", "error").inc()
        code = status.HTTP_503_SERVICE_UNAVAILABLE if exc.retryable else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, str(exc)) from exc
    latency = time.perf_counter() - started
    LLM_REQUESTS.labels(provider.name, "answer", "ok").inc()
    LLM_LATENCY.labels(provider.name, "answer").observe(latency)

    by_ref = {s.ref: s for s in sources}
    citations: list[Citation] = []
    seen: set[tuple[int, str]] = set()
    for ref, quote in result.citations:
        src = by_ref.get(ref)
        if src is None or (ref, quote) in seen:
            continue
        seen.add((ref, quote))
        citations.append(
            Citation(
                document_id=src.document_id,
                document_title=src.document_title,
                chunk_id=src.chunk_id,
                chunk_index=src.chunk_index,
                quote=quote[:600],
            )
        )

    usage = result.usage
    in_tok, out_tok, cost = (usage.input_tokens, usage.output_tokens, usage.cost_usd) if usage else (0, 0, 0.0)
    LLM_TOKENS.labels(provider.name, "input").inc(in_tok)
    LLM_TOKENS.labels(provider.name, "output").inc(out_tok)
    LLM_COST.labels(provider.name).inc(cost)

    q = Question(
        org_id=user.org_id,
        user_id=user.id,
        document_id=body.document_id,
        question=body.question,
        answer=result.answer,
        citations=[c.model_dump() for c in citations],
        llm_provider=provider.name,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        latency_ms=int(latency * 1000),
    )
    db.add(q)
    audit.record(db, user, "question.asked", body.question[:120], document_id=body.document_id)
    db.commit()
    return AskOut(
        id=q.id,
        answer=result.answer,
        citations=citations,
        provider=provider.name,
        latency_ms=q.latency_ms,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
    )


@router.get("/history")
def history(
    document_id: str | None = None,
    limit: int = Query(20, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Question).where(Question.org_id == user.org_id)
    if document_id:
        stmt = stmt.where(Question.document_id == document_id)
    rows = db.scalars(stmt.order_by(Question.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "question": r.question,
            "answer": r.answer,
            "citations": r.citations,
            "document_id": r.document_id,
            "created_at": r.created_at,
            "provider": r.llm_provider,
        }
        for r in rows
    ]
