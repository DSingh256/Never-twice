"use client";

/* Live analysis replay: consumes the backend's SSE stream for one analysis.
 * Steps arrive in analysis order; the final event carries the verdict. */

import { useEffect, useRef, useState } from "react";
import { API_BASE, type AnalysisDetail, type Verdict } from "@/lib/api";
import { LevelStamp } from "./ui";

type Step = { seq: number; name: string; detail?: string };

export function StepStream({
  analysisId,
  done,
}: {
  analysisId: number;
  done: boolean;
}) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [status, setStatus] = useState<string>("done");
  const started = useRef(false);

  useEffect(() => {
    // A finished analysis is replayed from persisted steps via the same
    // SSE endpoint; a running one streams live. Either way we just listen.
    if (started.current) return;
    started.current = true;

    const es = new EventSource(`${API_BASE}/api/analyze/${analysisId}/stream`);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (payload.type === "step") {
          setSteps((prev) => [
            ...prev,
            {
              seq: payload.seq,
              name: payload.name,
              detail: payload.detail,
            },
          ]);
        } else if (payload.status === "done" || payload.status === "failed") {
          if (payload.verdict) setVerdict(payload.verdict as Verdict);
          setStatus(payload.status);
          es.close();
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    es.onerror = () => {
      es.close();
      setStatus((s) => (s === "done" ? "done" : "failed"));
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  return (
    <div>
      <ol className="space-y-1 font-mono text-xs">
        {steps.map((s) => (
          <li key={s.seq} className="flex gap-2">
            <span className="text-ink-soft">{String(s.seq).padStart(2, "0")}</span>
            <span className="font-semibold">{s.name}</span>
            {s.detail ? (
              <span className="truncate text-ink-soft">— {s.detail}</span>
            ) : null}
          </li>
        ))}
        {steps.length === 0 && done ? (
          <li className="text-ink-soft">steps archived (stream closed)</li>
        ) : null}
      </ol>

      {status === "done" && verdict ? (
        <div className="mt-4 border-t border-line pt-3">
          <div className="flex items-center gap-3">
            <LevelStamp level={verdict.level} />
            <span className="evidence-label">
              evidence {String(verdict.evidence_count ?? 0)}
            </span>
          </div>
          {verdict.rationale ? (
            <p className="mt-2 font-display text-sm leading-relaxed">
              {verdict.rationale}
            </p>
          ) : null}
        </div>
      ) : null}
      {status === "failed" ? (
        <p className="mt-3 font-mono text-xs text-danger">
          analysis failed — see archive record for the error
        </p>
      ) : null}
    </div>
  );
}

export function AnalysisRoom({ initial }: { initial: AnalysisDetail | null }) {
  const [text, setText] = useState("");
  const [id, setId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalysisDetail | null>(initial);

  async function run() {
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    setDetail(null);
    try {
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ diff: text, pr_title: "Manual console submission" }),
      });
      if (!res.ok) throw new Error(`analyze failed (${res.status})`);
      const data = (await res.json()) as { analysis_id: number };
      setId(data.analysis_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        spellCheck={false}
        placeholder={"Paste a unified diff here, e.g.\n\n-  min_healthy_hosts = 2\n+  min_healthy_hosts = 0"}
        className="w-full border border-line bg-paper-raised p-3 font-mono text-xs focus:border-accent focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={run}
          disabled={busy || !text.trim()}
          className="border border-ink bg-ink px-4 py-1.5 font-mono text-xs uppercase tracking-widest text-paper disabled:opacity-40"
        >
          {busy ? "dispatching…" : "run verdict"}
        </button>
        {err ? <span className="font-mono text-xs text-danger">{err}</span> : null}
      </div>
      {id != null ? <StepStream analysisId={id} done={false} /> : null}
      {detail?.verdict ? (
        <p className="font-mono text-xs text-ink-soft">
          archived analysis #{detail.id}
        </p>
      ) : null}
    </div>
  );
}
