export function formatDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!iso) return "-";
  const d = iso.length === 10 ? new Date(`${iso}T00:00:00`) : new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", ...opts });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function timeAgo(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [604800, "day"],
    [2629800, "week"],
    [31557600, "month"],
  ];
  let unitSeconds = 1;
  for (const [limit, unit] of steps) {
    if (seconds < limit) return rtf.format(-Math.round(seconds / unitSeconds), unit);
    unitSeconds = limit;
  }
  return rtf.format(-Math.round(seconds / 31557600), "year");
}

export function formatMoney(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toLocaleString()} ${currency}`;
  }
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const DOC_TYPE_LABEL: Record<string, string> = {
  contract: "Contract",
  nda: "NDA",
  invoice: "Invoice",
  policy: "Policy",
  other: "Other",
};

/** Split text into segments, marking those that match `needle` (case/whitespace-insensitive). */
export function highlight(text: string, needle: string | null): { text: string; match: boolean }[] {
  if (!needle) return [{ text, match: false }];
  const pattern = needle
    .trim()
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
  if (!pattern) return [{ text, match: false }];
  const re = new RegExp(pattern, "i");
  const m = re.exec(text);
  if (!m) return [{ text, match: false }];
  return [
    { text: text.slice(0, m.index), match: false },
    { text: m[0], match: true },
    { text: text.slice(m.index + m[0].length), match: false },
  ];
}
