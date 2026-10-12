import pytest

from app.models import PlaybookRule
from app.schemas import Amount, DocumentInsights, PolicyCheck, RenewalTerms
from app.services.jobs import drain
from app.services.llm import get_provider
from app.services.rules import RuleValidationError, evaluate, validate_params
from tests.conftest import auth_headers, register, upload

TEXT = (
    "This Agreement will automatically renew unless 90 days' notice is given. "
    "Invoices are payable within 15 days. The Client shall not engage any other consultant (exclusivity). "
    "Total liability shall not exceed the fees paid."
)


def _insights(**kw) -> DocumentInsights:
    base = dict(
        doc_type="contract",
        title="T",
        summary="S",
        parties=[],
        key_dates=[],
        amounts=[],
        obligations=[],
        risks=[],
        overall_risk="medium",
    )
    base.update(kw)
    return DocumentInsights(**base)


def _rule(kind: str, **params) -> PlaybookRule:
    return PlaybookRule(
        id=kind,
        name=kind,
        kind=kind,
        params=validate_params(kind, params),
        severity="medium",
        doc_types=[],
        enabled=True,
    )


def _status(findings, rule_id):
    return next(f for f in findings if f["rule_id"] == rule_id)


def test_deterministic_rule_kinds():
    ins = _insights(
        renewal=RenewalTerms(auto_renews=True, term_end_date="2027-01-14", notice_days=90, source_quote="renew"),
        payment_terms_days=15,
        amounts=[
            Amount(label="Monthly fee", value=5000, currency="USD"),  # 60,000 / year
            Amount(label="Liability cap", value=1_000_000, currency="USD"),  # ignored
        ],
    )
    rules = [
        _rule("max_notice_days", days=60),
        _rule("no_auto_renewal"),
        _rule("payment_terms", min_days=30, max_days=0),
        _rule("approval_threshold", amount=50000, currency="usd"),
        _rule(
            "required_clause", clause="Limitation of liability", phrases=["total liability", "limitation of liability"]
        ),
        _rule("prohibited_clause", phrases="exclusivity, non-compete"),
    ]
    f = evaluate(rules, ins, TEXT, "demo")
    assert _status(f, "max_notice_days")["status"] == "fail" and "90 days" in _status(f, "max_notice_days")["message"]
    assert _status(f, "no_auto_renewal")["status"] == "fail"
    assert _status(f, "payment_terms")["status"] == "fail"
    assert "payable within 15 days" in _status(f, "payment_terms")["source_quote"]
    assert (
        _status(f, "approval_threshold")["status"] == "fail" and "60,000" in _status(f, "approval_threshold")["message"]
    )
    assert _status(f, "required_clause")["status"] == "pass"
    assert _status(f, "prohibited_clause")["status"] == "fail"
    assert [x["status"] for x in f][:5] == ["fail"] * 5  # failures sorted first


def test_rules_pass_on_clean_document_and_respect_doc_types():
    ins = _insights(doc_type="invoice", payment_terms_days=45)
    rules = [_rule("max_notice_days", days=60), _rule("payment_terms", min_days=30, max_days=60)]
    rules.append(_rule("required_clause", clause="Liability", phrases=["indemnify"]))
    rules[-1].doc_types = ["contract"]  # not applicable to invoices
    f = evaluate(rules, ins, "Net 45", "demo")
    assert [x["status"] for x in f] == ["pass", "pass"]


def test_ai_instruction_rule_status():
    rule = _rule("ai_instruction", instruction="Vendors processing personal data must reference a DPA.")
    demo = evaluate([rule], _insights(), TEXT, "demo")
    assert demo[0]["status"] == "not_evaluated" and "Claude" in demo[0]["message"]
    checked = _insights(
        policy_checks=[PolicyCheck(rule_id=rule.id, violated=True, explanation="No DPA referenced.", source_quote="")]
    )
    assert evaluate([rule], checked, TEXT, "claude")[0]["status"] == "fail"
    assert evaluate([rule], _insights(), TEXT, "claude")[0]["message"].startswith("Re-analyze")


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("payment_terms", {"min_days": 0, "max_days": 0}),
        ("required_clause", {"phrases": []}),
        ("approval_threshold", {"amount": -5}),
        ("ai_instruction", {"instruction": "short"}),
        ("not_a_kind", {}),
    ],
)
def test_invalid_rule_params(kind, params):
    with pytest.raises(RuleValidationError):
        validate_params(kind, params)


