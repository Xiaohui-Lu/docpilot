"""Claude provider tests against a fake client - no network, no API key, no cost."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.services.llm.base import LLMError, LLMRefusal, Source
from app.services.llm.claude import ClaudeProvider

VALID = {
    "doc_type": "contract",
    "title": "MSA",
    "summary": "A subscription agreement.",
    "parties": [{"name": "Northwind Logistics Ltd.", "role": "Customer"}],
    "key_dates": [{"label": "End", "date": "2027-01-14", "source_quote": "ends on January 14, 2027"}],
    "amounts": [{"label": "Annual fee", "value": 48000, "currency": "USD"}],
    "obligations": ["Pay within 30 days"],
    "risks": [
        {
            "severity": "medium",
            "title": "Auto-renewal",
            "explanation": "Renews yearly.",
            "source_quote": "will automatically renew",
        }
    ],
    "overall_risk": "medium",
}


def _response(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=None,
        model=model,
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
    )


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _provider(result, **settings) -> tuple[ClaudeProvider, FakeMessages]:
    fake = FakeMessages(result)
    client = SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake))
    return ClaudeProvider(Settings(llm_provider="claude", **settings), client=client), fake


def _api_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


def test_extract_sends_schema_and_validates():
    provider, fake = _provider(_response([SimpleNamespace(type="text", text=json.dumps(VALID))]))
    result = provider.extract("doc text", "msa.pdf")
    assert result.insights.title == "MSA"
    assert result.usage.input_tokens == 1200
    assert result.usage.cost_usd == pytest.approx(1200 / 1e6 * 4 + 300 / 1e6 * 20)

    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["effort"] == "medium"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in call  # Opus 5.5: thinking is always on; depth is controlled by effort


def test_fallback_can_be_disabled():
    provider, fake = _provider(
        _response([SimpleNamespace(type="text", text=json.dumps(VALID))]), llm_refusal_fallback=False
    )
    provider.extract("doc", "a.txt")
    assert "fallbacks" not in fake.calls[0]


def test_invalid_model_output_is_retryable():
    bad = {**VALID, "overall_risk": "catastrophic"}
    provider, _ = _provider(_response([SimpleNamespace(type="text", text=json.dumps(bad))]))
    with pytest.raises(LLMError) as exc:
        provider.extract("doc", "a.txt")
    assert exc.value.retryable


def test_refusal_is_not_retryable():
    provider, _ = _provider(_response([], stop_reason="refusal"))
    with pytest.raises(LLMRefusal) as exc:
        provider.extract("doc", "a.txt")
    assert not exc.value.retryable


def test_error_mapping():
    p, _ = _provider(_api_error(anthropic.RateLimitError, 429))
    with pytest.raises(LLMError) as exc:
        p.extract("doc", "a.txt")
    assert exc.value.retryable

    p, _ = _provider(_api_error(anthropic.BadRequestError, 400))
    with pytest.raises(LLMError) as exc:
        p.extract("doc", "a.txt")
    assert not exc.value.retryable

    p, _ = _provider(_api_error(anthropic.InternalServerError, 529))
    with pytest.raises(LLMError) as exc:
        p.extract("doc", "a.txt")
    assert exc.value.retryable


def test_oversized_document_is_rejected_not_truncated():
    provider, fake = _provider(_response([]))
    with pytest.raises(LLMError) as exc:
        provider.extract("x" * 700_000, "huge.txt")
    assert not exc.value.retryable and not fake.calls


def test_answer_maps_citations_to_sources():
    cit = SimpleNamespace(type="char_location", document_index=1, cited_text="90 days' prior written notice")
    content = [
        SimpleNamespace(type="text", text="You must give ", citations=None),
        SimpleNamespace(type="text", text="90 days' notice before the term ends", citations=[cit]),
        SimpleNamespace(type="text", text=".", citations=None),
    ]
    provider, fake = _provider(_response(content))
    sources = [
        Source(ref=1, document_id="d1", document_title="Invoice", chunk_id="c1", chunk_index=0, text="..."),
        Source(
            ref=2,
            document_id="d2",
            document_title="MSA",
            chunk_id="c2",
            chunk_index=3,
            text="... 90 days ...",
        ),
    ]
    result = provider.answer("How much notice?", sources)
    assert result.answer == "You must give 90 days' notice before the term ends [2]."
    assert result.citations == [(2, "90 days' prior written notice")]
    docs = [b for b in fake.calls[0]["messages"][0]["content"] if b["type"] == "document"]
    assert len(docs) == 2 and all(d["citations"] == {"enabled": True} for d in docs)


def test_policies_are_sent_and_unknown_checks_dropped():
    from app.services.llm.base import PolicyInstruction

    payload = {
        **VALID,
        "renewal": {
            "auto_renews": True,
            "term_end_date": "2027-01-14",
            "notice_days": 90,
            "renewal_term_months": 12,
            "source_quote": "will automatically renew",
        },
        "payment_terms_days": 30,
        "policy_checks": [
            {"rule_id": "r1", "violated": True, "explanation": "No DPA.", "source_quote": ""},
            {"rule_id": "made-up", "violated": True, "explanation": "?", "source_quote": ""},
        ],
    }
    provider, fake = _provider(_response([SimpleNamespace(type="text", text=json.dumps(payload))]))
    result = provider.extract("doc", "a.txt", [PolicyInstruction("r1", "Must reference a DPA.")])
    prompt = fake.calls[0]["messages"][0]["content"]
    assert '<policy id="r1">Must reference a DPA.</policy>' in prompt
    assert [c.rule_id for c in result.insights.policy_checks] == ["r1"]
    assert result.insights.renewal.notice_days == 90
    schema = fake.calls[0]["output_config"]["format"]["schema"]
    assert {"renewal", "payment_terms_days", "policy_checks"} <= set(schema["required"])


def test_messy_output_is_normalized_not_rejected():
    from app.schemas import DocumentInsights

    messy = {
        **VALID,
        "key_dates": [{"label": "End", "date": "2027-01-14T00:00:00Z", "source_quote": "x" * 900}],
        "amounts": [{"label": "Fee", "value": 10, "currency": " usd "}],
        "risks": VALID["risks"] * 25,
        "renewal": {
            "auto_renews": True,
            "term_end_date": "end of next year",
            "notice_days": 9999,
            "renewal_term_months": 12,
            "source_quote": "",
        },
        "payment_terms_days": -5,
        "policy_checks": [],
    }
    ins = DocumentInsights.model_validate(messy)
    assert ins.key_dates[0].date == "2027-01-14" and len(ins.key_dates[0].source_quote) == 400
    assert ins.amounts[0].currency == "USD"
    assert len(ins.risks) == 20
    assert ins.renewal.term_end_date == "" and ins.renewal.notice_days == 730
    assert ins.payment_terms_days == 0
