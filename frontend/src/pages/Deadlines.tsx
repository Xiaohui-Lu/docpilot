import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CalendarPlus, Copy, Mail, MailCheck, Send, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { DeadlineRow, URGENCY_STYLE } from "../components/Deadlines";
import { Card, Empty, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, timeAgo } from "../lib/format";
import type { NotificationSettings, Urgency } from "../lib/types";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const GROUPS: Urgency[] = ["overdue", "urgent", "soon", "upcoming"];

export function DeadlinesPage() {
  const [tab, setTab] = useState<"open" | "handled">("open");
  const { data, isLoading, error } = useQuery({
    queryKey: ["deadlines", tab],
    queryFn: () => api.deadlines({ includeHandled: tab === "handled" }),
  });
  const items = (data?.items ?? []).filter((i) => (tab === "handled" ? i.handled : !i.handled));

  return (
    <>
      <PageHeader kicker="Never miss a renewal" title="Deadlines">
        <CalendarButton />
      </PageHeader>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {GROUPS.map((g) => (
          <div key={g} className="card flex items-center justify-between px-4 py-3">
            <div>
              <div className="text-xs text-muted">{URGENCY_STYLE[g].label}</div>
              <div
                className={clsx(
                  "text-2xl font-semibold",
                  g === "overdue" || g === "urgent" ? "text-red-700" : "text-ink",
                )}
              >
                {data?.counts[g] ?? 0}
              </div>
            </div>
            <span className={clsx("h-8 w-1.5 rounded-full", URGENCY_STYLE[g].bar)} />
          </div>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Card
          bodyClassName="p-0"
          title={
            <div className="flex gap-1" role="tablist">
              {(["open", "handled"] as const).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={clsx(
                    "rounded-md px-3 py-1 text-sm capitalize",
                    tab === t ? "bg-paper font-semibold text-ink" : "text-muted hover:text-ink",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          }
        >
          {error && (
            <div className="p-4">
              <ErrorNote error={error} />
            </div>
          )}
          {isLoading ? (
            <Spinner />
          ) : items.length === 0 ? (
            <Empty title={tab === "open" ? "Nothing due in the next 12 months" : "No handled deadlines yet"}>
              {tab === "open" ? "Deadlines appear here as soon as documents are analyzed." : null}
            </Empty>
          ) : tab === "handled" ? (
            <ul className="divide-y divide-line">
              {items.map((i) => (
                <DeadlineRow key={`${i.document_id}-${i.key}`} item={i} />
              ))}
            </ul>
          ) : (
            GROUPS.map((g) => {
              const group = items.filter((i) => i.urgency === g);
              if (!group.length) return null;
              return (
                <section key={g}>
                  <h3 className="border-b border-line bg-paper/50 px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                    {URGENCY_STYLE[g].label} · {group.length}
                  </h3>
                  <ul className="divide-y divide-line">
                    {group.map((i) => (
                      <DeadlineRow key={`${i.document_id}-${i.key}`} item={i} />
                    ))}
                  </ul>
                </section>
              );
            })
          )}
        </Card>

        <div className="space-y-5">
          <DigestSettings />
          <RecentEmails />
        </div>
      </div>
    </>
  );
}

function CalendarButton() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const { can } = useAuth();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["calendar"], queryFn: api.calendar, enabled: open });
  const rotate = useMutation({
    mutationFn: api.rotateCalendar,
    onSuccess: (d) => qc.setQueryData(["calendar"], d),
  });
  const url = data ? `${window.location.origin}${data.path}` : "";
  return (
    <>
      <button type="button" className="btn-secondary" onClick={() => setOpen(true)}>
        <CalendarPlus className="size-4" /> Add to calendar
      </button>
      {open && (
        <Modal title="Subscribe in your calendar" onClose={() => setOpen(false)}>
          <p className="text-sm text-muted">
            Paste this private link into Outlook, Google Calendar or Apple Calendar ("Subscribe from URL"). Deadlines
            and cancel-by dates update automatically, with a reminder 7 days before each one.
          </p>
          <div className="mt-4 flex gap-2">
            <input className="input font-mono text-xs" readOnly value={url} aria-label="Calendar URL" />
            <button
              type="button"
              className="btn-primary shrink-0"
              onClick={() => {
                void navigator.clipboard?.writeText(url);
                setCopied(true);
              }}
            >
              <Copy className="size-4" /> {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="mt-3 text-xs text-muted">
            Anyone with the link can see your deadlines.
            {can("admin") && (
              <>
                {" "}
                <button
                  type="button"
                  className="font-medium text-brand-700 hover:underline"
                  onClick={() => rotate.mutate()}
                >
                  Reset link
                </button>{" "}
                to revoke old copies.
              </>
            )}
          </p>
        </Modal>
      )}
    </>
  );
}

function DigestSettings() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["notification-settings"], queryFn: api.notificationSettings });
  const [form, setForm] = useState<NotificationSettings | null>(null);
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);
  const save = useMutation({
    mutationFn: (s: NotificationSettings) =>
      api.updateNotificationSettings({
        digest_enabled: s.digest_enabled,
        digest_weekday: s.digest_weekday,
        digest_lead_days: s.digest_lead_days,
        recipient_user_ids: s.recipients.filter((r) => r.subscribed).map((r) => r.id),
      }),
    onSuccess: (d) => qc.setQueryData(["notification-settings"], d),
  });
  const send = useMutation({
    mutationFn: api.sendDigest,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notifications"] });
      void qc.invalidateQueries({ queryKey: ["notification-settings"] });
    },
  });
  if (!form) return <Card title="Weekly email digest">{<Spinner />}</Card>;
  const editable = can("admin");
  const dirty = JSON.stringify(form) !== JSON.stringify(data);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Mail className="size-4" /> Weekly email digest
        </span>
      }
    >
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4 accent-[#1f8a70]"
          checked={form.digest_enabled}
          disabled={!editable}
          onChange={(e) => setForm({ ...form, digest_enabled: e.target.checked })}
        />
        Email upcoming deadlines every
        <select
          className="input w-auto py-1 text-sm"
          value={form.digest_weekday}
          disabled={!editable}
          aria-label="Weekday"
          onChange={(e) => setForm({ ...form, digest_weekday: Number(e.target.value) })}
        >
          {WEEKDAYS.map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
      </label>
      <label className="mt-3 flex items-center gap-2 text-sm">
        Look ahead
        <select
          className="input w-auto py-1 text-sm"
          value={form.digest_lead_days}
          disabled={!editable}
          aria-label="Look-ahead window"
          onChange={(e) => setForm({ ...form, digest_lead_days: Number(e.target.value) })}
        >
          {[30, 60, 90, 120].map((d) => (
            <option key={d} value={d}>
              {d} days
            </option>
          ))}
        </select>
      </label>
      <div className="mt-4">
        <div className="label">Recipients</div>
        <ul className="space-y-1.5">
          {form.recipients.map((r) => (
            <li key={r.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-[#1f8a70]"
                  checked={r.subscribed}
                  disabled={!editable}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      recipients: form.recipients.map((x) =>
                        x.id === r.id ? { ...x, subscribed: e.target.checked } : x,
                      ),
                    })
                  }
                />
                <span className="font-medium">{r.name}</span>
                <span className="truncate text-xs text-muted">{r.email}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4 text-xs text-muted">
        {form.digest_last_sent_at ? `Last sent ${timeAgo(form.digest_last_sent_at)}.` : "Not sent yet."}
      </div>
      <ErrorNote error={save.error ?? send.error} />
      {editable && (
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate(form)}
          >
            Save
          </button>
          <button type="button" className="btn-secondary" disabled={send.isPending} onClick={() => send.mutate()}>
            <Send className="size-4" /> {send.isPending ? "Sending..." : "Send now"}
          </button>
          {send.data && (
            <span className="self-center text-xs text-brand-700">
              {send.data.status === "sent" ? `Sent to ${send.data.recipients.length}` : send.data.error}
            </span>
          )}
        </div>
      )}
    </Card>
  );
}

function RecentEmails() {
  const { can } = useAuth();
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: api.notifications, enabled: can("admin") });
  const [preview, setPreview] = useState<{ subject: string; html: string } | null>(null);
  if (!can("admin")) return null;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <MailCheck className="size-4" /> Recent alert emails
        </span>
      }
      bodyClassName="p-0"
    >
      {!data?.length ? (
        <Empty title="No emails yet" />
      ) : (
        <ul className="divide-y divide-line">
          {data.slice(0, 6).map((n) => (
            <li key={n.id} className="px-5 py-3">
              <div className="flex items-start justify-between gap-3">
                <button
                  type="button"
                  className="text-left text-sm font-medium text-brand-700 hover:underline"
                  onClick={async () => setPreview({ subject: n.subject, html: await api.notificationHtml(n.id) })}
                >
                  {n.subject}
                </button>
                <span
                  className={clsx(
                    "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                    n.status === "sent"
                      ? "bg-brand-50 text-brand-700"
                      : n.status === "failed"
                        ? "bg-red-50 text-red-700"
                        : "bg-paper text-muted",
                  )}
                >
                  {n.status}
                </span>
              </div>
              <div className="mt-0.5 text-xs text-muted">
                {formatDateTime(n.created_at)} · {n.recipients.length} recipient(s) via {n.transport}
                {n.error ? ` · ${n.error}` : ""}
              </div>
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <Modal title={preview.subject} onClose={() => setPreview(null)} wide>
          <iframe
            title="Email preview"
            srcDoc={preview.html}
            sandbox=""
            className="h-[70vh] w-full rounded-lg border border-line"
          />
        </Modal>
      )}
    </Card>
  );
}

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-night/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("card w-full p-5", wide ? "max-w-3xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
            <X className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
