from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import DeadlineAck, Document, Organization, User, new_calendar_token, utcnow
from app.schemas import DeadlineHandleIn
from app.security import get_current_user, require_role
from app.services import audit
from app.services.deadlines import build_ics, list_action_items

router = APIRouter(prefix="/api/deadlines", tags=["deadlines"])
calendar_router = APIRouter(prefix="/api/calendar", tags=["deadlines"])


@router.get("")
def deadlines(
    horizon_days: int = Query(365, ge=1, le=1825),
    include_handled: bool = False,
    document_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Upcoming action items across the organization, including computed 'last day to cancel' dates."""
    items = list_action_items(
        db,
        user.org_id,
        utcnow().date(),
        horizon_days=horizon_days,
        include_handled=include_handled,
        document_id=document_id,
    )
    open_items = [i for i in items if not i.handled]
    counts = {u: sum(1 for i in open_items if i.urgency == u) for u in ("overdue", "urgent", "soon", "upcoming")}
    return {"items": [i.as_dict() for i in items], "counts": counts}


@router.post("/handled", status_code=status.HTTP_201_CREATED)
def mark_handled(
    body: DeadlineHandleIn, user: User = Depends(require_role("member")), db: Session = Depends(get_db)
) -> dict:
    doc = db.scalar(select(Document).where(Document.id == body.document_id, Document.org_id == user.org_id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    existing = db.scalar(select(DeadlineAck).where(DeadlineAck.document_id == doc.id, DeadlineAck.key == body.key))
    if existing is None:
        db.add(DeadlineAck(org_id=user.org_id, document_id=doc.id, key=body.key, note=body.note, handled_by=user.email))
        audit.record(db, user, "deadline.handled", doc.title or doc.filename, key=body.key, note=body.note)
        db.commit()
    return {"status": "handled"}


@router.delete("/handled", status_code=status.HTTP_204_NO_CONTENT)
def unmark_handled(
    document_id: str, key: str, user: User = Depends(require_role("member")), db: Session = Depends(get_db)
) -> None:
    db.execute(
        delete(DeadlineAck).where(
            DeadlineAck.org_id == user.org_id, DeadlineAck.document_id == document_id, DeadlineAck.key == key
        )
    )
    audit.record(db, user, "deadline.reopened", key, document_id=document_id)
    db.commit()


@router.get("/calendar")
def calendar_info(user: User = Depends(get_current_user)) -> dict:
    """Secret subscription URL for Outlook / Google Calendar / Apple Calendar."""
    return {"path": f"/api/calendar/{user.organization.calendar_token}.ics"}


@router.post("/calendar/rotate")
def rotate_calendar_token(admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> dict:
    org = admin.organization
    org.calendar_token = new_calendar_token()
    audit.record(db, admin, "calendar.token_rotated")
    db.commit()
    return {"path": f"/api/calendar/{org.calendar_token}.ics"}


@calendar_router.get("/{token}.ics", include_in_schema=False)
def calendar_feed(token: str, db: Session = Depends(get_db)) -> Response:
    # Calendar apps can't send auth headers, so the unguessable token in the URL is the credential.
    org = db.scalar(select(Organization).where(Organization.calendar_token == token))
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown calendar")
    items = list_action_items(db, org.id, utcnow().date(), horizon_days=730, past_days=60)
    body = build_ics(items, f"DocPilot deadlines - {org.name}", get_settings().app_base_url.rstrip("/"), utcnow())
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="docpilot-deadlines.ics"', "Cache-Control": "no-store"},
    )
