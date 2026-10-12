import csv
import hashlib
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, undefer

from app.config import get_settings
from app.db import get_db
from app.models import Document, Job, User
from app.schemas import DocumentDetailOut, DocumentOut, DocumentPage, JobOut
from app.security import get_current_user, require_role
from app.services import audit
from app.services.jobs import enqueue_document
from app.services.parsing import UnsupportedDocument, detect_content_type

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _get_owned(db: Session, user: User, document_id: str, *, with_text: bool = False) -> Document:
    stmt = select(Document).where(Document.id == document_id, Document.org_id == user.org_id)
    if with_text:
        stmt = stmt.options(undefer(Document.text))
    doc = db.scalar(stmt)
    if doc is None:  # 404 (not 403) so other tenants' IDs are not discoverable
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("", response_model=DocumentPage)
def list_documents(
    q: str | None = Query(None, max_length=200),
    status_: str | None = Query(None, alias="status"),
    doc_type: str | None = None,
    risk: str | None = None,
    policy: str | None = Query(None, pattern="^(violations|compliant)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPage:
    stmt = select(Document).where(Document.org_id == user.org_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Document.filename).like(like), func.lower(Document.title).like(like)))
    if status_:
        stmt = stmt.where(Document.status == status_)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if risk:
        stmt = stmt.where(Document.overall_risk == risk)
    if policy == "violations":
        stmt = stmt.where(Document.policy_violations > 0)
    elif policy == "compliant":
        stmt = stmt.where(Document.status == "ready", Document.policy_violations == 0)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return DocumentPage(
        items=[DocumentOut.model_validate(d) for d in rows], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(require_role("member")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    settings = get_settings()
    filename = (file.filename or "document").replace("\\", "/").split("/")[-1][:300]
    try:
        content_type = detect_content_type(filename, file.content_type)
    except UnsupportedDocument as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    data = await file.read(settings.upload_max_mb * 1024 * 1024 + 1)
    if len(data) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {settings.upload_max_mb} MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.org_id == user.org_id, Document.sha256 == sha))
    if existing is not None:  # idempotent upload: same bytes -> same document
        return DocumentOut.model_validate(existing)

    doc = Document(
        org_id=user.org_id,
        uploaded_by=user.id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha,
        raw=data,
        status="queued",
    )
    db.add(doc)
    db.flush()
    enqueue_document(db, doc)
    audit.record(db, user, "document.uploaded", filename, document_id=doc.id, size_bytes=len(data))
    db.commit()
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentDetailOut:
    doc = _get_owned(db, user, document_id, with_text=True)
    jobs = db.scalars(select(Job).where(Job.document_id == doc.id).order_by(Job.created_at.desc())).all()
    out = DocumentDetailOut.model_validate(
        {
            **DocumentOut.model_validate(doc).model_dump(),
            "insights": doc.insights,
            "grounding": doc.grounding,
            "policy_findings": doc.policy_findings,
            "text": doc.text or "",
            "jobs": [JobOut.model_validate(j) for j in jobs],
        }
    )
    return out


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    document_id: str, user: User = Depends(require_role("member")), db: Session = Depends(get_db)
) -> DocumentOut:
    doc = _get_owned(db, user, document_id)
    active = db.scalar(
        select(func.count()).select_from(Job).where(Job.document_id == doc.id, Job.status.in_(("queued", "running")))
    )
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already being processed")
    doc.status = "queued"
    doc.error = None
    enqueue_document(db, doc)
    audit.record(db, user, "document.reprocessed", doc.filename, document_id=doc.id)
    db.commit()
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str, user: User = Depends(require_role("member")), db: Session = Depends(get_db)
) -> None:
    doc = _get_owned(db, user, document_id)
    audit.record(db, user, "document.deleted", doc.filename, document_id=doc.id)
    db.delete(doc)
    db.commit()


@router.get("/export/insights.csv")
def export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    """One row per document with the headline fields - for spreadsheets and BI tools."""
    docs = db.scalars(
        select(Document)
        .where(Document.org_id == user.org_id, Document.status == "ready")
        .order_by(Document.created_at.desc())
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "title",
            "filename",
            "type",
            "overall_risk",
            "parties",
            "next_date",
            "total_amount",
            "risks",
            "processed_at",
        ]
    )
    for d in docs:
        ins = d.insights or {}
        dates = sorted(x["date"] for x in ins.get("key_dates", []) if x.get("date"))
        amounts = ins.get("amounts", [])
        top = max(amounts, key=lambda a: a["value"], default=None)
        writer.writerow(
            [
                d.title,
                d.filename,
                d.doc_type,
                d.overall_risk,
                "; ".join(f"{p['name']} ({p['role']})" for p in ins.get("parties", [])),
                dates[0] if dates else "",
                f"{top['value']:.2f} {top['currency']}" if top else "",
                "; ".join(f"[{r['severity']}] {r['title']}" for r in ins.get("risks", [])),
                d.processed_at.isoformat() if d.processed_at else "",
            ]
        )
    audit.record(db, user, "report.exported", "insights.csv", rows=len(docs))
    db.commit()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="docpilot-insights.csv"'},
    )
