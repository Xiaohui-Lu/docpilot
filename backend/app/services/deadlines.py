"""Turn extracted contract data into dated action items.

The most valuable one is computed, not extracted: for an auto-renewing agreement the *last day to cancel*
is the term end date minus the notice period. Missing it usually means paying for another full term.
"""

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeadlineAck, Document

# Dates that record something that already happened are not actionable.
_NOT_ACTIONABLE = re.compile(
    r"sign|effective|start|commenc|issue|approv|dated|executed|made on"
    r"|agreement date|contract date|invoice date|billing date",
    re.I,
)

_KIND_BY_LABEL = (
    (re.compile(r"payment|due|payable", re.I), "payment_due"),
    (re.compile(r"notice", re.I), "notice"),
    (re.compile(r"renew", re.I), "renewal"),
    (re.compile(r"expir|end|terminat", re.I), "expiry"),
    (re.compile(r"review|re-?assess|audit", re.I), "review"),
    (re.compile(r"deadline|deliver", re.I), "deadline"),
)


@dataclass
class ActionItem:
    key: str
    document_id: str
    document_title: str
    kind: str  # cancel_by | auto_renews | payment_due | notice | renewal | expiry | review | deadline | date
    label: str
    date: str  # ISO
    days_left: int
    urgency: str  # overdue | urgent (<=14d) | soon (<=30d) | upcoming
    detail: str = ""
    source_quote: str = ""
    handled: bool = False
    handled_by: str | None = None
    handled_at: datetime | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def urgency(days_left: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left <= 14:
        return "urgent"
    if days_left <= 30:
        return "soon"
    return "upcoming"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _parse(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def items_for_document(doc: Document, today: date) -> list[ActionItem]:
    ins = doc.insights or {}
    title = doc.title or doc.filename
    items: list[ActionItem] = []

    def add(kind: str, label: str, when: date, detail: str = "", quote: str = "") -> None:
        days = (when - today).days
        items.append(
            ActionItem(
                key=f"{kind}:{when.isoformat()}:{_slug(label)}",
                document_id=doc.id,
                document_title=title,
                kind=kind,
                label=label,
                date=when.isoformat(),
                days_left=days,
                urgency=urgency(days),
                detail=detail,
                source_quote=quote,
            )
        )

    renewal = ins.get("renewal") or {}
    term_end = _parse(renewal.get("term_end_date", "")) if renewal.get("auto_renews") else None
    covered: set[date] = set()  # dates already represented by the computed renewal items
    if term_end:
        notice = int(renewal.get("notice_days") or 0)
        covered = {term_end, term_end - timedelta(days=notice)}
        months = int(renewal.get("renewal_term_months") or 0)
        term_txt = f" for another {months} months" if months else ""
        quote = renewal.get("source_quote", "")
        if notice:
            add(
                "cancel_by",
                f"Last day to cancel auto-renewal ({notice}-day notice)",
                term_end - timedelta(days=notice),
                f"The term ends {term_end:%b %d, %Y}. Without written notice by this date it renews{term_txt}.",
                quote,
            )
        add("auto_renews", "Term ends - renews automatically", term_end, f"Renews{term_txt} unless cancelled.", quote)

    for kd in ins.get("key_dates", []):
        when = _parse(kd.get("date", ""))
        label = kd.get("label", "Date")
        if when is None or _NOT_ACTIONABLE.search(label):
            continue
        if when in covered:
            continue  # the model sometimes lists the term end / notice deadline itself; don't show it twice
        kind = next((k for pattern, k in _KIND_BY_LABEL if pattern.search(label)), "date")
        add(kind, label, when, "", kd.get("source_quote", ""))
    return items


def list_action_items(
    db: Session,
    org_id: str,
    today: date,
    *,
    horizon_days: int = 365,
    past_days: int = 30,
    include_handled: bool = False,
    document_id: str | None = None,
) -> list[ActionItem]:
    stmt = select(Document).where(Document.org_id == org_id, Document.status == "ready")
    if document_id:
        stmt = stmt.where(Document.id == document_id)
    docs = db.scalars(stmt).all()
    acks = {(a.document_id, a.key): a for a in db.scalars(select(DeadlineAck).where(DeadlineAck.org_id == org_id))}
    out: list[ActionItem] = []
    for doc in docs:
        for item in items_for_document(doc, today):
            if not (-past_days <= item.days_left <= horizon_days):
                continue
            ack = acks.get((item.document_id, item.key))
            if ack:
                if not include_handled:
                    continue
                item.handled, item.handled_by, item.handled_at, item.note = (
                    True,
                    ack.handled_by,
                    ack.handled_at,
                    ack.note,
                )
            out.append(item)
    out.sort(key=lambda i: (i.date, i.kind != "cancel_by"))
    return out


# ---------------------------------------------------------------------------
# iCalendar feed (RFC 5545) so deadlines show up in Outlook / Google Calendar
# ---------------------------------------------------------------------------

_KIND_PREFIX = {
    "cancel_by": "Cancel-by",
    "auto_renews": "Auto-renews",
    "payment_due": "Payment due",
    "notice": "Notice",
    "renewal": "Renewal",
    "expiry": "Expires",
    "review": "Review",
    "deadline": "Deadline",
}


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold lines longer than 75 octets as RFC 5545 requires."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def build_ics(items: list[ActionItem], calendar_name: str, base_url: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DocPilot//Contract deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
    ]
    for item in items:
        day = date.fromisoformat(item.date)
        uid = hashlib.sha1(f"{item.document_id}:{item.key}".encode()).hexdigest()
        summary = f"{_KIND_PREFIX.get(item.kind, 'Date')}: {item.document_title}"
        description = f"{item.label}. {item.detail}".strip() + f"\n{base_url}/documents/{item.document_id}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@docpilot",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            "TRANSP:TRANSPARENT",
        ]
        if item.kind in ("cancel_by", "payment_due", "notice", "deadline"):
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_ics_escape(summary)}",
                "TRIGGER:-P7D",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
