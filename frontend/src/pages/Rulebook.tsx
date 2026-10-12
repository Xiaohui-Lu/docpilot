import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BookCheck, Plus, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Card, Empty, ErrorNote, PageHeader, RiskBadge, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { DOC_TYPE_LABEL } from "../lib/format";
import type { RiskLevel, Rule, RuleKindSpec } from "../lib/types";

function describeParams(rule: Rule): string {
  const p = rule.params as Record<string, unknown>;
  switch (rule.kind) {
    case "max_notice_days":
      return `Notice to cancel must be ${p.days} days or less`;
    case "no_auto_renewal":
      return "Flags every automatic renewal";
    case "payment_terms":
      return [p.min_days ? `at least ${p.min_days} days` : "", p.max_days ? `at most ${p.max_days} days` : ""]
        .filter(Boolean)
        .join(", ")
        .replace(/^/, "Payment terms: ");
    case "approval_threshold":
      return `Value of ${p.currency} ${Number(p.amount).toLocaleString()} or more needs approval`;
    case "required_clause":
      return `Must contain: ${(p.phrases as string[]).map((x) => `"${x}"`).join(" or ")}`;
    case "prohibited_clause":
      return `Must not contain: ${(p.phrases as string[]).map((x) => `"${x}"`).join(", ")}`;
    case "ai_instruction":
      return String(p.instruction);
    default:
      return "";
  }
}

