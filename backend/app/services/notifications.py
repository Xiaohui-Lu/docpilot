"""Weekly deadline digest emails.

Delivery uses SMTP when configured; otherwise each email is written to ``outbox_dir`` as a .eml file
(open it in any mail client) and kept in the ``notifications`` table, so the feature works locally
with zero setup. In docker-compose, Mailpit catches the emails and shows them in a web inbox.
"""

import html
import logging
import re
import smtplib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Document, Job, Notification, Organization, User, utcnow
from app.services.deadlines import ActionItem, list_action_items

log = logging.getLogger(__name__)


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    items: list[ActionItem] = field(default_factory=list)
    flagged: list[Document] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.items and not self.flagged


_URGENCY_LABEL = {"overdue": "Overdue", "urgent": "Next 14 days", "soon": "Next 30 days", "upcoming": "Coming up"}
_URGENCY_COLOR = {"overdue": "#b91c1c", "urgent": "#b45309", "soon": "#1f6f5c", "upcoming": "#475569"}


def _when(days: int) -> str:
    if days < 0:
        return f"{-days} day{'s' if days != -1 else ''} ago"
    if days == 0:
        return "today"
    return f"in {days} day{'s' if days != 1 else ''}"


def build_digest(db: Session, org: Organization, today: date, settings: Settings | None = None) -> Digest:
    settings = settings or get_settings()
    base = settings.app_base_url.rstrip("/")
    items = list_action_items(db, org.id, today, horizon_days=org.digest_lead_days, past_days=30)
    since = org.digest_last_sent_at or (utcnow() - timedelta(days=7))
    flagged = list(
        db.scalars(
            select(Document)
            .where(
                Document.org_id == org.id,
                Document.status == "ready",
                Document.processed_at >= since,
                (Document.overall_risk == "high") | (Document.policy_violations > 0),
            )
            .order_by(Document.processed_at.desc())
        )
    )

    act_now = [i for i in items if i.urgency in ("overdue", "urgent")]
    plural = "s" if len(items) != 1 else ""
    subject = f"DocPilot: {len(items)} contract deadline{plural} in the next {org.digest_lead_days} days"
    if act_now:
        subject += f" ({len(act_now)} need action now)"

    # Plain-text part
    lines = [f"Contract deadlines for {org.name} - week of {today:%B %d, %Y}", ""]
    for group in ("overdue", "urgent", "soon", "upcoming"):
        group_items = [i for i in items if i.urgency == group]
        if not group_items:
            continue
        lines.append(_URGENCY_LABEL[group].upper())
        for i in group_items:
            lines.append(f"- {date.fromisoformat(i.date):%b %d} ({_when(i.days_left)}): {i.label} - {i.document_title}")
            if i.detail:
                lines.append(f"  {i.detail}")
            lines.append(f"  {base}/documents/{i.document_id}")
        lines.append("")
    if flagged:
        lines.append("NEWLY FLAGGED DOCUMENTS")
        for d in flagged:
            lines.append(f"- {d.title or d.filename}: {d.overall_risk} risk, {d.policy_violations} rulebook issue(s)")
        lines.append("")
    if not items and not flagged:
        lines.append("Nothing needs your attention this week.")
    lines += ["", f"All deadlines: {base}/deadlines", "Change these emails: ask an admin to update Alert settings."]
    text = "\n".join(lines)

    # HTML part (inline styles - email clients ignore <style> blocks)
    rows = []
    for group in ("overdue", "urgent", "soon", "upcoming"):
        group_items = [i for i in items if i.urgency == group]
        if not group_items:
            continue
        color = _URGENCY_COLOR[group]
        rows.append(
            f'<tr><td colspan="3" style="padding:18px 0 6px;font:600 12px Segoe UI,Arial;letter-spacing:.08em;'
            f'color:{color};text-transform:uppercase">{_URGENCY_LABEL[group]}</td></tr>'
        )
        for i in group_items:
            rows.append(
                "<tr>"
                f'<td style="padding:8px 12px 8px 0;font:600 14px Segoe UI,Arial;color:#12343b;white-space:nowrap;'
                f'vertical-align:top">{date.fromisoformat(i.date):%b %d}<br>'
                f'<span style="font-weight:400;font-size:12px;color:{color}">{_when(i.days_left)}</span></td>'
                f'<td style="padding:8px 12px 8px 0;font:14px Segoe UI,Arial;color:#1d2a2e;vertical-align:top">'
                f"<b>{html.escape(i.label)}</b><br>"
                f'<span style="color:#5f6b6e;font-size:13px">{html.escape(i.detail)}</span></td>'
                f'<td style="padding:8px 0;font:14px Segoe UI,Arial;vertical-align:top">'
                f'<a href="{base}/documents/{i.document_id}" style="color:#18705b">{html.escape(i.document_title)}</a>'
                "</td></tr>"
            )
    flagged_html = "".join(
        f'<li style="margin:4px 0"><a href="{base}/documents/{d.id}" style="color:#18705b">'
        f"{html.escape(d.title or d.filename)}</a> - {d.overall_risk} risk, "
        f"{d.policy_violations} rulebook issue(s)</li>"
        for d in flagged
    )
    body = (
        f'<table role="presentation" style="width:100%;border-collapse:collapse">{"".join(rows)}</table>'
        if rows
        else '<p style="font:14px Segoe UI,Arial;color:#5f6b6e">Nothing needs your attention this week.</p>'
    )
    flagged_block = (
        '<h3 style="font:600 14px Segoe UI,Arial;color:#12343b;margin-top:24px">Newly flagged documents</h3>'
        f'<ul style="font:14px Segoe UI,Arial;color:#1d2a2e;padding-left:18px">{flagged_html}</ul>'
        if flagged
        else ""
    )
    html_doc = f"""<!doctype html><html><body style="margin:0;background:#f5f3ee;padding:24px">
<div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e3e0d8;border-radius:12px;overflow:hidden">
<div style="background:#12343b;padding:18px 24px;font:600 16px Segoe UI,Arial;color:#fff">DocPilot
<span style="font-weight:400;color:#a7dcc9"> - weekly contract deadlines</span></div>
<div style="padding:8px 24px 24px">
<p style="font:14px Segoe UI,Arial;color:#1d2a2e">Here is what needs attention at <b>{html.escape(org.name)}</b>
in the next {org.digest_lead_days} days.</p>
{body}
{flagged_block}
<p style="margin-top:24px"><a href="{base}/deadlines" style="display:inline-block;background:#12343b;color:#fff;
padding:10px 16px;border-radius:8px;font:600 14px Segoe UI,Arial;text-decoration:none">Open all deadlines</a></p>
</div></div>
<p style="text-align:center;font:12px Segoe UI,Arial;color:#8a9496">Sent by DocPilot to people who opted in to weekly
alerts.</p></body></html>"""
    return Digest(subject=subject, text=text, html=html_doc, items=items, flagged=flagged)


