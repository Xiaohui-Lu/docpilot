from app.services.jobs import drain
from tests.conftest import auth_headers, register, upload


def test_upload_process_and_read(client):
    h = auth_headers(register(client))
    doc = upload(client, h, "01")
    assert doc["status"] == "queued"

    assert drain() == 1
    detail = client.get(f"/api/documents/{doc['id']}", headers=h).json()
    assert detail["status"] == "ready"
    assert detail["doc_type"] == "contract"
    assert detail["overall_risk"] in ("medium", "high")
    ins = detail["insights"]
    assert {p["name"] for p in ins["parties"]} >= {"Northwind Logistics Ltd.", "Brightline Software Inc."}
    assert any(r["title"] == "Automatic renewal" for r in ins["risks"])
    assert any(d["date"] == "2027-01-14" for d in ins["key_dates"])
    assert detail["grounding"]["score"] == 1.0
    assert detail["jobs"][0]["status"] == "succeeded"
    assert "Master Subscription Agreement" in detail["text"]


def test_upload_is_idempotent_and_validates(client):
    h = auth_headers(register(client))
    first = upload(client, h, "03")
    second = upload(client, h, "03")
    assert first["id"] == second["id"]

    bad = client.post("/api/documents", headers=h, files={"file": ("photo.png", b"\x89PNG", "image/png")})
    assert bad.status_code == 415
    empty = client.post("/api/documents", headers=h, files={"file": ("empty.txt", b"", "text/plain")})
    assert empty.status_code == 400


def test_list_filters_export_and_delete(client):
    h = auth_headers(register(client))
    for prefix in ("01", "03", "05"):
        upload(client, h, prefix)
    drain()

    page = client.get("/api/documents", headers=h).json()
    assert page["total"] == 3
    invoices = client.get("/api/documents?doc_type=invoice", headers=h).json()
    assert [d["doc_type"] for d in invoices["items"]] == ["invoice"]
    high = client.get("/api/documents?risk=high", headers=h).json()
    assert all(d["overall_risk"] == "high" for d in high["items"])
    search = client.get("/api/documents?q=consulting", headers=h).json()
    assert search["total"] == 1

    csv = client.get("/api/documents/export/insights.csv", headers=h)
    assert csv.status_code == 200
    assert csv.text.splitlines()[0].startswith("title,filename,type,overall_risk")
    assert len(csv.text.strip().splitlines()) == 4

    doc_id = invoices["items"][0]["id"]
    assert client.delete(f"/api/documents/{doc_id}", headers=h).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=h).status_code == 404


def test_reprocess(client):
    h = auth_headers(register(client))
    doc = upload(client, h, "02")
    assert client.post(f"/api/documents/{doc['id']}/reprocess", headers=h).status_code == 409  # still queued
    drain()
    assert client.post(f"/api/documents/{doc['id']}/reprocess", headers=h).status_code == 202
    drain()
    detail = client.get(f"/api/documents/{doc['id']}", headers=h).json()
    assert detail["status"] == "ready"
    assert len(detail["jobs"]) == 2


def test_tenant_isolation(client):
    a = auth_headers(register(client, "a@alpha.example.com", "Alpha"))
    b = auth_headers(register(client, "b@beta.example.com", "Beta"))
    doc = upload(client, a, "01")
    drain()

    assert client.get(f"/api/documents/{doc['id']}", headers=b).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=b).status_code == 404
    assert client.get("/api/documents", headers=b).json()["total"] == 0
    ans = client.post("/api/ask", headers=b, json={"question": "When does the subscription renew?"}).json()
    assert ans["citations"] == []
    assert (
        client.post("/api/ask", headers=b, json={"question": "renewal?", "document_id": doc["id"]}).status_code == 404
    )


def test_ask_with_citations_and_analytics(client):
    h = auth_headers(register(client))
    for prefix in ("01", "03", "04", "05"):
        upload(client, h, prefix)
    drain()

    r = client.post("/api/ask", headers=h, json={"question": "How much notice is needed to stop automatic renewal?"})
    assert r.status_code == 200
    body = r.json()
    assert "90 days" in body["answer"]
    assert body["citations"] and body["citations"][0]["document_title"] == "Master Subscription Agreement"

    hist = client.get("/api/ask/history", headers=h).json()
    assert hist[0]["question"].startswith("How much notice")

    stats = client.get("/api/analytics/overview", headers=h).json()
    assert stats["documents"]["total"] == 4
    assert stats["documents"]["by_status"]["ready"] == 4
    assert stats["top_risks"]
    assert stats["grounding"]["score"] == 1.0
    assert stats["llm"]["questions"] == 1
    assert len(stats["timeline"]) == 14
