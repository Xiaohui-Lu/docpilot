from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditEvent, User
from app.schemas import AuditOut, RoleUpdateIn, UserCreateIn, UserOut
from app.security import hash_password, require_role
from app.services import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).where(User.org_id == admin.org_id).order_by(User.created_at)))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateIn, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)
) -> User:
    email = body.email.lower()
    if db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        org_id=admin.org_id,
        email=email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    audit.record(db, admin, "user.created", email, role=body.role)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_role(
    user_id: str,
    body: RoleUpdateIn,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.org_id == admin.org_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and body.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own admin role")
    audit.record(db, admin, "user.role_changed", user.email, old=user.role, new=body.role)
    user.role = body.role
    db.commit()
    return user


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    limit: int = Query(50, ge=1, le=500),
    action: str | None = None,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.org_id == admin.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    return list(db.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit)))
