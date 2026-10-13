import zlib

from app.schemas import DocumentInsights, KeyDate, Risk
from app.services.grounding import _norm, check_grounding, quote_is_grounded
from app.services.parsing import ParsedDocument, chunk_text, parse_document
from app.services.retrieval import BM25, tokenize


def _minimal_pdf(pages: list[str]) -> bytes:
    """Build a tiny valid PDF with one text line per page (no external deps)."""
    objs: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + len(pages) * 2
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        stream = zlib.compress(content)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + i * 2} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objs.append(f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def test_parse_pdf_with_pages():
    pdf = _minimal_pdf(["This Agreement renews automatically each year.", "Payment is due within 30 days."])
    parsed = parse_document(pdf, "application/pdf")
    assert parsed.page_count == 2
    assert "renews automatically" in parsed.text and "within 30 days" in parsed.text
    chunks = chunk_text(parsed, size=40, overlap=10)
    assert {c.page for c in chunks} == {1, 2}


def test_chunking_overlaps_and_covers_text():
    text = " ".join(f"Sentence number {i} talks about clause {i}." for i in range(200))
    parsed = ParsedDocument(text=text, page_count=1, page_offsets=[0])
    chunks = chunk_text(parsed, size=500, overlap=100)
    assert len(chunks) > 5
    assert all(len(c.text) <= 500 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start_char < prev.end_char  # overlap
    assert chunks[-1].end_char == len(text)


def test_bm25_prefers_relevant_chunk():
    docs = [
        tokenize("The tenant pays monthly rent of CAD 18,600"),
        tokenize("This agreement renews automatically unless 90 days notice is given"),
        tokenize("Invoices are payable within 30 days"),
    ]
    bm = BM25(docs)
    q = tokenize("how much notice before automatic renewal")
    scores = [bm.score(q, i) for i in range(3)]
    assert scores.index(max(scores)) == 1


def _insights(quote: str) -> DocumentInsights:
    return DocumentInsights(
        doc_type="contract",
        title="T",
        summary="S",
        parties=[],
        amounts=[],
        obligations=[],
        key_dates=[KeyDate(label="End", date="2027-01-14", source_quote="ends on January 14, 2027")],
        risks=[Risk(severity="high", title="Made up", explanation="x", source_quote=quote)],
        overall_risk="high",
    )


def test_grounding_flags_fabricated_quotes():
    text = "The initial term ends on January 14, 2027.\nThe Provider may increase fees by 7%."
    ok = check_grounding(_insights("The Provider may increase fees by 7%"), text)
    assert ok["score"] == 1.0
    bad = check_grounding(_insights("The Customer waives all rights to terminate"), text)
    assert bad["ungrounded"] == 1 and bad["score"] == 0.5


def test_grounding_tolerates_whitespace_and_quotes():
    text = "the  “Provider”   shall\nnotify the Customer within 72 hours"
    assert quote_is_grounded('the "Provider" shall notify the Customer within 72 hours', _norm(text))


def test_missing_clause_risks_without_quotes_are_not_counted():
    result = check_grounding(_insights(""), "The initial term ends on January 14, 2027.")
    assert result["checked"] == 1 and result["ungrounded"] == 0
