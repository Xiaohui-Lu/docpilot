"""Provider-agnostic LLM interface used by the pipeline and the Q&A endpoint."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.schemas import DocumentInsights

# USD per 1M tokens (input, output). Used for cost dashboards; update when pricing changes.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


class LLMError(Exception):
    """An LLM call failed. ``retryable`` tells the job queue whether to try again."""

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class LLMRefusal(LLMError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICING.get(self.model, (0.0, 0.0))
        return round(self.input_tokens / 1e6 * price_in + self.output_tokens / 1e6 * price_out, 6)


@dataclass
class Source:
    """A retrieved chunk handed to the model as citable context."""

    ref: int  # 1-based reference number shown to users as [n]
    document_id: str
    document_title: str
    chunk_id: str
    chunk_index: int
    text: str


@dataclass
class CitedAnswer:
    answer: str
    citations: list[tuple[int, str]] = field(default_factory=list)  # (source ref, quoted text)
    usage: Usage | None = None


@dataclass(frozen=True)
class PolicyInstruction:
    """A natural-language company rule the model must evaluate during extraction."""

    rule_id: str
    instruction: str


@dataclass
class Extraction:
    insights: DocumentInsights
    usage: Usage


class LLMProvider(Protocol):
    name: str
    model: str

    def extract(self, text: str, filename: str, policies: Sequence[PolicyInstruction] = ()) -> Extraction: ...

    def answer(self, question: str, sources: list[Source]) -> CitedAnswer: ...
