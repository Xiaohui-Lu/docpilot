export type Role = "admin" | "member" | "viewer";
export type RiskLevel = "low" | "medium" | "high";
export type DocStatus = "queued" | "processing" | "ready" | "failed";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  org_id: string;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
  org_name: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocStatus;
  error: string | null;
  title: string | null;
  doc_type: string | null;
  overall_risk: RiskLevel | null;
  page_count: number;
  created_at: string;
  processed_at: string | null;
  processing_ms: number | null;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  policy_violations: number;
}

export interface Party {
  name: string;
  role: string;
}
export interface KeyDate {
  label: string;
  date: string;
  source_quote: string;
}
export interface Amount {
  label: string;
  value: number;
  currency: string;
}
export interface Risk {
  severity: RiskLevel;
  title: string;
  explanation: string;
  source_quote: string;
}

export interface Insights {
  doc_type: string;
  title: string;
  summary: string;
  parties: Party[];
  key_dates: KeyDate[];
  amounts: Amount[];
  obligations: string[];
  risks: Risk[];
  overall_risk: RiskLevel;
  renewal?: {
    auto_renews: boolean;
    term_end_date: string;
    notice_days: number;
    renewal_term_months: number;
    source_quote: string;
  };
  payment_terms_days?: number;
}

export interface GroundingItem {
  kind: "date" | "risk";
  index: number;
  grounded: boolean;
}

export interface Grounding {
  checked: number;
  grounded: number;
  ungrounded: number;
  score: number;
  items: GroundingItem[];
}

export interface Job {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  insights: Insights | null;
  grounding: Grounding | null;
  policy_findings: PolicyFinding[] | null;
  text: string;
  jobs: Job[];
}

export interface DocumentPage {
  items: DocumentSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Citation {
  document_id: string;
  document_title: string;
  chunk_id: string;
  chunk_index: number;
  quote: string;
}

export interface AskResponse {
  id: string;
  answer: string;
  citations: Citation[];
  provider: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface HistoryItem {
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  document_id: string | null;
  created_at: string;
  provider: string;
}

export interface Overview {
  generated_at: string;
  documents: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    by_risk: Record<string, number>;
  };
  top_risks: { title: string; count: number }[];
  upcoming_dates: {
    document_id: string;
    document_title: string;
    label: string;
    date: string;
    days_left: number;
    kind: string;
    urgency: Urgency;
  }[];
  deadlines: {
    overdue: number;
    next_14_days: number;
    next_30_days: number;
    next_cancel_by: ActionItem | null;
  };
  policy: {
    documents_with_violations: number;
    violations: number;
    top_rules: { rule: string; count: number }[];
  };
  contract_value: { currency: string; value: number }[];
  timeline: { date: string; uploads: number }[];
  processing: {
    p50_ms: number | null;
    p95_ms: number | null;
    jobs: Record<string, number>;
    jobs_retried: number;
  };
  grounding: { checked: number; grounded: number; score: number | null };
  llm: {
    document_tokens: number;
    document_cost_usd: number;
    questions: number;
    question_tokens: number;
    question_cost_usd: number;
  };
}

export interface AuditEvent {
  id: string;
  user_email: string | null;
  action: string;
  target: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export type Urgency = "overdue" | "urgent" | "soon" | "upcoming";

export interface ActionItem {
  key: string;
  document_id: string;
  document_title: string;
  kind: string;
  label: string;
  date: string;
  days_left: number;
  urgency: Urgency;
  detail: string;
  source_quote: string;
  handled: boolean;
  handled_by: string | null;
  handled_at: string | null;
  note: string;
}

export interface DeadlinesResponse {
  items: ActionItem[];
  counts: Record<Urgency, number>;
}

export type FindingStatus = "pass" | "fail" | "not_evaluated";

export interface PolicyFinding {
  rule_id: string;
  rule_name: string;
  kind: string;
  severity: RiskLevel;
  status: FindingStatus;
  message: string;
  source_quote: string;
}

export interface Rule {
  id: string;
  name: string;
  description: string;
  kind: string;
  params: Record<string, unknown>;
  severity: RiskLevel;
  doc_types: string[];
  enabled: boolean;
  created_at: string;
  violations: number;
  not_evaluated: number;
}

export interface RuleParamSpec {
  name: string;
  type: "int" | "number" | "string" | "list" | "text";
  label: string;
  default: unknown;
}

export interface RuleKindSpec {
  label: string;
  help: string;
  params: RuleParamSpec[];
  ai?: boolean;
}

export interface NotificationSettings {
  digest_enabled: boolean;
  digest_weekday: number;
  digest_lead_days: number;
  digest_last_sent_at: string | null;
  recipients: { id: string; name: string; email: string; role: Role; subscribed: boolean }[];
}

export interface NotificationRecord {
  id: string;
  kind: string;
  subject: string;
  recipients: string[];
  item_count: number;
  transport: string;
  status: "sent" | "failed" | "skipped";
  error: string | null;
  created_at: string;
}
