"""Company rulebook: checks every document against the organization's own policies.

Most rule kinds are deterministic - they run on the structured fields the model extracted (notice period,
payment terms, amounts) or on the source text, so results are consistent, instant and free. The
``ai_instruction`` kind lets a company express any policy in plain English; it is evaluated by the model
during extraction (Claude mode).
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.models import Document, PlaybookRule
from app.schemas import DocumentInsights
from app.services.llm.base import PolicyInstruction

# Metadata drives both validation and the "add rule" form in the UI.
RULE_KINDS: dict[str, dict[str, Any]] = {
    "max_notice_days": {
        "label": "Maximum notice period to cancel",
        "help": "Flag auto-renewing agreements that need more notice than you allow.",
        "params": [{"name": "days", "type": "int", "label": "Maximum days of notice", "default": 60}],
    },
    "no_auto_renewal": {
        "label": "Auto-renewal needs sign-off",
        "help": "Flag every agreement that renews automatically.",
        "params": [],
    },
    "payment_terms": {
        "label": "Payment terms window",
        "help": "Flag payment terms shorter or longer than you accept (0 = no limit).",
        "params": [
            {"name": "min_days", "type": "int", "label": "At least (days)", "default": 30},
            {"name": "max_days", "type": "int", "label": "At most (days)", "default": 0},
        ],
    },
    "approval_threshold": {
        "label": "Approval threshold",
        "help": "Flag agreements whose value (monthly fees annualized) reaches an amount.",
        "params": [
            {"name": "amount", "type": "number", "label": "Amount", "default": 50000},
            {"name": "currency", "type": "string", "label": "Currency (ISO code)", "default": "USD"},
        ],
    },
    "required_clause": {
        "label": "Required clause",
        "help": "Flag documents that contain none of these phrases.",
        "params": [
            {"name": "clause", "type": "string", "label": "Clause name", "default": ""},
            {"name": "phrases", "type": "list", "label": "Any of these phrases", "default": []},
        ],
    },
    "prohibited_clause": {
        "label": "Prohibited clause",
        "help": "Flag documents that contain any of these phrases.",
        "params": [{"name": "phrases", "type": "list", "label": "Phrases", "default": []}],
    },
    "ai_instruction": {
        "label": "Plain-English rule (AI)",
        "help": "Describe the policy in your own words; the AI checks it when a document is analyzed.",
        "params": [{"name": "instruction", "type": "text", "label": "Policy", "default": ""}],
        "ai": True,
    },
}

_EXCLUDED_AMOUNTS = re.compile(r"insurance|liabil|cap|tax|deposit|late|replacement|threshold|rate", re.I)


class RuleValidationError(ValueError):
    pass


def validate_params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    spec = RULE_KINDS.get(kind)
    if spec is None:
        raise RuleValidationError(f"Unknown rule kind {kind!r}")
    clean: dict[str, Any] = {}
    for p in spec["params"]:
        value = params.get(p["name"], p["default"])
        try:
            if p["type"] == "int":
                value = int(value)
                if value < 0:
                    raise RuleValidationError(f"{p['label']} must be zero or more")
            elif p["type"] == "number":
                value = float(value)
                if value <= 0:
                    raise RuleValidationError(f"{p['label']} must be positive")
            elif p["type"] == "list":
                if isinstance(value, str):
                    value = [v for v in (x.strip() for x in value.split(",")) if v]
                value = [str(v).strip() for v in value if str(v).strip()][:20]
                if not value:
                    raise RuleValidationError(f"{p['label']}: add at least one phrase")
            else:
                value = str(value).strip()
        except (TypeError, ValueError) as exc:
            if isinstance(exc, RuleValidationError):
                raise
            raise RuleValidationError(f"{p['label']}: invalid value") from exc
        clean[p["name"]] = value
    if kind == "approval_threshold":
        clean["currency"] = (clean["currency"] or "USD").upper()[:3]
    if kind == "ai_instruction" and len(clean["instruction"]) < 10:
        raise RuleValidationError("Describe the policy in at least a short sentence")
    if kind == "payment_terms" and not (clean["min_days"] or clean["max_days"]):
        raise RuleValidationError("Set a minimum or maximum number of days")
    return clean


def _sentence_with(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.I)
    if not m:
        return ""
    start = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start()) + 1) + 1
    ends = [i for i in (text.find("\n", m.end()), text.find(". ", m.end())) if i != -1]
    end = min(ends) + 1 if ends else len(text)
    return re.sub(r"^(?:#+\s*)?(?:\d+(?:\.\d+)*\.?\s+)", "", text[start:end].strip())[:380]


def _finding(rule: PlaybookRule, status: str, message: str, quote: str = "") -> dict[str, Any]:
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "kind": rule.kind,
        "severity": rule.severity,
        "status": status,  # pass | fail | not_evaluated
        "message": message,
        "source_quote": quote,
    }


def evaluate(
    rules: list[PlaybookRule], insights: DocumentInsights, text: str, llm_provider: str | None
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    renewal = insights.renewal
    checks = {c.rule_id: c for c in insights.policy_checks}
    for rule in rules:
        if not rule.enabled or (rule.doc_types and insights.doc_type not in rule.doc_types):
            continue
        p = rule.params or {}
        if rule.kind == "max_notice_days":
            limit = int(p.get("days", 60))
            if renewal.notice_days > limit:
                findings.append(
                    _finding(
                        rule,
                        "fail",
                        f"Cancelling requires {renewal.notice_days} days' notice; your limit is {limit} days.",
                        renewal.source_quote,
                    )
                )
            else:
                msg = (
                    f"Notice period is {renewal.notice_days} days (limit {limit})."
                    if renewal.notice_days
                    else "No renewal notice requirement found."
                )
                findings.append(_finding(rule, "pass", msg))
        elif rule.kind == "no_auto_renewal":
            if renewal.auto_renews:
                months = f" for {renewal.renewal_term_months} months" if renewal.renewal_term_months else ""
                findings.append(
                    _finding(rule, "fail", f"Renews automatically{months} unless cancelled.", renewal.source_quote)
                )
            else:
                findings.append(_finding(rule, "pass", "Does not renew automatically."))
        elif rule.kind == "payment_terms":
            days = insights.payment_terms_days
            lo, hi = int(p.get("min_days", 0)), int(p.get("max_days", 0))
            quote = _sentence_with(text, rf"(?:within\s+{days}\s*days|net\s*{days}\b)") if days else ""
            if not days:
                findings.append(_finding(rule, "pass", "No payment terms stated."))
            elif lo and days < lo:
                findings.append(
                    _finding(rule, "fail", f"Payment due within {days} days; policy requires at least {lo}.", quote)
                )
            elif hi and days > hi:
                findings.append(
                    _finding(rule, "fail", f"Payment terms of {days} days exceed the {hi}-day maximum.", quote)
                )
            else:
                findings.append(_finding(rule, "pass", f"Payment terms of {days} days are within policy.", quote))
        elif rule.kind == "approval_threshold":
            currency = str(p.get("currency", "USD")).upper()
            threshold = float(p.get("amount", 0))
            values = [
                a.value * 12 if "monthly" in a.label.lower() else a.value
                for a in insights.amounts
                if (currency == "ANY" or a.currency == currency) and not _EXCLUDED_AMOUNTS.search(a.label)
            ]
            top = max(values, default=0.0)
            if top >= threshold:
                findings.append(
                    _finding(
                        rule,
                        "fail",
                        f"Value of {currency} {top:,.0f} reaches the {currency} {threshold:,.0f} approval threshold.",
                    )
                )
            else:
                findings.append(_finding(rule, "pass", f"Below the {currency} {threshold:,.0f} threshold."))
        elif rule.kind == "required_clause":
            phrases = p.get("phrases", [])
            hit = next((ph for ph in phrases if ph.lower() in text.lower()), None)
            if hit:
                findings.append(
                    _finding(rule, "pass", "Required clause present.", _sentence_with(text, re.escape(hit)))
                )
            else:
                findings.append(_finding(rule, "fail", f"Missing required clause: {p.get('clause') or phrases[0]}."))
        elif rule.kind == "prohibited_clause":
            phrases = p.get("phrases", [])
            hit = next((ph for ph in phrases if ph.lower() in text.lower()), None)
            if hit:
                findings.append(
                    _finding(
                        rule, "fail", f'Contains a prohibited term: "{hit}".', _sentence_with(text, re.escape(hit))
                    )
                )
            else:
                findings.append(_finding(rule, "pass", "No prohibited terms found."))
        elif rule.kind == "ai_instruction":
            check = checks.get(rule.id)
            if check is not None:
                findings.append(
                    _finding(rule, "fail" if check.violated else "pass", check.explanation, check.source_quote)
                )
            elif llm_provider == "demo":
                findings.append(
                    _finding(
                        rule,
                        "not_evaluated",
                        "Plain-English rules are checked by Claude; this document "
                        "was analyzed by the offline demo model.",
                    )
                )
            else:
                findings.append(_finding(rule, "not_evaluated", "Re-analyze this document to apply this rule."))
    order = {"fail": 0, "not_evaluated": 1, "pass": 2}
    findings.sort(key=lambda f: (order[f["status"]], {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3)))
    return findings


def enabled_rules(db: Session, org_id: str) -> list[PlaybookRule]:
    return list(
        db.scalars(
            select(PlaybookRule)
            .where(PlaybookRule.org_id == org_id, PlaybookRule.enabled.is_(True))
            .order_by(PlaybookRule.created_at)
        )
    )


def ai_policies(rules: list[PlaybookRule]) -> list[PolicyInstruction]:
    return [
        PolicyInstruction(rule_id=r.id, instruction=r.params.get("instruction", ""))
        for r in rules
        if r.kind == "ai_instruction" and r.params.get("instruction")
    ]


def apply_to_document(doc: Document, rules: list[PlaybookRule], text: str) -> None:
    if not doc.insights:
        doc.policy_findings, doc.policy_violations = None, 0
        return
    findings = evaluate(rules, DocumentInsights.model_validate(doc.insights), text, doc.llm_provider)
    doc.policy_findings = findings
    doc.policy_violations = sum(1 for f in findings if f["status"] == "fail")


def recheck_organization(db: Session, org_id: str) -> int:
    """Re-run the rulebook on every analyzed document (cheap: no model calls)."""
    rules = enabled_rules(db, org_id)
    docs = db.scalars(
        select(Document).where(Document.org_id == org_id, Document.status == "ready").options(undefer(Document.text))
    ).all()
    for doc in docs:
        apply_to_document(doc, rules, doc.text or "")
    return len(docs)
