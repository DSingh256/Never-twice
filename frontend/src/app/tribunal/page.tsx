"use client";

/* The Tribunal — live A/B/C cross-examination of a single diff.
 *
 * Witness A: the naked model. No memory. What any generic LLM gate knows.
 * Witness B: the model shown recalled memories as plain context.
 * Witness C: the full production pipeline (recall + reflect + feedback).
 *
 * The delta between A and C is the measured value of organizational memory,
 * on the caller's own change, in under a minute. No sample data: every
 * witness verdict is a real model call against the real memory bank.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { API_BASE } from "@/lib/api";

type Witness = {
  condition: "A" | "B" | "C" | undefined;
  status: "pending" | "running" | "ok" | "failed" | undefined;
  level?: string | null;
  rationale?: string | null;
  suggested_checks?: string[];
  matched_incidents?: Array<{
    title?: string;
    why_similar?: string;
    what_failed_before?: string;
  }>;
  learned_from_feedback?: Array<{ note?: string | null }>;
  confidence?: number | null;
  evidence_count?: number;
  latency_ms?: number | null;
  error?: string | null;
};

type Delta = {
  confidence_a?: number | null;
  confidence_c?: number | null;
  level_a?: string | null;
  level_c?: string | null;
  level_rank_shift?: number;
};

type TribunalData = {
  id: number;
  status: string;
  pr_title?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  witnesses: Witness[];
  delta?: Delta | null;
};

const LEVEL_STAMP: Record<string, { word: string; cls: string }> = {
  high: { word: "HIGH RISK", cls: "text-signal-red" },
  medium: { word: "REVIEW REQUIRED", cls: "text-amber" },
  low: { word: "LOW RISK", cls: "text-sage" },
  none: { word: "CLEARED", cls: "text-vellum-dim" },
};

const SAMPLE_RISKY = `diff --git a/infra/dns-resolver/terraform/main.tf b/infra/dns-resolver/terraform/main.tf
--- a/infra/dns-resolver/terraform/main.tf
+++ b/infra/dns-resolver/terraform/main.tf
@@ -14,9 +14,7 @@
-  min_healthy_hosts = 2
+  min_healthy_hosts = 0
`;

const SAMPLE_SAFE = `diff --git a/docs/runbooks/dns-resolver.md b/docs/runbooks/dns-resolver.md
--- a/docs/runbooks/dns-resolver.md
+++ b/docs/runbooks/dns-resolver.md
@@ -1,5 +1,7 @@
 # DNS resolver runbook
+
+## Escalation
+Page the on-call SRE only after two consecutive health-check failures.
 `;

const WITNESS_META: Record<
  string,
  { seat: string; name: string; brief: string }
> = {
  A: {
    seat: "WITNESS A",
    name: "The naked model",
    brief: "Knows nothing about this organization. What a generic LLM gate sees.",
  },
  B: {
    seat: "WITNESS B",
    name: "Shown the archive",
    brief: "The same model, given recalled memories as plain context.",
  },
  C: {
    seat: "WITNESS C",
    name: "The full pipeline",
    brief: "Production: recall + reflect against the archive + engineer feedback.",
  },
};

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-1.5 w-full max-w-40 bg-hairline">
        <motion.div
          className="absolute left-0 top-0 h-full bg-amber"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.9, ease: "easeOut" }}
        />
      </div>
      <span className="tag-mono text-xs text-vellum">{pct}%</span>
    </div>
  );
}

function WitnessCard({ witness }: { witness: Witness }) {
  const meta = WITNESS_META[witness.condition ?? "A"];
  const status = witness.status ?? "pending";
  const stamp = witness.level ? LEVEL_STAMP[witness.level] : null;

  return (
    <div className="brackets case-file flex min-h-[22rem] flex-col p-5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="plate text-amber">{meta.seat}</p>
        <span className="tag-mono text-[10px] text-vellum-faint">
          {status === "ok" && witness.latency_ms != null
            ? `${(witness.latency_ms / 1000).toFixed(1)}s`
            : status === "running"
              ? "testifying…"
              : status === "pending"
                ? "seat held"
                : ""}
        </span>
      </div>
      <h3 className="display-serif mt-2 text-xl text-vellum">{meta.name}</h3>
      <p className="mt-1 min-h-8 font-grotesk text-[11px] leading-snug text-vellum-faint">
        {meta.brief}
      </p>

      <div className="mt-4 flex-1">
        {status === "pending" && (
          <p className="mt-6 font-mono text-xs text-vellum-faint">
            — awaiting its turn —
          </p>
        )}
        {status === "running" && (
          <div className="mt-6 flex items-center gap-2 font-mono text-xs text-vellum-dim">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber" />
            cross-examining the change…
          </div>
        )}
        {status === "failed" && (
          <p className="mt-2 border border-signal-red/40 bg-signal-red/10 p-3 font-mono text-[11px] leading-snug text-signal-red">
            {witness.error ?? "witness refused to testify"}
          </p>
        )}
        {status === "ok" && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            {stamp && (
              <div
                className={`inline-block border-2 border-double border-current px-3 py-1 font-mono text-sm font-bold tracking-[0.1em] ${stamp.cls}`}
                style={{ transform: "rotate(-2deg)" }}
              >
                {stamp.word}
              </div>
            )}
            <div className="mt-3">
              <ConfidenceMeter value={witness.confidence ?? 0} />
            </div>
            <p className="mt-3 font-grotesk text-[12px] leading-relaxed text-vellum-dim">
              {witness.rationale}
            </p>
            {witness.matched_incidents && witness.matched_incidents.length > 0 && (
              <div className="mt-3 border-l-2 border-amber/50 pl-3">
                <p className="plate">
                  cites {witness.matched_incidents.length} incident
                  {witness.matched_incidents.length === 1 ? "" : "s"}
                </p>
                {witness.matched_incidents.slice(0, 2).map((mi, i) => (
                  <p key={i} className="mt-1 line-clamp-2 font-grotesk text-[11px] text-vellum-faint">
                    {orNull(mi.why_similar) || orNull(mi.title) || "incident memory"}
                  </p>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-hairline pt-2 font-mono text-[10px] text-vellum-faint">
        <span className="plate">evidence</span>
        <span className="tag-mono text-vellum-dim">{witness.evidence_count ?? 0}</span>
      </div>
    </div>
  );
}

/** Honest display string: LLM "null" literals (or empty) mean no data. */
const orNull = (s: string | null | undefined) =>
  s && s.trim().toLowerCase() !== "null" ? s : null;