def deliver_email(to: list[str], subject: str, text: str, html_body: str, settings: Settings | None = None) -> str:
    """Send one email. Returns the transport used: 'smtp' or 'outbox'."""
    settings = settings or get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    if settings.smtp_host:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return "smtp"
    outbox = Path(settings.outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    name = f"{utcnow():%Y%m%dT%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', subject.lower())[:60]}.eml"
    (outbox / name).write_bytes(bytes(msg))
    return "outbox"


def digest_recipients(db: Session, org_id: str) -> list[str]:
    return list(
        db.scalars(select(User.email).where(User.org_id == org_id, User.notify_digest.is_(True)).order_by(User.email))
    )


def send_digest(
    db: Session, org: Organization, today: date | None = None, *, force: bool = False, raise_on_error: bool = False
) -> Notification:
    """Build and deliver the digest. Records a Notification row whatever happens."""
    today = today or utcnow().date()
    digest = build_digest(db, org, today)
    recipients = digest_recipients(db, org.id)
    note = Notification(
        org_id=org.id,
        kind="digest",
        subject=digest.subject,
        recipients=recipients,
        body_text=digest.text,
        body_html=digest.html,
        item_count=len(digest.items),
    )
    if not recipients:
        note.status, note.transport, note.error = "skipped", "none", "No one has opted in to digest emails"
    elif digest.is_empty and not force:
        note.status, note.transport, note.error = "skipped", "none", "Nothing to report this week"
    else:
        try:
            note.transport = deliver_email(recipients, digest.subject, digest.text, digest.html)
            note.status = "sent"
        except Exception as exc:  # SMTP failures are reported, and retried when run as a job
            note.status, note.transport, note.error = "failed", "smtp", f"{type(exc).__name__}: {exc}"
            log.warning("digest delivery failed", exc_info=True)
    org.digest_last_sent_at = utcnow()
    db.add(note)
    db.commit()
    if note.status == "failed" and raise_on_error:
        raise RuntimeError(note.error)
    return note


def due_for_digest(org: Organization, now: datetime) -> bool:
    if not org.digest_enabled or now.weekday() != org.digest_weekday or now.hour < 12:  # ~8am US Eastern
        return False
    return org.digest_last_sent_at is None or org.digest_last_sent_at <= now - timedelta(days=6)


def schedule_digests(db: Session, now: datetime | None = None) -> int:
    """Enqueue a digest job for every organization that is due (called periodically by workers)."""
    now = now or utcnow()
    queued = 0
    for org in db.scalars(select(Organization).where(Organization.digest_enabled.is_(True))):
        if not due_for_digest(org, now):
            continue
        pending = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.org_id == org.id, Job.kind == "send_digest", Job.status.in_(("queued", "running")))
        )
        if pending:
            continue
        db.add(Job(org_id=org.id, kind="send_digest", max_attempts=3))
        queued += 1
    db.commit()
    return queued
