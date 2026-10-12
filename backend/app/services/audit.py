from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record(
    db: Session,
    user: User | None,
    action: str,
    target: str | None = None,
    *,
    org_id: str | None = None,
    **detail: Any,
) -> None:
    """Append an audit event. The caller owns the transaction."""
    db.add(
        AuditEvent(
            org_id=org_id or (user.org_id if user else ""),
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            target=target,
            detail=detail,
        )
    )
