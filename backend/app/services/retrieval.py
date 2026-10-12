"""BM25 keyword retrieval over a tenant's chunks.

BM25 needs no embedding model or API key, is deterministic and works well for contract language
(names, clause titles, defined terms). The interface is deliberately small so it can be swapped for
pgvector / hybrid search without touching callers.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document

_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
# fmt: off
_STOP = frozenset((
    "a an and are as at be by can could do does for from has have how if in into is it its may might "
    "much need of on or our shall should that the their they this to us was we were what when where "
    "which who will with would you your any all"
).split())
# fmt: on
_SUFFIXES = ("ations", "ation", "ings", "ing", "ies", "ied", "als", "al", "ed", "es", "s", "ly")


def stem(token: str) -> str:
    """Tiny suffix-stripping stemmer: renewal/renewing/renews -> renew. Good enough for keyword recall."""
    if token.isdigit() or len(token) <= 4:
        return token
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            token = token[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
            break
    # engage/engaging -> engag, notice/noticed -> notic
    return token[:-1] if token.endswith("e") and len(token) > 5 else token


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass
class ScoredChunk:
    chunk: Chunk
    document_title: str
    score: float


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.lengths = [len(d) for d in docs]
        self.avgdl = (sum(self.lengths) / len(docs)) if docs else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def score(self, query: list[str], i: int) -> float:
        tf, dl = self.tf[i], self.lengths[i]
        s = 0.0
        for term in query:
            f = tf.get(term)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / denom
        return s


def search_chunks(
    db: Session, org_id: str, query: str, top_k: int = 6, document_id: str | None = None
) -> list[ScoredChunk]:
    stmt = (
        select(Chunk, Document.title, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.org_id == org_id, Document.status == "ready")
    )
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
    rows = db.execute(stmt).all()
    if not rows:
        return []
    corpus = [tokenize(r.Chunk.text) for r in rows]
    bm25 = BM25(corpus)
    q = tokenize(query)
    scored = [
        ScoredChunk(chunk=r.Chunk, document_title=r.title or r.filename, score=bm25.score(q, i))
        for i, r in enumerate(rows)
    ]
    scored = [s for s in scored if s.score > 0]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]
