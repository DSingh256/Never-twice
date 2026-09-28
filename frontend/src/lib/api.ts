/* Thin read-only client for the Never Twice API (from the UI's perspective).
 * Always absolute: server components run in Node (a relative path would fail
 * there), and the browser pages live on a different port than the API. */

const BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type Health = {
  status: string;
  hindsight: { ok: boolean; bank_id?: string; version?: string };
  llm: { ok: boolean; model?: string };
  database: { ok: boolean };
};

export type AnalysisRow = {
  id: number;
  status: string;
  service: string | null;
  pr_title: string | null;
  level: string | null;
  confidence: number | null;
  evidence_count: number | null;
  created_at: string | null;
};

export type Verdict = {
  level?: string;
  rationale?: string;
  matched_incidents?: Array<{
    title?: string;
    source_url?: string | null;
    why_similar?: string;
    what_failed_before?: string;
    what_worked?: string | null;
  }>;
  suggested_checks?: string[];
  learned_from_feedback?: Array<{ note?: string | null }>;
  supporting_memory_ids?: string[];
  [k: string]: unknown;
};

export type AnalysisDetail = AnalysisRow & {
  diff?: string | null;
  verdict?: Verdict | null;
  change_facts?: { summary?: string; change_category?: string; [k: string]: unknown } | null;
  error?: string | null;
};

export type FeedbackRow = {
  id: number;
  analysis_id: number;
  verdict: string;
  note: string | null;
  reviewer: string | null;
  created_at: string | null;
};

export type MemoryListResult = {
  memories: Array<{
    id: string;
    text?: string;
    content?: string;
    created_at?: string | null;
    tags?: string[];
  }>;
  total?: number;
};

export type MemoryStats = {
  bank_id: string;
  total_memory_units: number;
  documents: number;
  by_type: Record<string, number>;
  audit: {
    retained_rows: number;
    incidents_memory_split: number;
    incidents_heldout_split: number;
  };
  app_totals: { analyses: number; feedback: number };
};

export type EvalRunSummary = {
  runs: Array<{
    id: string;
    status: string;
    label: string | null;
    item_count: number;
    created_at: string | null;
    summary?: Record<string, unknown> | null;
    error?: string | null;
  }>;
};

export type EvalRunDetail = {
  id?: string;
  status?: string;
  created_at?: string | null;
  items?: Array<{
    id?: number;
    case_id?: string;
    condition?: string;
    expected_label?: number;
    predicted_level?: string | null;
    predicted_positive?: boolean;
    correct?: boolean | null;
    confidence?: number | null;
    evidence_count?: number;
    latency_ms?: number | null;
    error?: string | null;
  }>;
  config_snapshot?: Record<string, unknown> | null;
  summary?: Record<string, unknown> | null;
  error?: string | null;
};

export type MemoryHitDto = {
  id: string;
  text: string;
  score: number;
  fact_type?: string;
  tags?: string[];
  document_id?: string | null;
};

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export const api = {
  health: () =>
    getJson<Health | null>("/api/health", null),

  analyses: (limit = 50) =>
    getJson<{ analyses: AnalysisRow[] }>(
      `/api/analyses?limit=${limit}`,
      { analyses: [] }
    ),

  analysis: (id: number) =>
    getJson<AnalysisDetail | null>(`/api/analyses/${id}`, null),

  feedback: (limit = 100) =>
    getJson<{ feedback: FeedbackRow[] }>(
      `/api/feedback?limit=${limit}`,
      { feedback: [] }
    ),

  memories: (tag: string, limit = 50) =>
    getJson<MemoryListResult>(
      `/api/memory/list?tag=${encodeURIComponent(tag)}&limit=${limit}`,
      { memories: [] }
    ),

  memoryStats: () =>
    getJson<MemoryStats | null>("/api/memory/stats", null),

  evalRuns: () =>
    getJson<EvalRunSummary>("/api/eval/runs", { runs: [] }),

  evalRun: (id: string) =>
    getJson<EvalRunDetail | null>(`/api/eval/runs/${encodeURIComponent(id)}`, null),

  /** Live recall against the bank — the same operation the verdict uses. */
  memorySearch: (q: string, limit = 24) =>
    getJson<{ memories: MemoryHitDto[] }>(
      `/api/memory/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      { memories: [] }
    ),
};

export { BASE as API_BASE };
