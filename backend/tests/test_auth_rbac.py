from tests.conftest import auth_headers, register


def test_register_login_and_me(client):
    reg = register(client)
    assert reg["user"]["role"] == "admin"
    assert reg["org_name"] == "Northwind"

    r = client.post("/api/auth/login", json={"email": "ADMIN@northwind.example.com", "password": "s3cure-pass!"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=auth_headers(r.json()))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@northwind.example.com"


def test_bad_credentials_and_duplicates(client):
    register(client)
    assert (
        client.post(
            "/api/auth/login", json={"email": "admin@northwind.example.com", "password": "nope-nope"}
        ).status_code
        == 401
    )
    r = client.post(
        "/api/auth/register",
        json={
            "org_name": "Other Co",
            "name": "Y",
            "email": "admin@northwind.example.com",
            "password": "another-pass",
        },
    )
    assert r.status_code == 409


def test_requires_token(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_role_based_access(client):
    admin = auth_headers(register(client))
    r = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "name": "Vic Viewer",
            "email": "viewer@northwind.example.com",
            "password": "viewer-pass",
            "role": "viewer",
        },
    )
    assert r.status_code == 201
    viewer = auth_headers(
        client.post("/api/auth/login", json={"email": "viewer@northwind.example.com", "password": "viewer-pass"}).json()
    )

    # viewers can read but not upload or administer
    assert client.get("/api/documents", headers=viewer).status_code == 200
    up = client.post("/api/documents", headers=viewer, files={"file": ("a.txt", b"hello world", "text/plain")})
    assert up.status_code == 403
    assert client.get("/api/admin/users", headers=viewer).status_code == 403

    # admins can promote, but cannot demote themselves
    users = client.get("/api/admin/users", headers=admin).json()
    me = next(u for u in users if u["role"] == "admin")
    assert client.patch(f"/api/admin/users/{me['id']}", headers=admin, json={"role": "member"}).status_code == 400
    vid = next(u["id"] for u in users if u["role"] == "viewer")
    assert client.patch(f"/api/admin/users/{vid}", headers=admin, json={"role": "member"}).json()["role"] == "member"

    actions = [e["action"] for e in client.get("/api/admin/audit", headers=admin).json()]
    assert "user.created" in actions and "user.role_changed" in actions