function DeltaPanel({ delta, witnessC }: { delta: Delta; witnessC: Witness }) {
  const a = delta.confidence_a ?? 0;
  const c = delta.confidence_c ?? 0;
  const gain = Math.round((c - a) * 1000) / 10;
  const shift = delta.level_rank_shift ?? 0;
  const feedbackCount = witnessC.learned_from_feedback?.length ?? 0;

  return (
    <motion.section
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
      className="mt-10"
    >
      <div className="hazard-strip mb-6 opacity-40" />
      <p className="plate text-amber">THE DELTA — WHAT THE ARCHIVE CHANGED</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="case-file p-5">
          <p className="plate">confidence shift</p>
          <p className="display-serif mt-2 text-4xl text-vellum">
            {gain > 0 ? `+${gain}` : gain}
            <span className="text-xl text-vellum-dim">pts</span>
          </p>
          <p className="mt-2 font-mono text-[11px] text-vellum-faint">
            witness A {Math.round(a * 100)}% → witness C {Math.round(c * 100)}%
          </p>
        </div>
        <div className="case-file p-5">
          <p className="plate">verdict shift</p>
          <p className="display-serif mt-2 text-2xl text-vellum">
            {delta.level_a ?? "—"}{" "}
            <span className={shift > 0 ? "text-signal-red" : shift < 0 ? "text-sage" : "text-vellum-faint"}>
              {shift > 0 ? "↑" : shift < 0 ? "↓" : "→"}
            </span>{" "}
            {delta.level_c ?? "—"}
          </p>
          <p className="mt-2 font-mono text-[11px] text-vellum-faint">
            {shift > 0
              ? "the archive escalated this change"
              : shift < 0
                ? "the archive de-escalated this change"
                : "same level; memory changed the grounding"}
          </p>
        </div>
        <div className="case-file p-5">
          <p className="plate">lived experience applied</p>
          <p className="display-serif mt-2 text-4xl text-vellum">
            {feedbackCount}
            <span className="text-xl text-vellum-dim"> feedback memories</span>
          </p>
          <p className="mt-2 font-mono text-[11px] text-vellum-faint">
            engineer lessons the verdict stood on
          </p>
        </div>
      </div>

      {witnessC.matched_incidents && witnessC.matched_incidents.length > 0 && (
        <div className="case-file mt-4 p-5">
          <p className="plate text-amber">THE ARCHIVE SPOKE — WITNESS C&apos;S CITATIONS</p>
          <ul className="mt-3 space-y-3">
            {witnessC.matched_incidents.slice(0, 3).map((mi, i) => (
              <li key={i} className="border-l-2 border-amber/50 pl-3">
                <p className="font-grotesk text-sm text-vellum">
                  {mi.title || "incident memory"}
                </p>
                {orNull(mi.why_similar) && (
                  <p className="mt-0.5 font-grotesk text-xs text-vellum-dim">
                    {orNull(mi.why_similar)}
                  </p>
                )}
                {orNull(mi.what_failed_before) && (
                  <p className="mt-0.5 font-mono text-[11px] text-signal-red/90">
                    failed before: {orNull(mi.what_failed_before)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </motion.section>
  );
}

export default function TribunalPage() {
  const [diff, setDiff] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [tribunal, setTribunal] = useState<TribunalData | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (pollRef.current) clearTimeout(pollRef.current);
  }, []);

  const poll = useCallback((id: number) => {
    const tick = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tribunal/${id}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`poll failed (${res.status})`);
        const data: TribunalData = await res.json();
        setTribunal(data);
        if (data.status === "running") {
          pollRef.current = setTimeout(tick, 2000);
        }
      } catch (e) {
        setSubmitError(e instanceof Error ? e.message : String(e));
      }
    };
    pollRef.current = setTimeout(tick, 600);
  }, []);

  const convene = async () => {
    if (!diff.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    setTribunal(null);
    try {
      const res = await fetch(`${API_BASE}/api/tribunal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ diff, pr_title: prTitle || null }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? `convene failed (${res.status})`);
      }
      const { tribunal_id } = (await res.json()) as { tribunal_id: number };
      poll(tribunal_id);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const running = tribunal?.status === "running";
  const wA = tribunal?.witnesses.find((w) => w.condition === "A");
  const wB = tribunal?.witnesses.find((w) => w.condition === "B");
  const wC = tribunal?.witnesses.find((w) => w.condition === "C");

  return (
    <main className="archive-night min-h-screen px-5 py-12 md:px-10">
      <div className="mx-auto max-w-6xl">
        <header>
          <p className="plate text-amber">BLACK BOX ARCHIVE · THE TRIBUNAL</p>
          <h1 className="display-serif mt-3 text-3xl text-vellum md:text-5xl">
            Three judges. One diff.
            <br />
            Only two have read the archive.
          </h1>
          <p className="mt-4 max-w-2xl font-grotesk text-sm text-vellum-dim">
            The same change is cross-examined three times: by the naked model,
            by the model shown recalled memories, and by the full production
            pipeline. The delta is the measured value of organizational memory
            — on your change, live, with no sample data.
          </p>
        </header>

        {/* --- the exhibit: submit a diff --- */}
        <section className="brackets case-file mt-10 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="plate">EXHIBIT A — THE CHANGE UNDER REVIEW</p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setDiff(SAMPLE_RISKY)}
                className="border border-hairline px-2 py-1 font-mono text-[10px] text-vellum-dim transition-colors hover:border-amber-line hover:text-amber"
              >
                load the dns-resolver diff
              </button>
              <button
                type="button"
                onClick={() => setDiff(SAMPLE_SAFE)}
                className="border border-hairline px-2 py-1 font-mono text-[10px] text-vellum-dim transition-colors hover:border-amber-line hover:text-amber"
              >
                load a safe diff
              </button>
            </div>
          </div>
          <textarea
            value={diff}
            onChange={(e) => setDiff(e.target.value)}
            placeholder="Paste a unified diff here…"
            spellCheck={false}
            className="mt-3 h-40 w-full resize-y border border-hairline bg-night-2 p-4 font-mono text-[11px] leading-relaxed text-vellum outline-none placeholder:text-vellum-faint focus:border-amber-line"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <input
              value={prTitle}
              onChange={(e) => setPrTitle(e.target.value)}
              placeholder="PR title (optional)"
              className="min-w-64 flex-1 border border-hairline bg-night-2 px-3 py-2 font-mono text-xs text-vellum outline-none placeholder:text-vellum-faint focus:border-amber-line"
            />
            <button
              type="button"
              onClick={convene}
              disabled={!diff.trim() || submitting || running}
              className={`cursor-pointer border px-5 py-2 font-mono text-xs tracking-[0.14em] uppercase transition-colors ${
                !diff.trim() || submitting || running
                  ? "cursor-not-allowed border-hairline text-vellum-faint"
                  : "border-amber-line bg-amber-soft text-amber hover:bg-amber hover:text-night"
              }`}
            >
              {submitting ? "convening…" : running ? "tribunal in session…" : "convene the tribunal"}
            </button>
            {tribunal && (
              <span className="tag-mono text-[10px] text-vellum-faint">
                case #{tribunal.id}
                {tribunal.duration_ms != null && tribunal.status !== "running"
                  ? ` · ${(tribunal.duration_ms / 1000).toFixed(1)}s total`
                  : ""}
              </span>
            )}
          </div>
          {submitError && (
            <p className="mt-3 border border-signal-red/40 bg-signal-red/10 p-3 font-mono text-[11px] text-signal-red">
              {submitError}
            </p>
          )}
        </section>

        {/* --- the three witnesses --- */}
        {tribunal && (
          <section className="mt-10">
            <p className="plate">THE PANEL — SAME DIFF, THREE DEGREES OF MEMORY</p>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <WitnessCard witness={wA ?? { condition: "A", status: "pending" }} />
              <WitnessCard witness={wB ?? { condition: "B", status: "pending" }} />
              <WitnessCard witness={wC ?? { condition: "C", status: "pending" }} />
            </div>
          </section>
        )}

        {/* --- the delta --- */}
        {tribunal?.delta && tribunal.status === "done" && wC?.status === "ok" && (
          <DeltaPanel delta={tribunal.delta} witnessC={wC} />
        )}

        {tribunal?.status === "failed" && (
          <p className="mt-8 border border-signal-red/40 bg-signal-red/10 p-4 font-mono text-xs text-signal-red">
            the tribunal collapsed: {tribunal.error ?? "all three witnesses failed"}
          </p>
        )}

        <footer className="mt-12 flex flex-wrap gap-x-8 gap-y-2 border-t border-hairline pt-6 font-mono text-[11px]">
          <Link href="/eval" className="text-vellum-dim underline hover:text-amber">
            the statistical version of this claim → /eval
          </Link>
          <Link href="/analyze" className="text-vellum-dim underline hover:text-amber">
            single-verdict analysis room →
          </Link>
          <Link href="/" className="text-vellum-dim underline hover:text-amber">
            back to the briefing
          </Link>
        </footer>
      </div>
    </main>
  );
}
