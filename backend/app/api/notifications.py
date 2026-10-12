from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Notification, User, utcnow
from app.schemas import NotificationOut, NotificationSettingsIn
from app.security import get_current_user, require_role
from app.services import audit
from app.services.notifications import build_digest, send_digest

router = APIRouter(prefix="/api/notifications", tags=["alerts"])


def _settings_out(db: Session, user: User) -> dict:
    org = user.organization
    users = db.scalars(select(User).where(User.org_id == org.id).order_by(User.name)).all()
    return {
        "digest_enabled": org.digest_enabled,
        "digest_weekday": org.digest_weekday,
        "digest_lead_days": org.digest_lead_days,
        "digest_last_sent_at": org.digest_last_sent_at,
        "recipients": [
            {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "subscribed": u.notify_digest} for u in users
        ],
    }


@router.get("/settings")
def get_settings_(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _settings_out(db, user)


@router.put("/settings")
def update_settings(
    body: NotificationSettingsIn, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)
) -> dict:
    org = admin.organization
    org.digest_enabled = body.digest_enabled
    org.digest_weekday = body.digest_weekday
    org.digest_lead_days = body.digest_lead_days
    wanted = set(body.recipient_user_ids)
    db.execute(update(User).where(User.org_id == org.id).values(notify_digest=User.id.in_(wanted)))
    audit.record(
        db,
        admin,
        "alerts.updated",
        "weekly digest",
        enabled=body.digest_enabled,
        weekday=body.digest_weekday,
        lead_days=body.digest_lead_days,
        recipients=len(wanted),
    )
    db.commit()
    db.expire_all()
    return _settings_out(db, admin)


@router.get("/digest/preview", response_class=HTMLResponse)
def preview_digest(admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> str:
    return build_digest(db, admin.organization, utcnow().date()).html


@router.post("/digest/send", response_model=NotificationOut)
def send_now(admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> Notification:
    note = send_digest(db, admin.organization, force=True)
    audit.record(db, admin, "alerts.digest_sent", note.subject, status=note.status, recipients=len(note.recipients))
    db.commit()
    return note


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(20, ge=1, le=100), admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)
) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.org_id == admin.org_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/{notification_id}/html", response_class=HTMLResponse)
def notification_html(
    notification_id: str, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)
) -> str:
    note = db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.org_id == admin.org_id)
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return note.body_html
