import type {
  ActionItem,
  AskResponse,
  DeadlinesResponse,
  NotificationRecord,
  NotificationSettings,
  Rule,
  RuleKindSpec,
  AuditEvent,
  DocumentDetail,
  DocumentPage,
  DocumentSummary,
  HistoryItem,
  Overview,
  Role,
  TokenResponse,
  User,
} from "./types";

const TOKEN_KEY = "docpilot.token";

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;

  constructor(status: number, message: string, requestId: string | null) {
    super(message);
    this.status = status;
    this.requestId = requestId;
  }
}

export const tokenStore = {
  get: (): string | null => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string | null) => {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable (private mode) - session-only login */
    }
  },
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object" && "msg" in detail[0]) {
      return String((detail[0] as { msg: unknown }).msg);
    }
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && token) onUnauthorized?.();
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, errorMessage(body, res.statusText), res.headers.get("x-request-id"));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export interface DocumentFilters {
  q?: string;
  status?: string;
  doc_type?: string;
  risk?: string;
  policy?: string;
  page?: number;
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", { method: "POST", body: json({ email, password }) }),
  register: (org_name: string, name: string, email: string, password: string) =>
    request<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: json({ org_name, name, email, password }),
    }),
  me: () => request<TokenResponse>("/api/auth/me"),

  documents: (filters: DocumentFilters = {}) => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) if (v !== undefined && v !== "") params.set(k, String(v));
    return request<DocumentPage>(`/api/documents?${params.toString()}`);
  },
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentSummary>("/api/documents", { method: "POST", body: form });
  },
  reprocess: (id: string) => request<DocumentSummary>(`/api/documents/${id}/reprocess`, { method: "POST" }),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  exportCsv: async () => {
    const res = await fetch("/api/documents/export/insights.csv", {
      headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` },
    });
    if (!res.ok) throw new ApiError(res.status, "Export failed", res.headers.get("x-request-id"));
    return res.blob();
  },

  ask: (question: string, document_id?: string) =>
    request<AskResponse>("/api/ask", { method: "POST", body: json({ question, document_id }) }),
  history: (document_id?: string) =>
    request<HistoryItem[]>(`/api/ask/history${document_id ? `?document_id=${document_id}` : ""}`),

  overview: () => request<Overview>("/api/analytics/overview"),

  users: () => request<User[]>("/api/admin/users"),
  createUser: (body: { name: string; email: string; password: string; role: Role }) =>
    request<User>("/api/admin/users", { method: "POST", body: json(body) }),
  updateRole: (id: string, role: Role) =>
    request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: json({ role }) }),
  audit: () => request<AuditEvent[]>("/api/admin/audit?limit=100"),

  deadlines: (opts: { includeHandled?: boolean; documentId?: string; horizonDays?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.includeHandled) params.set("include_handled", "true");
    if (opts.documentId) params.set("document_id", opts.documentId);
    if (opts.horizonDays) params.set("horizon_days", String(opts.horizonDays));
    return request<DeadlinesResponse>(`/api/deadlines?${params.toString()}`);
  },
  markHandled: (item: ActionItem, note = "") =>
    request<{ status: string }>("/api/deadlines/handled", {
      method: "POST",
      body: json({ document_id: item.document_id, key: item.key, note }),
    }),
  reopen: (item: ActionItem) =>
    request<void>(`/api/deadlines/handled?document_id=${item.document_id}&key=${encodeURIComponent(item.key)}`, {
      method: "DELETE",
    }),
  calendar: () => request<{ path: string }>("/api/deadlines/calendar"),
  rotateCalendar: () => request<{ path: string }>("/api/deadlines/calendar/rotate", { method: "POST" }),

  rules: () => request<Rule[]>("/api/rules"),
  ruleKinds: () => request<Record<string, RuleKindSpec>>("/api/rules/kinds"),
  createRule: (body: Omit<Rule, "id" | "created_at" | "violations" | "not_evaluated">) =>
    request<Rule>("/api/rules", { method: "POST", body: json(body) }),
  updateRule: (id: string, body: Partial<Rule>) =>
    request<Rule>(`/api/rules/${id}`, { method: "PATCH", body: json(body) }),
  deleteRule: (id: string) => request<void>(`/api/rules/${id}`, { method: "DELETE" }),

  notificationSettings: () => request<NotificationSettings>("/api/notifications/settings"),
  updateNotificationSettings: (body: {
    digest_enabled: boolean;
    digest_weekday: number;
    digest_lead_days: number;
    recipient_user_ids: string[];
  }) => request<NotificationSettings>("/api/notifications/settings", { method: "PUT", body: json(body) }),
  sendDigest: () => request<NotificationRecord>("/api/notifications/digest/send", { method: "POST" }),
  notifications: () => request<NotificationRecord[]>("/api/notifications"),
  notificationHtml: async (id: string) => {
    const res = await fetch(`/api/notifications/${id}/html`, {
      headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` },
    });
    if (!res.ok) throw new ApiError(res.status, "Could not load email", res.headers.get("x-request-id"));
    return res.text();
  },
};
