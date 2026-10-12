from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, Job, Question, User, utcnow
from app.security import get_current_user
from app.services.deadlines import list_action_items

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org = user.org_id
    docs = db.scalars(select(Document).where(Document.org_id == org)).all()
    ready = [d for d in docs if d.status == "ready"]

    by_status = Counter(d.status for d in docs)
    by_type = Counter(d.doc_type or "unknown" for d in ready)
    by_risk = Counter(d.overall_risk or "unknown" for d in ready)

    risk_titles: Counter[str] = Counter()
    today = utcnow().date()
    total_value: dict[str, float] = {}
    grounded = checked = 0
    for d in ready:
        ins = d.insights or {}
        for r in ins.get("risks", []):
            risk_titles[r["title"]] += 1
        for a in ins.get("amounts", []):
            if a.get("label") in ("Total due", "Annual fee", "Fee", "Monthly fee", "Amount"):
                yearly = float(a["value"]) * (12 if a["label"] == "Monthly fee" else 1)
                total_value[a["currency"]] = total_value.get(a["currency"], 0.0) + yearly
        g = d.grounding or {}
        grounded += g.get("grounded", 0)
        checked += g.get("checked", 0)

    # Deadlines (computed cancel-by dates + extracted dates), excluding ones marked handled
    actions = list_action_items(db, org, today, horizon_days=120, past_days=30)
    upcoming = [
        {k: i.as_dict()[k] for k in ("document_id", "document_title", "label", "date", "days_left", "kind", "urgency")}
        for i in actions
    ]
    next_cancel = next((i for i in actions if i.kind == "cancel_by" and i.days_left >= 0), None)

    # Rulebook compliance
    rule_failures: Counter[str] = Counter()
    for d in ready:
        rule_failures.update(f["rule_name"] for f in d.policy_findings or [] if f["status"] == "fail")

    # Uploads per day for the last 14 days
    start = today - timedelta(days=13)
    per_day = Counter(d.created_at.date().isoformat() for d in docs if d.created_at.date() >= start)
    timeline = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "uploads": per_day.get((start + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(14)
    ]

    proc_times = sorted(d.processing_ms for d in ready if d.processing_ms is not None)
    p50 = proc_times[len(proc_times) // 2] if proc_times else None
    p95 = proc_times[min(len(proc_times) - 1, int(len(proc_times) * 0.95))] if proc_times else None

    q_stats = db.execute(
        select(
            func.count(Question.id),
            func.coalesce(func.sum(Question.cost_usd), 0.0),
            func.coalesce(func.sum(Question.input_tokens + Question.output_tokens), 0),
        ).where(Question.org_id == org)
    ).one()
    jobs = db.execute(select(Job.status, func.count()).where(Job.org_id == org).group_by(Job.status)).all()
    retried = db.scalar(select(func.count()).select_from(Job).where(Job.org_id == org, Job.attempts > 1)) or 0

    return {
        "generated_at": utcnow(),
        "documents": {
            "total": len(docs),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "by_risk": dict(by_risk),
        },
        "top_risks": [{"title": t, "count": c} for t, c in risk_titles.most_common(8)],
        "upcoming_dates": upcoming[:12],
        "deadlines": {
            "overdue": sum(1 for i in actions if i.urgency == "overdue"),
            "next_14_days": sum(1 for i in actions if i.urgency == "urgent"),
            "next_30_days": sum(1 for i in actions if i.urgency in ("overdue", "urgent", "soon")),
            "next_cancel_by": next_cancel.as_dict() if next_cancel else None,
        },
        "policy": {
            "documents_with_violations": sum(1 for d in ready if d.policy_violations),
            "violations": sum(d.policy_violations for d in ready),
            "top_rules": [{"rule": r, "count": c} for r, c in rule_failures.most_common(6)],
        },
        "contract_value": [{"currency": k, "value": round(v, 2)} for k, v in sorted(total_value.items())],
        "timeline": timeline,
        "processing": {"p50_ms": p50, "p95_ms": p95, "jobs": dict(jobs), "jobs_retried": retried},
        "grounding": {
            "checked": checked,
            "grounded": grounded,
            "score": round(grounded / checked, 3) if checked else None,
        },
        "llm": {
            "document_tokens": sum(d.input_tokens + d.output_tokens for d in docs),
            "document_cost_usd": round(sum(d.cost_usd for d in docs), 4),
            "questions": q_stats[0],
            "question_tokens": int(q_stats[2]),
            "question_cost_usd": round(float(q_stats[1]), 4),
        },
    }
