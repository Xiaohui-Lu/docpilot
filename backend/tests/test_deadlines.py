from datetime import UTC, date, datetime

import pytest

from app.api import deadlines as deadlines_api
from app.db import SessionLocal
from app.models import Document
from app.services.deadlines import build_ics, items_for_document, urgency
from app.services.jobs import drain
from tests.conftest import auth_headers, register, upload

TODAY = date(2026, 10, 12)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(deadlines_api, "utcnow", lambda: datetime(2026, 10, 12, 15, 0, tzinfo=UTC))


def _doc(**insights) -> Document:
    return Document(id="d1", org_id="o", filename="msa.md", title="MSA", insights=insights)


def test_cancel_by_is_term_end_minus_notice():
    doc = _doc(
        renewal={
            "auto_renews": True,
            "term_end_date": "2027-01-14",
            "notice_days": 90,
            "renewal_term_months": 12,
            "source_quote": "renews unless 90 days' notice",
        },
        key_dates=[
            {"label": "Signing date", "date": "2026-01-15", "source_quote": "x"},
            {"label": "Expiration / end date", "date": "2027-01-14", "source_quote": "x"},
            {"label": "Payment due", "date": "2026-11-14", "source_quote": "x"},
        ],
    )
    items = {i.kind: i for i in items_for_document(doc, TODAY)}
    assert items["cancel_by"].date == "2026-10-16"
    assert items["cancel_by"].days_left == 4 and items["cancel_by"].urgency == "urgent"
    assert "renews for another 12 months" in items["cancel_by"].detail
    assert items["auto_renews"].date == "2027-01-14"
    assert items["payment_due"].days_left == 33
    assert "expiry" not in items  # merged into the auto-renewal item
    assert all(i.label != "Signing date" for i in items.values())  # past events are not actions


def test_no_cancel_by_without_auto_renewal():
    doc = _doc(renewal={"auto_renews": False}, key_dates=[{"label": "Expiration", "date": "2027-06-30"}])
    kinds = [i.kind for i in items_for_document(doc, TODAY)]
    assert kinds == ["expiry"]


def test_urgency_bands():
    assert [urgency(d) for d in (-1, 0, 14, 15, 30, 31)] == ["overdue", "urgent", "urgent", "soon", "soon", "upcoming"]


def test_ics_is_valid_and_folded():
    doc = _doc(
        renewal={"auto_renews": True, "term_end_date": "2027-01-14", "notice_days": 90},
        key_dates=[],
    )
    doc.title = "Master Subscription Agreement with a very long title that forces line folding in the feed"
    ics = build_ics(items_for_document(doc, TODAY), "DocPilot", "http://app", datetime(2026, 10, 12, tzinfo=UTC))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261016" in ics
    assert "TRIGGER:-P7D" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:Cancel-by: Master Subscription Agreement with a very long title" in unfolded


def test_deadlines_api_handle_and_calendar(client):
    h = auth_headers(register(client))
    doc = upload(client, h, "01")
    drain()

    body = client.get("/api/deadlines", headers=h).json()
    cancel = next(i for i in body["items"] if i["kind"] == "cancel_by")
    assert cancel["date"] == "2026-10-16" and cancel["document_id"] == doc["id"]
    assert body["counts"]["urgent"] >= 1

    # Mark handled -> disappears from open list, visible with include_handled
    r = client.post(
        "/api/deadlines/handled",
        headers=h,
        json={"document_id": doc["id"], "key": cancel["key"], "note": "Sent notice"},
    )
    assert r.status_code == 201
    assert all(i["key"] != cancel["key"] for i in client.get("/api/deadlines", headers=h).json()["items"])
    handled = client.get("/api/deadlines?include_handled=true", headers=h).json()["items"]
    item = next(i for i in handled if i["key"] == cancel["key"])
    assert item["handled"] and item["note"] == "Sent notice" and item["handled_by"] == "admin@northwind.example.com"
    client.delete(f"/api/deadlines/handled?document_id={doc['id']}&key={cancel['key']}", headers=h)
    assert any(i["key"] == cancel["key"] for i in client.get("/api/deadlines", headers=h).json()["items"])

    # Calendar feed: secret URL, no auth header needed, rotatable
    path = client.get("/api/deadlines/calendar", headers=h).json()["path"]
    feed = client.get(path)
    assert feed.status_code == 200 and feed.headers["content-type"].startswith("text/calendar")
    assert "Cancel-by: Master Subscription Agreement" in feed.text.replace("\r\n ", "")
    new_path = client.post("/api/deadlines/calendar/rotate", headers=h).json()["path"]
    assert new_path != path
    assert client.get(path).status_code == 404
    assert client.get(new_path).status_code == 200


def test_deadline_permissions_and_tenancy(client):
    admin = auth_headers(register(client))
    doc = upload(client, admin, "01")
    drain()
    other = auth_headers(register(client, "x@other.example.com", "Other Co"))
    assert client.get("/api/deadlines", headers=other).json()["items"] == []
    r = client.post("/api/deadlines/handled", headers=other, json={"document_id": doc["id"], "key": "cancel_by:x"})
    assert r.status_code == 404

    client.post(
        "/api/admin/users",
        headers=admin,
        json={"name": "V", "email": "v@northwind.example.com", "password": "viewer-pass", "role": "viewer"},
    )
    viewer = auth_headers(
        client.post("/api/auth/login", json={"email": "v@northwind.example.com", "password": "viewer-pass"}).json()
    )
    assert client.get("/api/deadlines", headers=viewer).status_code == 200
    r = client.post("/api/deadlines/handled", headers=viewer, json={"document_id": doc["id"], "key": "cancel_by:x"})
    assert r.status_code == 403
    assert client.post("/api/deadlines/calendar/rotate", headers=viewer).status_code == 403


def test_dashboard_includes_deadline_and_policy_summary(client):
    h = auth_headers(register(client))
    upload(client, h, "07")
    drain()
    with SessionLocal() as db:
        assert db.query(Document).one().insights["renewal"]["notice_days"] == 60
    stats = client.get("/api/analytics/overview", headers=h).json()
    assert {"overdue", "next_14_days", "next_30_days", "next_cancel_by"} <= set(stats["deadlines"])
    assert {"documents_with_violations", "violations", "top_rules"} <= set(stats["policy"])


def test_model_listed_notice_deadline_is_not_duplicated():
    doc = _doc(
        renewal={"auto_renews": True, "term_end_date": "2026-12-31", "notice_days": 60, "renewal_term_months": 12},
        key_dates=[
            {"label": "Agreement date", "date": "2026-10-20", "source_quote": "x"},
            {"label": "Invoice date", "date": "2026-10-01", "source_quote": "x"},
            {"label": "Initial term end", "date": "2026-12-31", "source_quote": "x"},
            {
                "label": "Non-renewal notice deadline (60 days before term end)",
                "date": "2026-11-01",
                "source_quote": "x",
            },
        ],
    )
    kinds = sorted(i.kind for i in items_for_document(doc, TODAY))
    assert kinds == ["auto_renews", "cancel_by"]
