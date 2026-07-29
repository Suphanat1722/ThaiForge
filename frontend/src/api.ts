export type Counts = {
  pending: number;
  in_progress: number;
  done: number;
  failed: number;
  skipped: number;
  retranslation_pending: number;
  retranslation_in_progress: number;
  retranslation_failed: number;
  retryable_failed: number;
  retranslation_retryable_failed: number;
};

export type QuotaUsage = {
  used: number;
  budget: number;
  warning_at: number;
  reset_at: string;
  quota_day: string;
};

export type FailureSummary = {
  quota: number;
  protected_format: number;
  temporary_service: number;
  permanent: number;
};

export type QuotaEfficiency = {
  requests: number;
  cache_hits: number;
  deduplicated_rows: number;
  requests_saved: number;
  average_rows_per_request: number;
  planned_input_tokens: number;
  planned_output_tokens: number;
};

export type Job = {
  id: string;
  filename: string;
  status: string;
  encoding: string;
  delimiter: string;
  headers: string[];
  preview: Record<string, string>[];
  source_column: string | null;
  target_column: string | null;
  context_columns: string[];
  source_lang: string | null;
  target_lang: string | null;
  total_rows: number;
  completed_rows: number;
  glossary_revision: number;
  style_revision: number;
  glossary_rules_revision: number;
  glossary_rules_applied_revision: number;
  last_error: string | null;
  ai_calls: number;
  input_tokens: number;
  output_tokens: number;
  glossary_chunks_total: number;
  glossary_chunks_completed: number;
  pause_reason: string | null;
  quota_resume_at: string | null;
  quota_usage?: QuotaUsage;
  failure_summary?: FailureSummary;
  quota_efficiency?: QuotaEfficiency;
  created_at: string;
  updated_at: string;
  counts?: Counts;
  style_rules?: StyleRule[];
  glossary_rule_settings?: GlossaryRuleSettings;
};

export type GlossaryEntry = {
  id: string;
  source_term: string;
  target_term: string;
  rule_note: string;
  is_active: number;
  created_by: "ai" | "user";
  revision: number;
  translation_mode: "translate" | "transliterate" | "keep" | "mixed";
};

export type StyleRule = {
  id: string;
  rule_text: string;
  revision: number;
};

export type GlossaryRuleSettings = {
  rules: string[];
  revision: number;
  applied_revision: number;
  needs_regeneration: boolean;
};

export type TranslationRow = {
  id: string;
  row_index: number;
  source_text: string;
  original_target: string;
  translated_text: string | null;
  status: string;
  total_attempts: number;
  last_error: string | null;
  failure_class: string | null;
  retryable: number;
  next_attempt_at: string | null;
  context: Record<string, string>;
  updated_at: string;
};

export type ScanItem = {
  row_id: string;
  row_index: number;
  source_text: string;
  translated_text: string;
  reasons: { entry_id: string; source_term: string; reason: string }[];
};

export type Scan = {
  id: string;
  job_id: string;
  glossary_revision: number;
  status: string;
  candidate_count: number;
  items: ScanItem[];
  page: number;
  page_size: number;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" &&
            detail !== null &&
            "message" in detail
          ? String((detail as { message: unknown }).message)
          : "เกิดข้อผิดพลาดจากระบบ";
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = payload.detail ?? detail;
    } catch {
      // Keep the HTTP status text for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