export function RulebookPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const kinds = useQuery({ queryKey: ["rule-kinds"], queryFn: api.ruleKinds });
  const flagged = useQuery({
    queryKey: ["documents", { policy: "violations" }],
    queryFn: () => api.documents({ policy: "violations" }),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rules"] });
    void qc.invalidateQueries({ queryKey: ["documents"] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const toggle = useMutation({
    mutationFn: (r: Rule) => api.updateRule(r.id, { enabled: !r.enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (r: Rule) => api.deleteRule(r.id), onSuccess: refresh });

  return (
    <>
      <PageHeader kicker="Company policies" title="Rulebook" />
      <p className="-mt-3 mb-6 max-w-3xl text-sm text-muted">
        Your own rules, applied to every document the moment it is analyzed - and re-checked across all documents
        whenever a rule changes. Structured rules run instantly; plain-English rules are checked by the AI.
      </p>
      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <div className="space-y-5">
          <Card bodyClassName="p-0" title={`Rules (${rules.data?.length ?? 0})`}>
            {rules.isLoading ? (
              <Spinner />
            ) : !rules.data?.length ? (
              <Empty icon={<BookCheck className="size-8" />} title="No rules yet">
                Add your first policy, e.g. "notice periods must be 60 days or less".
              </Empty>
            ) : (
              <ul className="divide-y divide-line">
                {rules.data.map((r) => (
                  <li key={r.id} className={clsx("flex gap-4 px-5 py-4", !r.enabled && "opacity-55")}>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{r.name}</span>
                        <RiskBadge level={r.severity} suffix="severity" />
                        {r.kind === "ai_instruction" && (
                          <span className="inline-flex items-center gap-1 rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px] font-medium text-violet-700">
                            <Sparkles className="size-3" /> AI rule
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-sm text-muted">{describeParams(r)}</div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-muted">
                        <span className="rounded bg-paper px-1.5 py-0.5">{kinds.data?.[r.kind]?.label ?? r.kind}</span>
                        <span className="rounded bg-paper px-1.5 py-0.5">
                          {r.doc_types.length
                            ? r.doc_types.map((t) => DOC_TYPE_LABEL[t] ?? t).join(", ")
                            : "All documents"}
                        </span>
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span
                        className={clsx(
                          "rounded-full px-2 py-0.5 text-xs font-semibold",
                          r.violations
                            ? "bg-red-50 text-red-700"
                            : r.not_evaluated
                              ? "bg-paper text-muted ring-1 ring-inset ring-line"
                              : "bg-brand-50 text-brand-700",
                        )}
                        title={
                          r.not_evaluated ? "Plain-English rules are checked by Claude during analysis" : undefined
                        }
                      >
                        {r.violations
                          ? `${r.violations} document${r.violations > 1 ? "s" : ""} fail`
                          : r.not_evaluated
                            ? `Not checked yet (${r.not_evaluated} docs)`
                            : "All pass"}
                      </span>
                      {can("admin") && (
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1.5 text-xs text-muted">
                            <input
                              type="checkbox"
                              className="size-3.5 accent-[#1f8a70]"
                              checked={r.enabled}
                              onChange={() => toggle.mutate(r)}
                              aria-label={`Enable ${r.name}`}
                            />
                            On
                          </label>
                          <button
                            type="button"
                            className="text-muted hover:text-red-700"
                            aria-label={`Delete ${r.name}`}
                            onClick={() => {
                              if (window.confirm(`Delete rule "${r.name}"?`)) remove.mutate(r);
                            }}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {can("admin") && kinds.data && <NewRuleForm kinds={kinds.data} onCreated={refresh} />}
        </div>

        <Card title="Documents with rule violations" bodyClassName="p-0">
          {!flagged.data?.items.length ? (
            <Empty title="Every document follows your rules" />
          ) : (
            <ul className="divide-y divide-line">
              {flagged.data.items.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <Link
                    to={`/documents/${d.id}`}
                    className="min-w-0 truncate text-sm font-medium text-brand-700 hover:underline"
                  >
                    {d.title ?? d.filename}
                  </Link>
                  <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
                    {d.policy_violations} issue{d.policy_violations > 1 ? "s" : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

const DOC_TYPES = ["contract", "nda", "invoice", "policy", "other"];

function NewRuleForm({ kinds, onCreated }: { kinds: Record<string, RuleKindSpec>; onCreated: () => void }) {
  const [kind, setKind] = useState("max_notice_days");
  const spec = kinds[kind]!;
  const defaults = useMemo(
    () => Object.fromEntries(spec.params.map((p) => [p.name, Array.isArray(p.default) ? "" : String(p.default ?? "")])),
    [spec],
  );
  const [values, setValues] = useState<Record<string, string>>(defaults);
  const [name, setName] = useState("");
  const [severity, setSeverity] = useState<RiskLevel>("medium");
  const [docTypes, setDocTypes] = useState<string[]>([]);

  const create = useMutation({
    mutationFn: () =>
      api.createRule({
        name,
        description: "",
        kind,
        severity,
        doc_types: docTypes,
        enabled: true,
        params: Object.fromEntries(
          spec.params.map((p) => [
            p.name,
            p.type === "list"
              ? values[p.name]!.split(",")
                  .map((s) => s.trim())
                  .filter(Boolean)
              : values[p.name],
          ]),
        ),
      }),
    onSuccess: () => {
      setName("");
      setValues(defaults);
      onCreated();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Plus className="size-4" /> Add a rule
        </span>
      }
    >
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label" htmlFor="rule-kind">
            Type of rule
          </label>
          <select
            id="rule-kind"
            className="input"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              const s = kinds[e.target.value]!;
              setValues(
                Object.fromEntries(
                  s.params.map((p) => [p.name, Array.isArray(p.default) ? "" : String(p.default ?? "")]),
                ),
              );
            }}
          >
            {Object.entries(kinds).map(([k, s]) => (
              <option key={k} value={k}>
                {s.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted">{spec.help}</p>
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="rule-name">
            Rule name
          </label>
          <input
            id="rule-name"
            className="input"
            required
            minLength={3}
            placeholder="e.g. Notice period of 60 days or less"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        {spec.params.map((p) => (
          <div key={p.name} className={p.type === "text" || p.type === "list" ? "sm:col-span-2" : ""}>
            <label className="label" htmlFor={`param-${p.name}`}>
              {p.label}
              {p.type === "list" && " (comma-separated)"}
            </label>
            {p.type === "text" ? (
              <textarea
                id={`param-${p.name}`}
                className="input min-h-20"
                required
                placeholder="e.g. Vendors that store our customer data must be located in Canada or the US."
                value={values[p.name] ?? ""}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
              />
            ) : (
              <input
                id={`param-${p.name}`}
                className="input"
                type={p.type === "int" || p.type === "number" ? "number" : "text"}
                min={p.type === "int" ? 0 : undefined}
                value={values[p.name] ?? ""}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
              />
            )}
          </div>
        ))}
        <div>
          <label className="label" htmlFor="rule-severity">
            Severity
          </label>
          <select
            id="rule-severity"
            className="input"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as RiskLevel)}
          >
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <fieldset>
          <legend className="label">Applies to</legend>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {DOC_TYPES.map((t) => (
              <label key={t} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  className="size-3.5 accent-[#1f8a70]"
                  checked={docTypes.includes(t)}
                  onChange={(e) => setDocTypes(e.target.checked ? [...docTypes, t] : docTypes.filter((x) => x !== t))}
                />
                {DOC_TYPE_LABEL[t]}
              </label>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-muted">None selected = all documents</p>
        </fieldset>
        <div className="sm:col-span-2">
          <ErrorNote error={create.error} />
        </div>
        <div className="sm:col-span-2">
          <button className="btn-primary" type="submit" disabled={create.isPending}>
            Add rule and check all documents
          </button>
        </div>
      </form>
    </Card>
  );
}
