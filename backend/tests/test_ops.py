def test_health_ready_and_metrics(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ready"
    client.get("/api/documents")  # generate a 401 to be counted
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "docpilot_http_requests_total" in metrics.text
    assert 'route="/api/documents",status="401"' in metrics.text


def test_request_id_is_propagated(client):
    r = client.get("/healthz", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert client.get("/healthz").headers["x-request-id"]


def test_openapi_documents_all_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/auth/login", "/api/documents", "/api/ask", "/api/analytics/overview", "/api/admin/audit"):
        assert p in paths
