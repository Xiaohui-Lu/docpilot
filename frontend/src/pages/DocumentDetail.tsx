import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeft,
  BadgeCheck,
  BookCheck,
  Building2,
  CalendarClock,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleDollarSign,
  CircleX,
  RefreshCw,
  ScrollText,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AskBox } from "../components/AskBox";
import { DeadlineRow } from "../components/Deadlines";
import { Card, Empty, ErrorNote, PageHeader, RiskBadge, Spinner, StatusBadge, TypeTag } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatBytes, formatDate, formatDateTime, formatMoney, formatMs, highlight } from "../lib/format";
import type { DocumentDetail, Grounding, PolicyFinding } from "../lib/types";

function isGrounded(g: Grounding | null, kind: "date" | "risk", index: number): boolean | null {
  const item = g?.items.find((i) => i.kind === kind && i.index === index);
  return item ? item.grounded : null;
}

function VerifiedTag({ grounded }: { grounded: boolean | null }) {
  if (grounded === null) return null;
  return grounded ? (
    <span
      className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-700"
      title="Quote found in source text"
    >
      <BadgeCheck className="size-3.5" /> Verified in source
    </span>
  ) : (
    <span
      className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700"
      title="Quote not found verbatim"
    >
      <CircleAlert className="size-3.5" /> Unverified quote
    </span>
  );
}

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const [quote, setQuote] = useState<string | null>(params.get("quote"));
  const { can } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const {
    data: doc,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["document", id],
    queryFn: () => api.document(id),
    refetchInterval: (q) => (q.state.data && ["queued", "processing"].includes(q.state.data.status) ? 1500 : false),
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["document", id] });
    void qc.invalidateQueries({ queryKey: ["documents"] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const reprocess = useMutation({ mutationFn: () => api.reprocess(id), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: () => api.deleteDocument(id),
    onSuccess: () => {
      refresh();
      navigate("/documents");
    },
  });

  if (isLoading) return <Spinner />;
  if (error || !doc) return <ErrorNote error={error ?? "Document not found"} />;

  const ins = doc.insights;
  const busy = doc.status === "queued" || doc.status === "processing";

  return (
    <>
      <Link to="/documents" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> All documents
      </Link>
      <PageHeader
        kicker={ins ? undefined : "Document"}
        title={
          <span className="flex flex-wrap items-center gap-3">
            {doc.title ?? doc.filename}
            <RiskBadge level={doc.overall_risk} />
          </span>
        }
      >
        {can("member") && (
          <>
            <button
              className="btn-secondary"
              disabled={busy || reprocess.isPending}
              onClick={() => reprocess.mutate()}
              type="button"
            >
              <RefreshCw className={clsx("size-4", busy && "animate-spin")} /> Re-analyze
            </button>
            <button
              className="btn-danger"
              disabled={remove.isPending}
              type="button"
              onClick={() => {
                if (window.confirm(`Delete "${doc.title ?? doc.filename}"?`)) remove.mutate();
              }}
            >
              <Trash2 className="size-4" /> Delete
            </button>
          </>
        )}
      </PageHeader>

      <div className="mb-5 flex flex-wrap items-center gap-2 text-xs text-muted">
        <StatusBadge status={doc.status} />
        <TypeTag type={doc.doc_type} />
        <span>{doc.filename}</span>·<span>{formatBytes(doc.size_bytes)}</span>
        {doc.page_count > 1 && (
          <>
            ·<span>{doc.page_count} pages</span>
          </>
        )}
        {doc.processed_at && (
          <>
            ·
            <span>
              Analyzed {formatDateTime(doc.processed_at)} in {formatMs(doc.processing_ms)}
            </span>
          </>
        )}
      </div>

      {doc.status === "failed" && (
        <div className="mb-5">
          <ErrorNote error={doc.error} />
        </div>
      )}
      {busy && (
        <Card className="mb-5">
          <div className="flex items-center gap-3 text-sm text-muted">
            <RefreshCw className="size-4 animate-spin" />
            {doc.error ?? "Analyzing - extracting parties, dates, amounts and risks..."}
          </div>
        </Card>
      )}

      {ins && (
        <div className="grid gap-5 xl:grid-cols-[1.25fr_1fr]">
          <div className="space-y-5">
            <Card title="Summary">
              <p className="text-sm leading-relaxed text-ink/90">{ins.summary}</p>
              {ins.parties.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {ins.parties.map((p) => (
                    <span
                      key={p.name}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-paper/60 px-2.5 py-1 text-xs"
                    >
                      <Building2 className="size-3.5 text-muted" />
                      <b className="font-medium">{p.name}</b>
                      <span className="text-muted">{p.role}</span>
                    </span>
                  ))}
                </div>
              )}
            </Card>

            <DocumentDeadlines documentId={doc.id} />
            <RulebookCheck findings={doc.policy_findings} onQuote={setQuote} />

            <Card title={`Risks (${ins.risks.length})`} bodyClassName="p-0">
              {ins.risks.length === 0 ? (
                <Empty title="No risky clauses detected" />
              ) : (
                <ul className="divide-y divide-line">
                  {ins.risks.map((r, i) => (
                    <li key={`${r.title}-${i}`} className="px-5 py-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <RiskBadge level={r.severity} />
                          <span className="text-sm font-semibold">{r.title}</span>
                        </div>
                        <VerifiedTag grounded={isGrounded(doc.grounding, "risk", i)} />
                      </div>
                      <p className="mt-1.5 text-sm text-muted">{r.explanation}</p>
                      <button
                        type="button"
                        onClick={() => setQuote(r.source_quote)}
                        className={clsx(
                          "mt-2 block w-full rounded-lg border-l-2 bg-paper/60 px-3 py-2 text-left text-xs italic text-ink/80 hover:bg-brand-50",
                          quote === r.source_quote ? "border-brand-500" : "border-line",
                        )}
                      >
                        "{r.source_quote}"
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="grid gap-5 md:grid-cols-2">
              <Card
                title={
                  <span className="flex items-center gap-2">
                    <CalendarClock className="size-4" /> Key dates
                  </span>
                }
                bodyClassName="p-0"
              >
                {ins.key_dates.length === 0 ? (
                  <Empty title="No dates found" />
                ) : (
                  <ul className="divide-y divide-line">
                    {ins.key_dates.map((d, i) => (
                      <li key={`${d.label}-${i}`}>
                        <button
                          type="button"
                          onClick={() => setQuote(d.source_quote)}
                          className="flex w-full items-center justify-between gap-3 px-5 py-2.5 text-left text-sm hover:bg-paper/50"
                        >
                          <span>
                            <span className="block font-medium">{d.date ? formatDate(d.date) : "Unspecified"}</span>
                            <span className="text-xs text-muted">{d.label}</span>
                          </span>
                          <VerifiedTag grounded={isGrounded(doc.grounding, "date", i)} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card
                title={
                  <span className="flex items-center gap-2">
                    <CircleDollarSign className="size-4" /> Amounts
                  </span>
                }
                bodyClassName="p-0"
              >
                {ins.amounts.length === 0 ? (
                  <Empty title="No amounts found" />
                ) : (
                  <ul className="divide-y divide-line">
                    {ins.amounts.map((a, i) => (
                      <li key={`${a.label}-${i}`} className="flex items-center justify-between px-5 py-2.5 text-sm">
                        <span className="text-muted">{a.label}</span>
                        <span className="font-semibold tabular-nums">{formatMoney(a.value, a.currency)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>

            {ins.obligations.length > 0 && (
              <Card title="Obligations">
                <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink/90">
                  {ins.obligations.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          <div className="space-y-5">
            <Card title="Ask about this document">
              <AskBox
                documentId={doc.id}
                placeholder="e.g. What happens if we pay late?"
                suggestions={["What are the payment terms?", "How can this be terminated?"]}
                onCite={(c) => setQuote(c.quote)}
              />
            </Card>
            <SourceText doc={doc} quote={quote} onClear={() => setQuote(null)} />
            <ProcessingCard doc={doc} />
          </div>
        </div>
      )}
    </>
  );
}

function SourceText({ doc, quote, onClear }: { doc: DocumentDetail; quote: string | null; onClear: () => void }) {
  const parts = useMemo(() => highlight(doc.text, quote), [doc.text, quote]);
  const found = parts.some((p) => p.match);
  const box = useRef<HTMLDivElement>(null);

  // Scroll only the source panel (not the page) so the highlighted passage is centred.
  useEffect(() => {
    const el = box.current;
    const mark = el?.querySelector("mark");
    if (el && mark instanceof HTMLElement) {
      el.scrollTo({ top: Math.max(0, mark.offsetTop - el.clientHeight / 2), behavior: "smooth" });
    }
  }, [quote]);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <ScrollText className="size-4" /> Source text
        </span>
      }
      action={
        quote ? (
          <button type="button" onClick={onClear} className="text-xs text-muted hover:text-ink">
            {found ? "Clear highlight" : "Quote not located - clear"}
          </button>
        ) : null
      }
      bodyClassName="p-0"
    >
      <div
        ref={box}
        className="relative max-h-[520px] overflow-y-auto whitespace-pre-wrap px-5 py-4 font-mono text-[12.5px] leading-relaxed text-ink/85"
      >
        {parts.map((p, i) =>
          p.match ? (
            <mark key={i} className="hl">
              {p.text}
            </mark>
          ) : (
            <span key={i}>{p.text}</span>
          ),
        )}
      </div>
    </Card>
  );
}

function ProcessingCard({ doc }: { doc: DocumentDetail }) {
  const g = doc.grounding;
  return (
    <Card title="Processing details">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-muted">Model</dt>
          <dd className="font-medium">{doc.llm_model ?? "-"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Tokens (in / out)</dt>
          <dd className="font-medium tabular-nums">
            {doc.input_tokens.toLocaleString()} / {doc.output_tokens.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Estimated cost</dt>
          <dd className="font-medium">{formatMoney(doc.cost_usd, "USD")}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Grounding</dt>
          <dd className="font-medium">{g ? `${g.grounded}/${g.checked} quotes verified` : "-"}</dd>
        </div>
      </dl>
      {doc.jobs.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="label">Job history</div>
          <ul className="space-y-1.5 text-xs">
            {doc.jobs.map((j) => (
              <li key={j.id} className="flex items-center justify-between gap-2">
                <span
                  className={clsx(
                    "font-medium capitalize",
                    j.status === "failed" ? "text-red-700" : j.status === "succeeded" ? "text-brand-700" : "text-muted",
                  )}
                >
                  {j.status}
                </span>
                <span className="text-muted">
                  attempt {j.attempts}/{j.max_attempts} · {formatDateTime(j.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function DocumentDeadlines({ documentId }: { documentId: string }) {
  const { data } = useQuery({
    queryKey: ["deadlines", "document", documentId],
    queryFn: () => api.deadlines({ documentId, includeHandled: true, horizonDays: 1825 }),
  });
  if (!data?.items.length) return null;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <CalendarClock className="size-4" /> Deadlines for this document
        </span>
      }
      action={
        <Link to="/deadlines" className="text-xs font-medium text-brand-700 hover:underline">
          All deadlines
        </Link>
      }
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-line">
        {data.items.map((i) => (
          <DeadlineRow key={i.key} item={i} compact />
        ))}
      </ul>
    </Card>
  );
}

function RulebookCheck({ findings, onQuote }: { findings: PolicyFinding[] | null; onQuote: (q: string) => void }) {
  if (!findings?.length) return null;
  const failed = findings.filter((f) => f.status === "fail").length;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <BookCheck className="size-4" /> Rulebook check
          <span
            className={clsx(
              "rounded-full px-2 py-0.5 text-xs font-semibold",
              failed ? "bg-red-50 text-red-700" : "bg-brand-50 text-brand-700",
            )}
          >
            {failed ? `${failed} issue${failed > 1 ? "s" : ""}` : "Compliant"}
          </span>
        </span>
      }
      action={
        <Link to="/rules" className="text-xs font-medium text-brand-700 hover:underline">
          Edit rules
        </Link>
      }
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-line">
        {findings.map((f) => (
          <li key={f.rule_id} className="flex gap-3 px-5 py-3">
            {f.status === "fail" ? (
              <CircleX className="mt-0.5 size-4 shrink-0 text-red-600" />
            ) : f.status === "pass" ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand-600" />
            ) : (
              <CircleDashed className="mt-0.5 size-4 shrink-0 text-muted" />
            )}
            <div className="min-w-0">
              <div className="text-sm font-medium">{f.rule_name}</div>
              <div className={clsx("text-sm", f.status === "fail" ? "text-red-800" : "text-muted")}>{f.message}</div>
              {f.source_quote && f.status === "fail" && (
                <button
                  type="button"
                  onClick={() => onQuote(f.source_quote)}
                  className="mt-1 text-left text-xs italic text-muted hover:text-ink"
                >
                  "{f.source_quote.length > 140 ? `${f.source_quote.slice(0, 140)}...` : f.source_quote}"
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
