"""Offline, deterministic provider.

Lets the whole product run (and be tested end-to-end in CI) with no API key and zero cost. It uses
transparent rules - regexes for dates, amounts and parties plus a clause-risk rulebook - so it is
far less capable than Claude, but it produces output in exactly the same validated schema.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from app.schemas import Amount, DocumentInsights, KeyDate, Party, RenewalTerms, Risk
from app.services.llm.base import CitedAnswer, Extraction, PolicyInstruction, Source, Usage
from app.services.retrieval import tokenize

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_PATTERNS = [
    (re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}}),\s*(\d{{4}})\b"), "mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\.?\s+(\d{{4}})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_AMOUNT = re.compile(r"(USD|CAD|EUR|GBP|US\$|C\$|\$|€|£)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
_CURRENCY = {
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "CAD": "CAD",
    "C$": "CAD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
}
_PARTY = re.compile(r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)\s*\((?:the\s+)?[\"“']([A-Z][A-Za-z ]{1,30})[\"”']\)")
_NOT_PARTY_ROLES = {
    "agreement",
    "effective date",
    "purpose",
    "party",
    "parties",
    "lease",
    "premises",
    "services",
    "confidential information",
    "term",
    "subscription term",
    "deliverables",
    "policy",
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])|\n+")

# (pattern, severity, title, explanation)
_RISK_RULES: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(
            r"unlimited liability|liability[^.]{0,60}(?:shall|will) not be limited"
            r"|without limitation of liability",
            re.I,
        ),
        "high",
        "Uncapped liability",
        "Liability is not capped, so a single claim could exceed the value of the whole agreement.",
    ),
    (
        re.compile(r"exclusiv|shall not (?:engage|work with|compete)|non-compete", re.I),
        "high",
        "Exclusivity / non-compete",
        "Restricts working with other providers or competitors, reducing leverage.",
    ),
    (
        re.compile(r"personally guaranteed|personal guarantee", re.I),
        "high",
        "Personal guarantee",
        "An individual is personally on the hook for the company's obligations.",
    ),
    (
        re.compile(r"automatically renew|auto-renew|renew automatically", re.I),
        "medium",
        "Automatic renewal",
        "The agreement renews unless notice is given in time; missing the window locks in another term.",
    ),
    (
        re.compile(r"increase (?:the )?(?:fees|prices|rates)|price (?:adjustment|increase)", re.I),
        "medium",
        "Unilateral price increase",
        "The counterparty may raise prices during the term.",
    ),
    (
        re.compile(r"indemnif", re.I),
        "medium",
        "Indemnification obligation",
        "One party must cover the other's losses; check that it is mutual and capped.",
    ),
    (
        re.compile(r"terminate[^.]{0,80}for convenience", re.I),
        "medium",
        "Termination for convenience",
        "A party can exit without cause; confirm notice periods and refund of prepaid fees.",
    ),
    (
        re.compile(r"in perpetuity|perpetual", re.I),
        "medium",
        "Perpetual obligation",
        "An obligation that never expires can outlive the business relationship.",
    ),
    (
        re.compile(r"personal (?:data|information)", re.I),
        "medium",
        "Personal data processing",
        "Personal data is in scope; a data processing agreement and security terms should be in place.",
    ),
    (
        re.compile(r"late (?:fee|payment|charge)|interest (?:at|of) \d+(?:\.\d+)?\s?%", re.I),
        "low",
        "Late payment penalties",
        "Late payments accrue fees or interest.",
    ),
    (
        re.compile(r"shall not solicit|non-solicitation", re.I),
        "low",
        "Non-solicitation",
        "Limits hiring people from the other party; check the duration and scope.",
    ),
    (
        re.compile(r"(?:liability|damages)[^.]{0,120}shall not exceed", re.I),
        "low",
        "Liability cap",
        "Recoverable damages are capped; make sure the cap is proportionate to the risk.",
    ),
]


_ABBREV_END = re.compile(r"\b(?:Ltd|Inc|Corp|Co|LLC|LLP|No|St|Mr|Ms|Dr|Jr|Sr|vs|e\.g|i\.e)\.$")


def _sentences(text: str) -> list[str]:
    """Split into sentences, attaching short inline headings ("5. Intellectual Property.") to what follows."""
    out: list[str] = []
    carry = ""
    for raw in _SENTENCE.split(text):
        s = raw.strip()
        if len(s) <= 3 or s.startswith("#"):
            continue
        if len(s) < 30 and not s.startswith(("|", "*")):
            carry = f"{carry} {s}".strip()
            continue
        s = f"{carry} {s}".strip() if carry else s
        carry = ""
        if out and _ABBREV_END.search(out[-1]):  # "Northwind Logistics Ltd." is not a sentence end
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    if carry:
        out.append(carry)
    return out


_BOUNDARY = re.compile(r"\n|[.!?](?=\s)")
_CLAUSE_NO = re.compile(r"^(?:#+\s*)?(?:\d+(?:\.\d+)*\.?\s+)")


def _sentence_at(text: str, pos: int) -> str:
    """The sentence containing ``pos``. Periods inside clause numbers like "3.2" are not boundaries."""
    start = 0
    for m in _BOUNDARY.finditer(text, max(0, pos - 600), pos):
        start = m.end()
    m = _BOUNDARY.search(text, pos)
    end = m.end() if m else len(text)
    # Inline headings ("4. Exclusivity. During the term ...") - include the sentence that follows.
    while len(_CLAUSE_NO.sub("", text[start:end].strip())) < 30 and end < len(text) and text[end - 1] != "\n":
        m = _BOUNDARY.search(text, end + 1)
        end = m.end() if m else len(text)
    return _CLAUSE_NO.sub("", text[start:end].strip())[:380]


_AUTO_RENEW = re.compile(r"automatically renew|auto-renew|renew automatically", re.I)
_NOTICE = re.compile(r"\(?(\d{1,3})\)?\s*days'?\s*(?:prior\s+)?(?:written\s+)?notice", re.I)
_TERM_MONTHS = re.compile(r"\((\d{1,3})\)\s*month|(\d{1,3})[- ]month\s+term", re.I)


def _renewal_terms(text: str, key_dates: list[KeyDate]) -> RenewalTerms:
    auto = _AUTO_RENEW.search(text)
    if not auto:
        return RenewalTerms()
    sentence = _sentence_at(text, auto.start())
    # Prefer the notice period stated in the renewal clause itself.
    notice = _NOTICE.search(sentence) or next(
        (m for m in _NOTICE.finditer(text) if "renew" in _sentence_at(text, m.start()).lower()), None
    )
    months = _TERM_MONTHS.search(sentence)
    end = next((d.date for d in key_dates if d.label.startswith("Expiration") and d.date), "")
    return RenewalTerms(
        auto_renews=True,
        term_end_date=end,
        notice_days=int(notice[1]) if notice else 0,
        renewal_term_months=int(months[1] or months[2]) if months else 0,
        source_quote=sentence,
    )


def _payment_terms_days(text: str) -> int:
    m = re.search(r"\bnet\s*(\d{1,3})\b", text, re.I) or re.search(r"payable\s+within\s+(\d{1,3})\s*days", text, re.I)
    return int(m[1]) if m else 0


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _summarize(
    doc_type: str,
    parties: list[Party],
    key_dates: list[KeyDate],
    amounts: list[Amount],
    risks: list[Risk],
    sentences: list[str],
) -> str:
    """Template summary built from the extracted facts (the LLM writes free prose instead)."""
    kind = {"nda": "Non-disclosure agreement", "other": "Document"}.get(doc_type, doc_type.capitalize())
    who = " and ".join(f"{p.name.rstrip('.')} ({p.role})" for p in parties[:2])
    parts = [f"{kind} between {who}." if who else f"{kind}."]
    if not parties:  # policies etc.: use the scope sentence
        scope = next((s for s in sentences if re.search(r"\b(applies|purpose|scope)\b", s, re.I)), None)
        if scope:
            scope = re.sub(r"^[A-Z][\w ]{0,25}\.\s+", "", _CLAUSE_NO.sub("", scope))  # drop inline heading
            parts.append(scope[:240].rstrip(".") + ".")
    if amounts:
        top = max(amounts, key=lambda a: a.value if a.label != "Insurance minimum" else 0)
        parts.append(f"Headline amount: {top.currency} {top.value:,.2f} ({top.label.lower()}).")
    dated = [d for d in key_dates if d.date]
    if dated:
        shown = ", ".join(f"{d.label.lower()} {d.date}" for d in dated[:3])
        parts.append(f"Key dates: {shown}.")
    if risks:
        top_risks = sorted(risks, key=lambda r: ("high", "medium", "low").index(r.severity))[:2]
        parts.append(
            f"{_plural(len(risks), 'potential risk')} flagged, led by "
            + " and ".join(r.title.lower() for r in top_risks)
            + "."
        )
    else:
        parts.append("No risky clauses detected.")
    return " ".join(parts)[:1100]


def _is_heading(text: str, pos: int) -> bool:
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line = text[line_start : line_end if line_end != -1 else len(text)].strip()
    return line.startswith("#") or len(line) < 40


_MONTH_NUM = {
    m: i
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}


def _parse_date(match: re.Match[str], kind: str) -> str:
    try:
        if kind == "iso":
            year, month, day = int(match[1]), int(match[2]), int(match[3])
        elif kind == "mdy":
            month, day, year = _MONTH_NUM[match[1][:3].lower()], int(match[2]), int(match[3])
        else:
            day, month, year = int(match[1]), _MONTH_NUM[match[2][:3].lower()], int(match[3])
        return datetime(year, month, day).date().isoformat()
    except (ValueError, KeyError):
        return ""


_DATE_LABELS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("due date", "payable", "due on", "due by"), "Payment due"),
    (("invoice date", "issued"), "Issue date"),
    (("expir", "ends on", "ending on", "end date", "terminates on"), "Expiration / end date"),
    (("no later than", "notice"), "Notice deadline"),
    (("renew",), "Renewal date"),
    (("commenc", "begins on", "start"), "Start date"),
    (("delivered by", "deliver by", "closes on", "deadline"), "Deadline"),
    (("review",), "Review date"),
    (("approved",), "Approval date"),
    (("effective",), "Effective date"),
    (("entered into", "made on", "dated", "signed"), "Signing date"),
)


def _label_from(context: str, table: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    for keys, label in table:
        if any(k in context for k in keys):
            return label
    return None


def _date_label(text: str, pos: int) -> str:
    near = text[max(0, pos - 45) : pos].lower()
    sentence = _sentence_at(text, pos).lower()
    return _label_from(near, _DATE_LABELS) or _label_from(sentence, _DATE_LABELS) or "Date"


_AMOUNT_LABELS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("total amount due", "total due", "amount due", "balance due"), "Total due"),
    (("tax", "hst", "vat"), "Tax"),
    (("subtotal",), "Subtotal"),
    (("operating cost",), "Operating costs"),
    (("late fee", "late charge"), "Late fee"),
    (("insurance",), "Insurance minimum"),
    (("deposit",), "Deposit"),
    (("exceed", "liabil", "cap"), "Liability cap"),
    (("monthly", "per month"), "Monthly fee"),
    (("annual", "per year", "yearly"), "Annual fee"),
    (("daily rate", "hourly rate", "rate of"), "Rate"),
    (("expenses",), "Expense threshold"),
    (("fee", "price"), "Fee"),
)


def _amount_label(text: str, pos: int) -> str:
    near = text[max(0, pos - 50) : pos].lower()
    line = text[text.rfind("\n", 0, pos) + 1 : pos]
    if line.lstrip().startswith("|"):
        return "Line item"
    return _label_from(near, _AMOUNT_LABELS) or _label_from(_sentence_at(text, pos).lower(), _AMOUNT_LABELS) or "Amount"


def _doc_type(text: str) -> str:
    t = text.lower()
    if "non-disclosure" in t or "nondisclosure" in t or "confidentiality agreement" in t:
        return "nda"
    if "invoice" in t[:400] or ("amount due" in t and "bill to" in t):
        return "invoice"
    if "policy" in t[:300]:
        return "policy"
    if "agreement" in t or "contract" in t:
        return "contract"
    return "other"


class DemoProvider:
    name = "demo"
    model = "demo-rules-v1"

    def extract(self, text: str, filename: str, policies: Sequence[PolicyInstruction] = ()) -> Extraction:
        lines = [ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()]
        title = (lines[0] if lines else filename)[:200]
        doc_type = _doc_type(text)
        if doc_type == "invoice":
            number = re.search(r"invoice\s*(?:number|no\.?|#)\s*:?\s*([A-Z0-9-]{3,})", text, re.I)
            vendor = re.search(r"^from:\s*(.+)$", text, re.I | re.M)
            if number:
                title = f"Invoice {number[1]}" + (f" from {vendor[1].strip().rstrip('.')}" if vendor else "")

        parties: list[Party] = []
        seen: set[str] = set()
        for m in _PARTY.finditer(text):
            name = re.sub(r"^(?:and|between|by|This Agreement is entered into by)\s+", "", m[1].strip(" ,"), flags=re.I)
            name = re.sub(r".*\bbetween\s+", "", name, flags=re.I).strip(" ,")
            role = m[2].strip()
            if (
                role.lower() in _NOT_PARTY_ROLES
                or name.lower().startswith("this ")
                or re.search(r"\b(19|20)\d{2}\b", name)
            ):
                continue
            if name.lower() not in seen and len(parties) < 6:
                seen.add(name.lower())
                parties.append(Party(name=name, role=role))
        if doc_type == "invoice":
            for label, role in (("from", "Vendor"), ("bill to", "Customer")):
                m = re.search(rf"^{label}:\s*(.+)$", text, re.I | re.M)
                if m and m[1].strip().lower() not in seen:
                    parties.append(Party(name=m[1].strip()[:200], role=role))

        key_dates: list[KeyDate] = []
        seen_dates: set[tuple[str, str]] = set()
        for pattern, kind in _DATE_PATTERNS:
            for m in pattern.finditer(text):
                iso = _parse_date(m, kind)
                sentence = _sentence_at(text, m.start())
                label = _date_label(text, m.start())
                if iso and (label, iso) not in seen_dates and len(key_dates) < 12:
                    seen_dates.add((label, iso))
                    key_dates.append(KeyDate(label=label, date=iso, source_quote=sentence))

        amounts: list[Amount] = []
        seen_amounts: set[tuple[str, float]] = set()
        default_ccy = re.search(r"\b(USD|CAD|EUR|GBP)\b", text)
        for m in _AMOUNT.finditer(text):
            label = _amount_label(text, m.start())
            value = float(m[2].replace(",", ""))
            currency = default_ccy[1] if m[1] == "$" and default_ccy else _CURRENCY[m[1]]
            if label == "Line item" or (label, value) in seen_amounts or len(amounts) >= 12:
                continue
            seen_amounts.add((label, value))
            amounts.append(Amount(label=label, value=value, currency=currency))

        sentences = _sentences(text)
        obligations = [s[:300] for s in sentences if re.search(r"\b(shall|must|agrees to|is responsible for)\b", s)][:8]

        risks: list[Risk] = []
        for pattern, severity, rtitle, explanation in _RISK_RULES:
            # Quote the clause itself, not a section heading that happens to match.
            m = next((x for x in pattern.finditer(text) if not _is_heading(text, x.start())), None)
            if m:
                risks.append(
                    Risk(
                        severity=severity,
                        title=rtitle,
                        explanation=explanation,
                        source_quote=_sentence_at(text, m.start()),
                    )
                )
        notice = re.search(r"(\d{2,3})\s*days'?\s*(?:prior\s+)?(?:written\s+)?notice", text, re.I)
        if notice and int(notice[1]) >= 60 and any(r.title == "Automatic renewal" for r in risks):
            risks.append(
                Risk(
                    severity="medium",
                    title=f"Long notice window ({notice[1]} days)",
                    explanation="Cancelling requires a long notice period - put the deadline in a calendar.",
                    source_quote=_sentence_at(text, notice.start()),
                )
            )

        levels = {r.severity for r in risks}
        overall = "high" if "high" in levels else "medium" if "medium" in levels else "low"

        summary = _summarize(doc_type, parties, key_dates, amounts, risks, sentences)

        insights = DocumentInsights(
            doc_type=doc_type,
            title=title,
            summary=summary,
            parties=parties,
            key_dates=key_dates,
            amounts=amounts,
            obligations=obligations,
            risks=risks,
            overall_risk=overall,
            renewal=_renewal_terms(text, key_dates),
            payment_terms_days=_payment_terms_days(text),
            policy_checks=[],  # natural-language company rules need a real model (Claude mode)
        )
        return Extraction(insights=insights, usage=Usage(model=self.model))

    def answer(self, question: str, sources: list[Source]) -> CitedAnswer:
        """Extractive answer: rank sentences from the retrieved chunks by weighted term overlap."""
        q_terms = set(tokenize(question))
        if not sources or not q_terms:
            return CitedAnswer(
                answer="I couldn't find anything relevant in your documents.", usage=Usage(model=self.model)
            )
        candidates: list[tuple[int, int, str, set[str]]] = []  # (rank, ref, sentence, terms)
        for rank, src in enumerate(sources[:4]):
            for sent in _sentences(src.text):
                clean = re.sub(r"^[#*\-\s\d.]+", "", sent).strip()
                if len(clean) >= 30 and "fictional sample" not in clean.lower():
                    candidates.append((rank, src.ref, clean, set(tokenize(clean))))
        # Rarer question terms (across candidate sentences) count for more - a light IDF.
        df = Counter(t for *_, terms in candidates for t in terms & q_terms)
        n = max(len(candidates), 1)
        idf = {t: math.log(1 + n / (1 + df[t])) for t in q_terms}

        scored: list[tuple[float, int, str]] = []
        for rank, ref, sent, terms in candidates:
            hit = terms & q_terms
            if not hit:
                continue
            score = sum(idf[t] for t in hit) * (1.0 - 0.12 * rank)
            if re.search(r"\d", sent):
                score *= 1.15  # answers to business questions usually carry a number or date
            scored.append((score, ref, sent))
        scored.sort(key=lambda p: p[0], reverse=True)
        if not scored:
            return CitedAnswer(
                answer="The documents don't appear to answer that question.", usage=Usage(model=self.model)
            )
        best = scored[0][0]
        chosen: list[tuple[float, int, str]] = []
        for item in scored:
            if item[0] < best * 0.7 or len(chosen) == 3:
                break
            if item[2] not in {c[2] for c in chosen}:
                chosen.append(item)
        lines = [f"- {sent} [{ref}]" for _, ref, sent in chosen]
        answer = "Here is what the documents say:\n" + "\n".join(lines)
        return CitedAnswer(answer=answer, citations=[(ref, s) for _, ref, s in chosen], usage=Usage(model=self.model))