def test_rule_crud_rechecks_existing_documents(client):
    h = auth_headers(register(client))
    doc = upload(client, h, "01")
    drain()
    assert client.get(f"/api/documents/{doc['id']}", headers=h).json()["policy_violations"] == 0

    r = client.post(
        "/api/rules",
        headers=h,
        json={
            "name": "Notice period 60 days max",
            "kind": "max_notice_days",
            "params": {"days": 60},
            "severity": "high",
        },
    )
    assert r.status_code == 201
    rule = r.json()
    assert rule["violations"] == 1

    detail = client.get(f"/api/documents/{doc['id']}", headers=h).json()
    assert detail["policy_violations"] == 1
    assert detail["policy_findings"][0]["status"] == "fail"
    assert client.get("/api/documents?policy=violations", headers=h).json()["total"] == 1

    patched = client.patch(f"/api/rules/{rule['id']}", headers=h, json={"params": {"days": 120}}).json()
    assert patched["violations"] == 0 and patched["params"]["days"] == 120
    assert client.get("/api/documents?policy=compliant", headers=h).json()["total"] == 1

    assert client.patch(f"/api/rules/{rule['id']}", headers=h, json={"params": {"days": -1}}).status_code == 422
    assert client.delete(f"/api/rules/{rule['id']}", headers=h).status_code == 204
    assert client.get("/api/rules", headers=h).json() == []
    actions = [e["action"] for e in client.get("/api/admin/audit", headers=h).json()]
    assert {"rule.created", "rule.updated", "rule.deleted"} <= set(actions)


def test_rules_are_admin_only_and_tenant_scoped(client):
    admin = auth_headers(register(client))
    rule = client.post(
        "/api/rules", headers=admin, json={"name": "No auto renewals", "kind": "no_auto_renewal", "params": {}}
    ).json()
    client.post(
        "/api/admin/users",
        headers=admin,
        json={"name": "M", "email": "m@northwind.example.com", "password": "member-pass", "role": "member"},
    )
    member = auth_headers(
        client.post("/api/auth/login", json={"email": "m@northwind.example.com", "password": "member-pass"}).json()
    )
    assert client.get("/api/rules", headers=member).status_code == 200
    r = client.post("/api/rules", headers=member, json={"name": "x" * 5, "kind": "no_auto_renewal"})
    assert r.status_code == 403
    other = auth_headers(register(client, "o@other.example.com", "Other Co"))
    assert client.get("/api/rules", headers=other).json() == []
    assert client.delete(f"/api/rules/{rule['id']}", headers=other).status_code == 404
    assert client.get("/api/rules/kinds", headers=member).json()["ai_instruction"]["ai"] is True


def test_ai_rules_are_sent_to_the_model_during_processing(client, monkeypatch):
    h = auth_headers(register(client))
    rule = client.post(
        "/api/rules",
        headers=h,
        json={
            "name": "DPA required",
            "kind": "ai_instruction",
            "params": {"instruction": "Vendors that process personal data must reference a DPA."},
        },
    ).json()
    provider = get_provider()
    real = provider.extract
    seen = {}

    def extract(text, filename, policies=()):
        seen["policies"] = list(policies)
        result = real(text, filename, policies)
        result.insights.policy_checks = [
            PolicyCheck(rule_id=rule["id"], violated=True, explanation="No DPA referenced.", source_quote="")
        ]
        return result

    monkeypatch.setattr(provider, "extract", extract)
    doc = upload(client, h, "07")
    drain()
    assert [p.rule_id for p in seen["policies"]] == [rule["id"]]
    finding = client.get(f"/api/documents/{doc['id']}", headers=h).json()["policy_findings"][0]
    assert finding["status"] == "fail" and finding["message"] == "No DPA referenced."
