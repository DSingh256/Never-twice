/* Thin read-only client for the Never Twice API (from the UI's perspective). */

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

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
  [k: string]: unknown;
};

export type AnalysisDetail = AnalysisRow & {
  diff?: string | null;
  verdict?: Verdict | null;
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

export type EvalRunSummary = {
  runs: Array<{
    id: string;
    created_at: string | null;
    conditions: string[];
    items: number;
    summary?: Record<string, unknown>;
  }>;
};

export type EvalRunDetail = {
  id?: string;
  created_at?: string | null;
  conditions?: string[];
  items?: Array<{
    id?: number;
    incident_id?: number;
    condition?: string;
    level?: string | null;
    confidence?: number | null;
    correct?: boolean | null;
    [k: string]: unknown;
  }>;
  summary?: Record<string, unknown>;
  error?: string | null;
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

  evalRuns: () =>
    getJson<EvalRunSummary>("/api/eval/runs", { runs: [] }),

  evalRun: (id: string) =>
    getJson<EvalRunDetail | null>(`/api/eval/runs/${encodeURIComponent(id)}`, null),
};

export { BASE as API_BASE };
