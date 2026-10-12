"""Pydantic schemas: API contracts and the validated LLM extraction schema."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["admin", "member", "viewer"]
RiskLevel = Literal["low", "medium", "high"]
DocType = Literal["contract", "nda", "invoice", "policy", "other"]


# ---------------------------------------------------------------------------
# LLM extraction schema - the contract between the model and the application.
# Every response is validated against this before it is stored.
# ---------------------------------------------------------------------------


def _iso_or_empty(v: str) -> str:
    if v and not (len(v) == 10 and v[4] == "-" and v[7] == "-"):
        raise ValueError("date must be YYYY-MM-DD or empty")
    return v


class Party(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(max_length=100, description="e.g. Client, Vendor, Licensor, Employee")


class KeyDate(BaseModel):
    label: str = Field(max_length=120)
    date: str = Field(description="ISO date YYYY-MM-DD, or empty string if not determinable")
    source_quote: str = Field(max_length=400, description="Verbatim text from the document")

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return _iso_or_empty(v)


class Amount(BaseModel):
    label: str = Field(max_length=120)
    value: float
    currency: str = Field(min_length=3, max_length=3)


class Risk(BaseModel):
    severity: RiskLevel
    title: str = Field(max_length=120)
    explanation: str = Field(max_length=600)
    source_quote: str = Field(max_length=400, description="Verbatim text from the document")


class RenewalTerms(BaseModel):
    """What it takes to stop the agreement from rolling over - the basis for 'cancel by' alerts."""

    auto_renews: bool = False
    term_end_date: str = Field(default="", description="ISO date the current term ends, or empty")
    notice_days: int = Field(default=0, ge=0, le=730, description="Days of notice needed to cancel; 0 if none")
    renewal_term_months: int = Field(default=0, ge=0, le=120)
    source_quote: str = Field(default="", max_length=400)

    @field_validator("term_end_date")
    @classmethod
    def _date(cls, v: str) -> str:
        return _iso_or_empty(v)


class PolicyCheck(BaseModel):
    """Result of a company rulebook instruction evaluated by the model."""

    rule_id: str = Field(max_length=64)
    violated: bool
    explanation: str = Field(max_length=600)
    source_quote: str = Field(default="", max_length=400)


class DocumentInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    title: str = Field(max_length=200)
    summary: str = Field(max_length=1200)
    parties: list[Party] = Field(max_length=20)
    key_dates: list[KeyDate] = Field(max_length=30)
    amounts: list[Amount] = Field(max_length=30)
    obligations: list[str] = Field(max_length=30)
    risks: list[Risk] = Field(max_length=20)
    overall_risk: RiskLevel
    renewal: RenewalTerms = Field(default_factory=RenewalTerms)
    payment_terms_days: int = Field(default=0, ge=0, le=365, description="Days to pay invoices; 0 if not stated")
    policy_checks: list[PolicyCheck] = Field(default_factory=list, max_length=50)


def _strict(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(obj), "properties": obj}


# Hand-written JSON Schema for Claude structured outputs (flat, no $refs).
INSIGHTS_JSON_SCHEMA: dict[str, Any] = _strict(
    {
        "doc_type": {"type": "string", "enum": ["contract", "nda", "invoice", "policy", "other"]},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "parties": {
            "type": "array",
            "items": _strict({"name": {"type": "string"}, "role": {"type": "string"}}),
        },
        "key_dates": {
            "type": "array",
            "items": _strict(
                {"label": {"type": "string"}, "date": {"type": "string"}, "source_quote": {"type": "string"}}
            ),
        },
        "amounts": {
            "type": "array",
            "items": _strict(
                {"label": {"type": "string"}, "value": {"type": "number"}, "currency": {"type": "string"}}
            ),
        },
        "obligations": {"type": "array", "items": {"type": "string"}},
        "risks": {
            "type": "array",
            "items": _strict(
                {
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source_quote": {"type": "string"},
                }
            ),
        },
        "overall_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "renewal": _strict(
            {
                "auto_renews": {"type": "boolean"},
                "term_end_date": {"type": "string"},
                "notice_days": {"type": "integer"},
                "renewal_term_months": {"type": "integer"},
                "source_quote": {"type": "string"},
            }
        ),
        "payment_terms_days": {"type": "integer"},
        "policy_checks": {
            "type": "array",
            "items": _strict(
                {
                    "rule_id": {"type": "string"},
                    "violated": {"type": "boolean"},
                    "explanation": {"type": "string"},
                    "source_quote": {"type": "string"},
                }
            ),
        },
    }
)


# ---------------------------------------------------------------------------
# API schemas
# ---------------------------------------------------------------------------


class RegisterIn(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: Role
    org_id: str
    created_at: datetime
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    org_name: str


class UserCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: Role = "member"


class RoleUpdateIn(BaseModel):
    role: Role


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None
    title: str | None
    doc_type: str | None
    overall_risk: str | None
    page_count: int
    created_at: datetime
    processed_at: datetime | None
    processing_ms: int | None
    llm_provider: str | None
    llm_model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    policy_violations: int = 0


class DocumentDetailOut(DocumentOut):
    insights: dict[str, Any] | None
    grounding: dict[str, Any] | None
    policy_findings: list[dict[str, Any]] | None = None
    text: str
    jobs: list["JobOut"] = []


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    document_id: str | None = None


class Citation(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    chunk_index: int
    quote: str


class AskOut(BaseModel):
    id: str
    answer: str
    citations: list[Citation]
    provider: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_email: str | None
    action: str
    target: str | None
    detail: dict[str, Any]
    created_at: datetime


DocumentDetailOut.model_rebuild()


# ---------------------------------------------------------------------------
# Company rulebook
# ---------------------------------------------------------------------------

RuleKind = Literal[
    "max_notice_days",
    "no_auto_renewal",
    "payment_terms",
    "approval_threshold",
    "required_clause",
    "prohibited_clause",
    "ai_instruction",
]


class RuleIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)
    kind: RuleKind
    params: dict[str, Any] = Field(default_factory=dict)
    severity: RiskLevel = "medium"
    doc_types: list[DocType] = Field(default_factory=list, description="Empty = applies to every type")
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    params: dict[str, Any] | None = None
    severity: RiskLevel | None = None
    doc_types: list[DocType] | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    kind: str
    params: dict[str, Any]
    severity: str
    doc_types: list[str]
    enabled: bool
    created_at: datetime
    violations: int = 0
    not_evaluated: int = 0


# ---------------------------------------------------------------------------
# Deadlines & notifications
# ---------------------------------------------------------------------------


class DeadlineHandleIn(BaseModel):
    document_id: str
    key: str = Field(min_length=3, max_length=200)
    note: str = Field(default="", max_length=500)


class NotificationSettingsIn(BaseModel):
    digest_enabled: bool
    digest_weekday: int = Field(ge=0, le=6, description="0 = Monday")
    digest_lead_days: int = Field(ge=7, le=365)
    recipient_user_ids: list[str] = Field(default_factory=list)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    subject: str
    recipients: list[str]
    item_count: int
    transport: str
    status: str
    error: str | None
    created_at: datetime
