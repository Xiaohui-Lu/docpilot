from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, PlaybookRule, User
from app.schemas import RuleIn, RuleOut, RulePatch
from app.security import get_current_user, require_role
from app.services import audit
from app.services.rules import RULE_KINDS, RuleValidationError, recheck_organization, validate_params

router = APIRouter(prefix="/api/rules", tags=["rulebook"])


def _violation_counts(db: Session, org_id: str) -> dict[str, Counter[str]]:
    """Per rule: how many documents fail it, and how many could not be evaluated (AI rules in demo mode)."""
    counts: dict[str, Counter[str]] = {"fail": Counter(), "not_evaluated": Counter()}
    for findings in db.scalars(
        select(Document.policy_findings).where(Document.org_id == org_id, Document.status == "ready")
    ):
        for f in findings or []:
            if f["status"] in counts:
                counts[f["status"]][f["rule_id"]] += 1
    return counts


def _owned(db: Session, user: User, rule_id: str) -> PlaybookRule:
    rule = db.scalar(select(PlaybookRule).where(PlaybookRule.id == rule_id, PlaybookRule.org_id == user.org_id))
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


def _out(rule: PlaybookRule, counts: dict[str, Counter[str]]) -> RuleOut:
    return RuleOut.model_validate(rule).model_copy(
        update={"violations": counts["fail"][rule.id], "not_evaluated": counts["not_evaluated"][rule.id]}
    )


@router.get("/kinds")
def rule_kinds(_: User = Depends(get_current_user)) -> dict:
    return RULE_KINDS


@router.get("", response_model=list[RuleOut])
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RuleOut]:
    counts = _violation_counts(db, user.org_id)
    rules = db.scalars(select(PlaybookRule).where(PlaybookRule.org_id == user.org_id).order_by(PlaybookRule.created_at))
    return [_out(r, counts) for r in rules]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleIn, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> RuleOut:
    try:
        params = validate_params(body.kind, body.params)
    except RuleValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    rule = PlaybookRule(
        org_id=admin.org_id,
        name=body.name,
        description=body.description,
        kind=body.kind,
        params=params,
        severity=body.severity,
        doc_types=list(body.doc_types),
        enabled=body.enabled,
        created_by=admin.email,
    )
    db.add(rule)
    db.flush()
    recheck_organization(db, admin.org_id)
    audit.record(db, admin, "rule.created", rule.name, kind=rule.kind)
    db.commit()
    return _out(rule, _violation_counts(db, admin.org_id))


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: str, body: RulePatch, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)
) -> RuleOut:
    rule = _owned(db, admin, rule_id)
    changes = body.model_dump(exclude_unset=True)
    if "params" in changes:
        try:
            changes["params"] = validate_params(rule.kind, changes["params"] or {})
        except RuleValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    for field, value in changes.items():
        setattr(rule, field, list(value) if field == "doc_types" else value)
    db.flush()
    recheck_organization(db, admin.org_id)
    audit.record(db, admin, "rule.updated", rule.name, changes=sorted(changes))
    db.commit()
    return _out(rule, _violation_counts(db, admin.org_id))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: str, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)) -> None:
    rule = _owned(db, admin, rule_id)
    audit.record(db, admin, "rule.deleted", rule.name)
    db.delete(rule)
    db.flush()
    recheck_organization(db, admin.org_id)
    db.commit()
