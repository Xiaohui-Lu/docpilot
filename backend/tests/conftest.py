import os
import pathlib

os.environ["DOCPILOT_ENV"] = "test"
os.environ["DOCPILOT_LLM_PROVIDER"] = "demo"
os.environ["DOCPILOT_JWT_SECRET"] = "test-secret-0123456789abcdef0123456789"
os.environ["DOCPILOT_DATABASE_URL"] = "sqlite:///./.pytest-bootstrap.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as db_module  # noqa: E402
from app import models  # noqa: E402, F401  (register tables before drop_all)
from app.services.llm import get_provider  # noqa: E402

SAMPLES = pathlib.Path(__file__).resolve().parents[2] / "samples"


# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the suite against PostgreSQL, as CI does.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db_module.configure_engine(TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'test.db'}")
    if TEST_DATABASE_URL:
        db_module.Base.metadata.drop_all(bind=db_module.engine)
    db_module.init_db()
    get_provider.cache_clear()
    yield
    db_module.engine.dispose()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str = "admin@northwind.example.com", org: str = "Northwind") -> dict:
    r = client.post(
        "/api/auth/register",
        json={"org_name": org, "name": "Admin", "email": email, "password": "s3cure-pass!"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(token_response: dict) -> dict:
    return {"Authorization": f"Bearer {token_response['access_token']}"}


def sample(name_prefix: str) -> tuple[str, bytes]:
    path = next(SAMPLES.glob(f"{name_prefix}*"))
    return path.name, path.read_bytes()


def upload(client: TestClient, headers: dict, name_prefix: str = "01") -> dict:
    name, data = sample(name_prefix)
    r = client.post("/api/documents", headers=headers, files={"file": (name, data, "text/markdown")})
    assert r.status_code == 202, r.text
    return r.json()
