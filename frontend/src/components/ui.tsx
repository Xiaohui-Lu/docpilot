import clsx from "clsx";
import { CircleAlert, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { DOC_TYPE_LABEL } from "../lib/format";
import type { DocStatus, RiskLevel } from "../lib/types";

const RISK_STYLE: Record<RiskLevel, string> = {
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  low: "bg-brand-50 text-brand-700 ring-brand-200",
};

export function RiskBadge({
  level,
  className,
  suffix = "risk",
}: {
  level: RiskLevel | null | undefined;
  className?: string;
  suffix?: string;
}) {
  if (!level) return <span className="text-xs text-muted">-</span>;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold capitalize ring-1 ring-inset",
        RISK_STYLE[level],
        className,
      )}
    >
      <span
        className={clsx(
          "size-1.5 rounded-full",
          level === "high" ? "bg-red-500" : level === "medium" ? "bg-amber-500" : "bg-brand-500",
        )}
      />
      {suffix ? `${level} ${suffix}` : level}
    </span>
  );
}

const STATUS_STYLE: Record<DocStatus, string> = {
  queued: "bg-slate-100 text-slate-700",
  processing: "bg-sky-50 text-sky-700",
  ready: "bg-brand-50 text-brand-700",
  failed: "bg-red-50 text-red-700",
};

export function StatusBadge({ status }: { status: DocStatus }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium capitalize",
        STATUS_STYLE[status],
      )}
    >
      {(status === "queued" || status === "processing") && <LoaderCircle className="size-3 animate-spin" />}
      {status}
    </span>
  );
}

export function TypeTag({ type }: { type: string | null }) {
  if (!type) return null;
  return (
    <span className="rounded-md border border-line bg-paper px-1.5 py-0.5 text-[11px] font-medium text-muted">
      {DOC_TYPE_LABEL[type] ?? type}
    </span>
  );
}

export function Card({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("card min-w-0", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className={clsx("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "warn" | "good";
}) {
  return (
    <div className="card flex items-start gap-4 p-5">
      {icon && (
        <div
          className={clsx(
            "grid size-10 shrink-0 place-items-center rounded-lg",
            tone === "warn"
              ? "bg-red-50 text-red-600"
              : tone === "good"
                ? "bg-brand-50 text-brand-600"
                : "bg-paper text-night",
          )}
        >
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <div className="text-xs font-medium text-muted">{label}</div>
        <div className="mt-0.5 text-2xl font-semibold tracking-tight text-ink">{value}</div>
        {hint && <div className="mt-0.5 truncate text-xs text-muted">{hint}</div>}
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted" role="status">
      <LoaderCircle className="size-4 animate-spin" />
      {label}...
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <div className="text-sm font-semibold text-ink">{title}</div>
      {children && <div className="mt-1 max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <CircleAlert className="mt-0.5 size-4 shrink-0" />
      {message}
    </div>
  );
}

export function PageHeader({ kicker, title, children }: { kicker?: string; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {kicker && <div className="kicker mb-1">{kicker}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
