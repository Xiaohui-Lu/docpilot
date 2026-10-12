"""Create a demo workspace with sample documents, users and questions.

Runs through the real HTTP API (via FastAPI's TestClient), so seeding doubles as an end-to-end smoke test.

    python scripts/seed.py

Demo logins (local development only):
    admin   demo@docpilot.example.com      / docpilot-demo
    member  analyst@docpilot.example.com   / docpilot-demo
    viewer  auditor@docpilot.example.com   / docpilot-demo
"""

import os
import pathlib
import sys

os.environ.setdefault("DOCPILOT_WORKER_EMBEDDED", "false")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from datetime import timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document, utcnow  # noqa: E402
from app.services.jobs import drain  # noqa: E402

PASSWORD = "docpilot-demo"
SAMPLES = pathlib.Path(__file__).resolve().parents[2] / "samples"
# Spread demo uploads over the last two weeks so the activity chart looks like real usage.
UPLOAD_DAYS_AGO = [13, 11, 9, 7, 4, 2, 0]

# A starter rulebook for a logistics company buying software and services.
RULES = [
    {
        "name": "Notice period of 60 days or less",
        "description": "We need to be able to exit renewals without planning months ahead.",
        "kind": "max_notice_days",
        "params": {"days": 60},
        "severity": "high",
    },
    {
        "name": "Auto-renewals need procurement sign-off",
        "kind": "no_auto_renewal",
        "params": {},
        "severity": "low",
        "doc_types": ["contract"],
    },
    {
        "name": "Contracts of USD 50,000+ need CFO approval",
        "kind": "approval_threshold",
        "params": {"amount": 50000, "currency": "USD"},
        "severity": "medium",
    },
    {
        "name": "Liability must be capped",
        "kind": "required_clause",
        "params": {
            "clause": "Limitation of liability",
            "phrases": ["shall not exceed", "limitation of liability", "total liability"],
        },
        "severity": "high",
        "doc_types": ["contract"],
    },
    {
        "name": "No exclusivity or non-compete clauses",
        "kind": "prohibited_clause",
        "params": {"phrases": ["exclusiv", "non-compete", "shall not engage any other"]},
        "severity": "high",
    },
    {
        "name": "Give us at least 30 days to pay",
        "kind": "payment_terms",
        "params": {"min_days": 30, "max_days": 0},
        "severity": "medium",
        "doc_types": ["contract", "invoice"],
    },
    {
        "name": "Vendors handling personal data must sign a DPA",
        "description": "Checked by the AI when documents are analyzed in Claude mode.",
        "kind": "ai_instruction",
        "params": {
            "instruction": "If the vendor processes personal data (for example employee or driver information), "
            "the agreement must require or reference a data processing agreement (DPA)."
        },
        "severity": "medium",
    },
]
QUESTIONS = [
    "How much notice do we need to give to stop the Brightline subscription from renewing?",
    "Can we engage other routing consultants while the Apex project is running?",
    "When is the CloudPeak invoice due and what happens if we pay late?",
    "What security incident notification timelines do vendors have to meet?",
]


def main() -> None:
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"email": "demo@docpilot.example.com", "password": PASSWORD})
        if r.status_code == 200:
            print("Demo workspace already exists - nothing to do.")
            return
        reg = client.post(
            "/api/auth/register",
            json={
                "org_name": "Northwind Logistics",
                "name": "Dana Whitfield",
                "email": "demo@docpilot.example.com",
                "password": PASSWORD,
            },
        )
        reg.raise_for_status()
        h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        for name, email, role in (
            ("Sam Analyst", "analyst@docpilot.example.com", "member"),
            ("Alex Auditor", "auditor@docpilot.example.com", "viewer"),
        ):
            client.post(
                "/api/admin/users",
                headers=h,
                json={"name": name, "email": email, "password": PASSWORD, "role": role},
            ).raise_for_status()

        for rule in RULES:  # create the rulebook first so every upload is checked against it
            client.post("/api/rules", headers=h, json=rule).raise_for_status()
        print(f"created {len(RULES)} rulebook rules")

        uploaded: list[str] = []
        for path in sorted(SAMPLES.glob("*.md")):
            up = client.post(
                "/api/documents", headers=h, files={"file": (path.name, path.read_bytes(), "text/markdown")}
            )
            up.raise_for_status()
            uploaded.append(up.json()["id"])
            print(f"uploaded {path.name}")
        print(f"processed {drain()} jobs")

        with session_scope() as db:
            for doc_id, days in zip(uploaded, UPLOAD_DAYS_AGO, strict=False):
                doc = db.get(Document, doc_id)
                if doc:
                    doc.created_at = utcnow() - timedelta(days=days, hours=3)
                    doc.processed_at = doc.created_at + timedelta(seconds=4)

        for q in QUESTIONS:
            ans = client.post("/api/ask", headers=h, json={"question": q})
            ans.raise_for_status()
            print(f"Q: {q}\nA: {ans.json()['answer'][:160]}...\n")
        digest = client.post("/api/notifications/digest/send", headers=h).json()
        print(f"digest: {digest['subject']} [{digest['status']} via {digest['transport']}]")
        print("Seed complete. Log in as demo@docpilot.example.com /", PASSWORD)


if __name__ == "__main__":
    main()
