"""Claude implementation: structured extraction with JSON-schema outputs and cited Q&A."""

import json
import logging
from collections.abc import Sequence

import anthropic
from pydantic import ValidationError

from app.config import Settings
from app.schemas import INSIGHTS_JSON_SCHEMA, DocumentInsights
from app.services.llm.base import (
    CitedAnswer,
    Extraction,
    LLMError,
    LLMRefusal,
    PolicyInstruction,
    Source,
    Usage,
)

log = logging.getLogger(__name__)

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_MAX_DOC_CHARS = 600_000  # ~150k tokens; larger documents should be split, never silently truncated

EXTRACTION_SYSTEM = """You are a meticulous contracts and finance analyst. You read business documents \
(contracts, NDAs, invoices, policies) and extract the facts a busy operator needs.

Rules:
- Only report what the document actually says. Never invent parties, dates, amounts or clauses.
- Every `source_quote` must be copied verbatim from the document (a short, distinctive span).
- Dates must be ISO format (YYYY-MM-DD). Use an empty string if a date is relative or unclear.
- Amounts: numeric value plus ISO-4217 currency code (USD, CAD, EUR...).
- Risks are terms that could cost the reader money, time or leverage: auto-renewals, short notice \
windows, uncapped liability, broad indemnities, exclusivity, late fees, unilateral price changes, \
data-protection gaps. Rate severity from the reader's point of view.
- Keep the summary to 2-4 plain-English sentences.
- `renewal`: whether the agreement renews automatically, the ISO date the current term ends, how many \
days of notice are needed to stop the renewal, and the renewal term length in months (0 when not stated). \
If it does not auto-renew, set auto_renews=false and leave the other fields empty/0.
- `payment_terms_days`: how many days the payer has to pay an invoice (e.g. Net 30 -> 30; 0 if not stated).
- `policy_checks`: only when company policies are provided. Return exactly one entry per policy, using its \
id; set violated=true only when the document clearly conflicts with the policy, explain why in one \
sentence, and quote the relevant clause (empty string if the problem is something missing). When no \
policies are provided, return an empty list."""

ANSWER_SYSTEM = """You answer questions about a company's documents using only the provided sources. \
Cite the sources that support each statement. If the sources do not contain the answer, say so plainly \
instead of guessing. Be concise and specific: quote numbers, dates and party names exactly."""


class ClaudeProvider:
    name = "claude"

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        # Credentials resolve from the environment (ANTHROPIC_API_KEY or an `ant auth login` profile).
        self.client = client or anthropic.Anthropic(timeout=settings.llm_timeout_seconds, max_retries=2)
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.use_fallback = settings.llm_refusal_fallback and self.model in _FALLBACK_MODELS

    # -- transport ---------------------------------------------------------------------------

    def _create(self, **kwargs):
        try:
            if self.use_fallback:
                # On a policy decline the API re-runs the request on a suitable fallback model.
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            return self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Rate limited by Anthropic API: {exc.message}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409)
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}", retryable=retryable) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise LLMError(f"Could not reach Anthropic API: {exc}", retryable=True) from exc

    @staticmethod
    def _check_stop(response) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefusal(f"Model declined the request (category: {category or 'unspecified'})")
        if response.stop_reason == "max_tokens":
            raise LLMError("Model output hit max_tokens before finishing", retryable=False)

    def _usage(self, response) -> Usage:
        return Usage(
            model=getattr(response, "model", None) or self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    # -- operations --------------------------------------------------------------------------

    def extract(self, text: str, filename: str, policies: Sequence[PolicyInstruction] = ()) -> Extraction:
        if len(text) > _MAX_DOC_CHARS:
            raise LLMError(
                f"Document is {len(text):,} characters; the limit for single-pass extraction is "
                f"{_MAX_DOC_CHARS:,}. Split it into parts.",
                retryable=False,
            )
        prompt = f'<document filename="{filename}">\n{text}\n</document>\n\n'
        if policies:
            listed = "\n".join(f'<policy id="{p.rule_id}">{p.instruction}</policy>' for p in policies)
            prompt += f"<company_policies>\n{listed}\n</company_policies>\n\n"
        prompt += "Extract the structured insights for this document."
        response = self._create(
            model=self.model,
            max_tokens=16000,
            system=EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": INSIGHTS_JSON_SCHEMA},
            },
        )
        self._check_stop(response)
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            insights = DocumentInsights.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            # Rare with structured outputs, but business-rule validators can still reject values.
            raise LLMError(f"Model output failed validation: {exc}", retryable=True) from exc
        # Keep only checks for policies we actually asked about.
        asked = {p.rule_id for p in policies}
        insights.policy_checks = [c for c in insights.policy_checks if c.rule_id in asked]
        return Extraction(insights=insights, usage=self._usage(response))

    def answer(self, question: str, sources: list[Source]) -> CitedAnswer:
        if not sources:
            return CitedAnswer(answer="I couldn't find anything relevant in your documents.", usage=None)
        documents = [
            {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": s.text},
                "title": f"{s.document_title} - section {s.chunk_index + 1}",
                "citations": {"enabled": True},
            }
            for s in sources
        ]
        response = self._create(
            model=self.model,
            max_tokens=4000,
            system=ANSWER_SYSTEM,
            messages=[{"role": "user", "content": [*documents, {"type": "text", "text": question}]}],
            output_config={"effort": self.effort},
        )
        self._check_stop(response)

        parts: list[str] = []
        citations: list[tuple[int, str]] = []
        for block in response.content:
            if block.type != "text":
                continue
            parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                doc_index = getattr(cit, "document_index", None)
                if doc_index is None or doc_index >= len(sources):
                    continue
                ref = sources[doc_index].ref
                citations.append((ref, getattr(cit, "cited_text", "")))
                parts.append(f" [{ref}]")
        answer = "".join(parts).strip()
        return CitedAnswer(answer=answer, citations=citations, usage=self._usage(response))
