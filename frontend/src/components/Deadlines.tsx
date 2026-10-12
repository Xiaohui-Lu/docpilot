import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BellRing, CalendarClock, CircleCheck, CircleDollarSign, FileClock, RotateCcw, TimerReset } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, timeAgo } from "../lib/format";
import type { ActionItem, Urgency } from "../lib/types";

export const URGENCY_STYLE: Record<Urgency, { label: string; pill: string; bar: string }> = {
  overdue: { label: "Overdue", pill: "bg-red-600 text-white", bar: "bg-red-500" },
  urgent: { label: "Next 14 days", pill: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200", bar: "bg-red-400" },
  soon: {
    label: "Next 30 days",
    pill: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200",
    bar: "bg-amber-400",
  },
  upcoming: { label: "Later", pill: "bg-paper text-muted ring-1 ring-inset ring-line", bar: "bg-brand-400" },
};

const KIND_ICON: Record<string, typeof BellRing> = {
  cancel_by: BellRing,
  auto_renews: TimerReset,
  payment_due: CircleDollarSign,
  notice: FileClock,
};

export function daysText(days: number): string {
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

export function DeadlineRow({ item, compact = false }: { item: ActionItem; compact?: boolean }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [showQuote, setShowQuote] = useState(false);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["deadlines"] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const handle = useMutation({ mutationFn: () => api.markHandled(item, note), onSuccess: refresh });
  const reopen = useMutation({ mutationFn: () => api.reopen(item), onSuccess: refresh });
  const Icon = KIND_ICON[item.kind] ?? CalendarClock;
  const style = URGENCY_STYLE[item.urgency];
  const isCancel = item.kind === "cancel_by";

  return (
    <li className={clsx("relative flex gap-4 px-5 py-4", item.handled && "opacity-60")} data-testid="deadline">
      <span className={clsx("absolute inset-y-3 left-0 w-1 rounded-r", style.bar)} aria-hidden />
      <div className="w-[88px] shrink-0">
        <div className="text-sm font-semibold text-ink">{formatDate(item.date, { year: undefined })}</div>
        <div className="text-[11px] text-muted">{new Date(`${item.date}T00:00:00`).getFullYear()}</div>
        <span className={clsx("mt-1.5 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", style.pill)}>
          {daysText(item.days_left)}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <Icon className={clsx("mt-0.5 size-4 shrink-0", isCancel ? "text-red-600" : "text-muted")} />
          <div className="min-w-0">
            <div className={clsx("text-sm font-semibold", isCancel && "text-red-800")}>{item.label}</div>
            {item.detail && <div className="mt-0.5 text-sm text-muted">{item.detail}</div>}
            {!compact && (
              <Link
                to={`/documents/${item.document_id}`}
                className="mt-1 inline-block text-sm text-brand-700 hover:underline"
              >
                {item.document_title}
              </Link>
            )}
            {item.source_quote && (
              <button
                type="button"
                onClick={() => setShowQuote(!showQuote)}
                className={clsx("text-xs text-muted hover:text-ink", compact ? "mt-1 block" : "ml-2")}
              >
                {showQuote ? "Hide clause" : "Show clause"}
              </button>
            )}
            {showQuote && (
              <blockquote className="mt-2 rounded-lg border-l-2 border-brand-400 bg-paper/60 px-3 py-2 text-xs italic text-ink/80">
                "{item.source_quote}"
              </blockquote>
            )}
            {item.handled && (
              <div className="mt-1.5 text-xs text-brand-700">
                <CircleCheck className="mr-1 inline size-3.5" />
                Handled by {item.handled_by}
                {item.handled_at ? ` ${timeAgo(item.handled_at)}` : ""}
                {item.note ? ` - "${item.note}"` : ""}
              </div>
            )}
          </div>
        </div>
      </div>
      {can("member") && (
        <div className="shrink-0 self-start">
          {item.handled ? (
            <button type="button" className="btn-secondary px-2.5 py-1.5 text-xs" onClick={() => reopen.mutate()}>
              <RotateCcw className="size-3.5" /> Reopen
            </button>
          ) : confirming ? (
            <div className="flex w-56 flex-col gap-1.5">
              <input
                className="input py-1.5 text-xs"
                placeholder="Note (optional), e.g. notice sent"
                value={note}
                autoFocus
                onChange={(e) => setNote(e.target.value)}
              />
              <div className="flex gap-1.5">
                <button
                  type="button"
                  className="btn-primary flex-1 px-2.5 py-1.5 text-xs"
                  disabled={handle.isPending}
                  onClick={() => handle.mutate()}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  className="btn-secondary px-2.5 py-1.5 text-xs"
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn-secondary px-2.5 py-1.5 text-xs" onClick={() => setConfirming(true)}>
              <CircleCheck className="size-3.5" /> Mark handled
            </button>
          )}
        </div>
      )}
    </li>
  );
}
