import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, BellRing, BookCheck, Coins, FileText, Gauge, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { daysText, URGENCY_STYLE } from "../components/Deadlines";
import { UploadDropzone } from "../components/UploadDropzone";
import { Card, Empty, ErrorNote, PageHeader, Spinner, Stat } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import clsx from "clsx";
import { DOC_TYPE_LABEL, formatDate, formatMoney, formatMs } from "../lib/format";

const RISK_COLORS: Record<string, string> = { high: "#dc2626", medium: "#d97706", low: "#1f8a70" };

export function DashboardPage() {
  const { user, can } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: (q) => {
      const s = q.state.data?.documents.by_status;
      return s && ((s.queued ?? 0) > 0 || (s.processing ?? 0) > 0) ? 2000 : 30000;
    },
  });

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorNote error={error ?? "Could not load dashboard"} />;

  const d = data.documents;
  const ready = d.by_status.ready ?? 0;
  const inFlight = (d.by_status.queued ?? 0) + (d.by_status.processing ?? 0);
  const riskData = (["high", "medium", "low"] as const).map((k) => ({ level: k, count: d.by_risk[k] ?? 0 }));
  const typeData = Object.entries(d.by_type).map(([k, v]) => ({ type: DOC_TYPE_LABEL[k] ?? k, count: v }));
  const cancel = data.deadlines.next_cancel_by;
  const llmCost = data.llm.document_cost_usd + data.llm.question_cost_usd;

  if (d.total === 0) {
    return (
      <>
        <PageHeader kicker="Overview" title={`Welcome, ${user?.name.split(" ")[0] ?? ""}`} />
        <Card>
          <Empty icon={<FileText className="size-8" />} title="No documents yet">
            Upload a contract, NDA, invoice or policy. DocPilot finds every deadline - including the last day to cancel
            an auto-renewal - checks it against your rulebook, and emails your team before anything slips.
          </Empty>
          {can("member") && <UploadDropzone />}
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader kicker="Overview" title="Portfolio dashboard">
        {inFlight > 0 && <span className="text-sm text-muted">{inFlight} document(s) processing...</span>}
        <Link to="/documents" className="btn-secondary">
          View documents
        </Link>
      </PageHeader>

      {cancel && cancel.days_left <= 30 && (
        <div className="mb-4 flex flex-wrap items-center gap-4 rounded-xl border border-red-200 bg-red-50 px-5 py-4">
          <div className="grid size-10 shrink-0 place-items-center rounded-full bg-red-600 text-white">
            <BellRing className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-red-900">
              {daysText(cancel.days_left)}: last day to cancel {cancel.document_title} ({formatDate(cancel.date)})
            </div>
            <div className="text-sm text-red-800/90">{cancel.detail}</div>
          </div>
          <Link to="/deadlines" className="btn-primary shrink-0">
            Review deadlines
          </Link>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Actions due in 30 days"
          value={data.deadlines.next_30_days}
          hint={
            data.deadlines.overdue
              ? `${data.deadlines.overdue} overdue`
              : `${data.deadlines.next_14_days} in the next 14 days`
          }
          icon={<BellRing className="size-5" />}
          tone={data.deadlines.next_30_days ? "warn" : "good"}
        />
        <Stat
          label="Rulebook issues"
          value={data.policy.violations}
          hint={
            data.policy.top_rules[0]
              ? `${data.policy.documents_with_violations} docs · top: ${data.policy.top_rules[0].rule}`
              : "Every document follows your rules"
          }
          icon={<BookCheck className="size-5" />}
          tone={data.policy.violations ? "warn" : "good"}
        />
        <Stat
          label="High-risk documents"
          value={d.by_risk.high ?? 0}
          hint={data.top_risks[0] ? `Most common: ${data.top_risks[0].title}` : "No risks found"}
          icon={<ShieldAlert className="size-5" />}
          tone={(d.by_risk.high ?? 0) > 0 ? "warn" : "good"}
        />
        <Stat
          label="Documents analyzed"
          value={ready}
          hint={`${d.total} uploaded · ${
            data.grounding.score === null ? "-" : Math.round(data.grounding.score * 100)
          }% of AI quotes verified`}
          icon={<FileText className="size-5" />}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card
          title="Upcoming deadlines"
          className="lg:col-span-2"
          bodyClassName="p-0"
          action={
            <Link to="/deadlines" className="text-xs font-medium text-brand-700 hover:underline">
              View all
            </Link>
          }
        >
          {data.upcoming_dates.length === 0 ? (
            <Empty title="No deadlines in the next 120 days" />
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-paper/60 text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2 font-medium">Date</th>
                  <th className="px-5 py-2 font-medium">What</th>
                  <th className="px-5 py-2 font-medium">Document</th>
                  <th className="px-5 py-2 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.upcoming_dates.slice(0, 7).map((u) => (
                  <tr key={`${u.document_id}-${u.label}-${u.date}`} className="hover:bg-paper/40">
                    <td className="whitespace-nowrap px-5 py-2.5 font-medium">{formatDate(u.date)}</td>
                    <td className={clsx("px-5 py-2.5", u.kind === "cancel_by" && "font-semibold text-red-800")}>
                      {u.label}
                    </td>
                    <td className="max-w-[260px] truncate px-5 py-2.5">
                      <Link className="text-brand-700 hover:underline" to={`/documents/${u.document_id}`}>
                        {u.document_title}
                      </Link>
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <span
                        className={clsx(
                          "whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold",
                          URGENCY_STYLE[u.urgency].pill,
                        )}
                      >
                        {daysText(u.days_left)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Risk distribution">
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={riskData} margin={{ left: -20, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#ece9e2" />
                <XAxis dataKey="level" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#5f6b6e" }} />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12, fill: "#5f6b6e" }}
                />
                <Tooltip cursor={{ fill: "#f5f3ee" }} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {riskData.map((r) => (
                    <Cell key={r.level} fill={RISK_COLORS[r.level]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {typeData.map((t) => (
              <span key={t.type} className="rounded-md bg-paper px-2 py-1 text-xs text-muted">
                {t.type}: <b className="text-ink">{t.count}</b>
              </span>
            ))}
          </div>
        </Card>

        <Card
          title="Top rulebook issues"
          bodyClassName="p-0"
          action={
            <Link to="/rules" className="text-xs font-medium text-brand-700 hover:underline">
              Rulebook
            </Link>
          }
        >
          {data.policy.top_rules.length === 0 ? (
            <Empty title="Every document follows your rules" />
          ) : (
            <ul className="divide-y divide-line">
              {data.policy.top_rules.map((r) => (
                <li key={r.rule} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <span>{r.rule}</span>
                  <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
                    {r.count}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Uploads, last 14 days">
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.timeline} margin={{ left: -24, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#ece9e2" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => v.slice(5)}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "#5f6b6e" }}
                  interval={3}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "#5f6b6e" }}
                />
                <Tooltip cursor={{ fill: "#f5f3ee" }} />
                <Bar dataKey="uploads" fill="#1f8a70" radius={[4, 4, 0, 0]} maxBarSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Pipeline & AI usage">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted">Processing p50 / p95</dt>
              <dd className="mt-0.5 flex items-center gap-1.5 font-semibold">
                <Gauge className="size-4 text-muted" />
                {formatMs(data.processing.p50_ms)} / {formatMs(data.processing.p95_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">AI quotes verified</dt>
              <dd className="mt-0.5 flex items-center gap-1.5 font-semibold">
                <BadgeCheck className="size-4 text-brand-600" />
                {data.grounding.grounded}/{data.grounding.checked}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Jobs retried</dt>
              <dd className="mt-0.5 font-semibold">{data.processing.jobs_retried}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Questions answered</dt>
              <dd className="mt-0.5 font-semibold">{data.llm.questions}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">LLM spend (est.)</dt>
              <dd className="mt-0.5 flex items-center gap-1.5 font-semibold">
                <Coins className="size-4 text-muted" />
                {formatMoney(llmCost, "USD")}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-xs text-muted">Contract value tracked</dt>
              <dd className="mt-0.5 font-semibold">
                {data.contract_value.length
                  ? data.contract_value.map((c) => formatMoney(c.value, c.currency)).join(" · ")
                  : "-"}
              </dd>
            </div>
          </dl>
        </Card>
      </div>
    </>
  );
}
