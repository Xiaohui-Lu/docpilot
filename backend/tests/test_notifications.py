from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Notification, Organization
from app.services import notifications
from app.services.jobs import drain
from tests.conftest import auth_headers, register, upload


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "outbox_dir", str(tmp_path / "outbox"))
    monkeypatch.setattr(settings, "smtp_host", "")
    return tmp_path / "outbox"


def _org(db) -> Organization:
    return db.scalars(select(Organization)).first()


def test_settings_and_send_now_to_outbox(client, outbox):
    h = auth_headers(register(client))
    upload(client, h, "01")
    drain()

    s = client.get("/api/notifications/settings", headers=h).json()
    assert s["digest_enabled"] and s["digest_lead_days"] == 60
    assert [r["subscribed"] for r in s["recipients"]] == [True]

    sent = client.post("/api/notifications/digest/send", headers=h).json()
    assert sent["status"] == "sent" and sent["transport"] == "outbox"
    assert sent["recipients"] == ["admin@northwind.example.com"]
    assert sent["item_count"] >= 1 and "contract deadline" in sent["subject"]
    eml = list(outbox.glob("*.eml"))
    assert len(eml) == 1
    raw = eml[0].read_text(encoding="utf-8", errors="ignore")
    assert "Subject: DocPilot:" in raw and "text/html" in raw

    html = client.get(f"/api/notifications/{sent['id']}/html", headers=h).text
    assert "Last day to cancel auto-renewal" in html and "Master Subscription Agreement" in html
    assert client.get("/api/notifications", headers=h).json()[0]["id"] == sent["id"]
    assert "Open all deadlines" in client.get("/api/notifications/digest/preview", headers=h).text


def test_unsubscribed_org_is_skipped(client, outbox):
    h = auth_headers(register(client))
    r = client.put(
        "/api/notifications/settings",
        headers=h,
        json={"digest_enabled": True, "digest_weekday": 2, "digest_lead_days": 30, "recipient_user_ids": []},
    )
    assert r.json()["digest_weekday"] == 2 and not r.json()["recipients"][0]["subscribed"]
    note = client.post("/api/notifications/digest/send", headers=h).json()
    assert note["status"] == "skipped" and "opted in" in note["error"]
    assert not outbox.exists() or not list(outbox.glob("*.eml"))


def test_smtp_transport_and_failure(client, outbox, monkeypatch):
    h = auth_headers(register(client))
    sent_messages = []

    class FakeSMTP:
        fail = False

        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.example.com", 587)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            assert user == "apikey"

        def send_message(self, msg):
            if FakeSMTP.fail:
                raise ConnectionRefusedError("smtp down")
            sent_messages.append(msg)

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "apikey")
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)

    note = client.post("/api/notifications/digest/send", headers=h).json()
    assert note["transport"] == "smtp" and note["status"] == "sent"
    assert sent_messages[0]["To"] == "admin@northwind.example.com"

    FakeSMTP.fail = True
    failed = client.post("/api/notifications/digest/send", headers=h).json()
    assert failed["status"] == "failed" and "smtp down" in failed["error"]


def test_scheduler_enqueues_once_and_job_sends(client, outbox):
    h = auth_headers(register(client))
    upload(client, h, "07")
    drain()
    now = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
    with SessionLocal() as db:
        org = _org(db)
        org.digest_weekday = now.weekday()
        db.commit()
        assert notifications.due_for_digest(org, now)
        assert not notifications.due_for_digest(org, now.replace(hour=6))  # too early in the day
        assert notifications.schedule_digests(db, now) == 1
        assert notifications.schedule_digests(db, now) == 0  # already queued

    assert drain() == 1
    with SessionLocal() as db:
        note = db.scalars(select(Notification)).one()
        assert note.status == "sent" and note.item_count >= 1
        job = db.scalars(select(Job).where(Job.kind == "send_digest")).one()
        assert job.status == "succeeded"
        org = _org(db)
        assert org.digest_last_sent_at is not None
        assert not notifications.due_for_digest(org, now + timedelta(days=3))
        assert notifications.schedule_digests(db, now + timedelta(days=1)) == 0


def test_settings_require_admin(client):
    h = auth_headers(register(client))
    client.post(
        "/api/admin/users",
        headers=h,
        json={"name": "M", "email": "m@northwind.example.com", "password": "member-pass", "role": "member"},
    )
    member = auth_headers(
        client.post("/api/auth/login", json={"email": "m@northwind.example.com", "password": "member-pass"}).json()
    )
    assert client.get("/api/notifications/settings", headers=member).status_code == 200
    body = {"digest_enabled": False, "digest_weekday": 0, "digest_lead_days": 60, "recipient_user_ids": []}
    assert client.put("/api/notifications/settings", headers=member, json=body).status_code == 403
    assert client.post("/api/notifications/digest/send", headers=member).status_code == 403
