"use client";

/* THE ANALYSIS ROOM — a scroll-driven investigation.
 *
 * One continuous cinematic timeline: HERO → ARCHIVE → CHANGE → RECALL →
 * CASE FILES → REFLECT → FEEDBACK → VERDICT. A single scalar `progress`
 * (0..1 of the whole journey) drives the 3D scene and every HTML layer.
 * Each chapter is a `sticky` stage inside its own scroll segment, so
 * scrolling backward scrubs everything in reverse naturally.
 *
 * DATA RULE: every incident, similarity, diff, confidence and feedback item
 * comes from the running API (/api/analyses, /api/analyses/{id},
 * /api/memory/search, /api/feedback). Nothing here is authored sample data —
 * when the archive is empty we say so in an archival empty state.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import { api, API_BASE } from "@/lib/api";
import type { AnalysisDetail, AnalysisRow, FeedbackRow, MemoryHitDto, Verdict } from "@/lib/api";
import type { MemoryNode, SceneLink } from "./scene/ArchiveScene";

const ArchiveScene = dynamic(() => import("./scene/ArchiveScene"), {
  ssr: false,
  loading: () => null,
});

/* ------------------------------------------------------------------ */
/* timeline layout (fractions of total scroll)                        */
/* ------------------------------------------------------------------ */
const SEGMENTS = {
  hero: [0.0, 0.12],
  archive: [0.12, 0.24],
  change: [0.24, 0.4],
  recall: [0.4, 0.56],
  reflect: [0.56, 0.72],
  feedback: [0.72, 0.86],
  verdict: [0.86, 1.0],
} as const;

/** 1 inside [a,b] with soft edges, 0 outside — pure scrub, no toggles. */
function band(p: number, a: number, b: number, feather = 0.03): number {
  const rise = smooth(p, a - feather, a + feather);
  const fall = 1 - smooth(p, b - feather, b + feather);
  return Math.min(rise, fall);
}
function smooth(x: number, a: number, b: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a || 1)));
  return t * t * (3 - 2 * t);
}
function segmentOpacity(p: number, seg: readonly [number, number] | readonly number[]) {
  return band(p, seg[0], seg[1], 0.045);
}

const CHAPTERS = [
  { id: "hero", label: "01 · BRIEFING", at: 0.0 },
  { id: "archive", label: "02 · THE ARCHIVE", at: 0.14 },
  { id: "change", label: "03 · THE CHANGE", at: 0.27 },
  { id: "recall", label: "04 · MEMORY RECALL", at: 0.44 },
  { id: "reflect", label: "05 · CASE FILES · REFLECTION", at: 0.6 },
  { id: "feedback", label: "06 · THE LOOP", at: 0.76 },
  { id: "verdict", label: "07 · VERDICT", at: 0.92 },
] as const;

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */
function parseMemoryNode(hit: MemoryHitDto, slot: number): MemoryNode {
  const incidentTag = (hit.tags ?? []).find((t) => t.startsWith("incident:"));
  const serviceTag = (hit.tags ?? []).find((t) => t.startsWith("service:"));
  const kindTag = (hit.tags ?? []).find((t) => t.startsWith("kind:"));
  return {
    id: hit.id,
    text: hit.text,
    score: hit.score,
    slot,
    tags: [incidentTag ?? "incident:—", serviceTag ?? "", kindTag ?? hit.fact_type ?? ""].filter(
      Boolean
    ),
  };
}

function parseLinkStrength(hit: MemoryHitDto): number {
  // hit.score is the real recall relevance (0..~1.1) — mapped to line strength.
  return Math.max(0.15, Math.min(1, hit.score / 0.9));
}

const LEVEL_STAMP: Record<string, { word: string; cls: string }> = {
  high: { word: "FLAGGED", cls: "text-signal-red" },
  medium: { word: "REVIEW REQUIRED", cls: "text-amber" },
  low: { word: "CLEARED · NOTED", cls: "text-sage" },
  none: { word: "CLEARED", cls: "text-vellum-dim" },
};

/* ------------------------------------------------------------------ */
/* HTML overlay pieces                                                */
/* ------------------------------------------------------------------ */
function SectionFrame({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`brackets case-file px-6 py-5 md:px-8 ${className}`}>{children}</div>;
}

function DiffPanel({ diff, verdict }: { diff: string; verdict?: Verdict | null }) {
  const lines = useMemo(() => diff.split("\n").slice(0, 44), [diff]);
  const hasMatches = (verdict?.matched_incidents?.length ?? 0) > 0;
  return (
    <pre className="max-h-[56vh] overflow-auto border border-hairline bg-night-2 p-4 font-mono text-[11px] leading-relaxed md:text-xs">
      {lines.map((l, i) => {
        const risky = hasMatches && /^[-+]/.test(l);
        const add = l.startsWith("+");
        const del = l.startsWith("-");
        return (
          <div
            key={i}
            className={
              risky
                ? `px-1 ${del ? "text-signal-red/90" : "bg-amber-soft text-vellum"}`
                : add
                  ? "px-1 text-amber"
                  : del
                    ? "px-1 text-signal-red/70"
                    : "px-1 text-vellum-faint"
            }
          >
            {l || " "}
          </div>
        );
      })}
    </pre>
  );
}

function CaseFile({
  hit,
  index,
  active,
  onActivate,
}: {
  hit: MemoryHitDto;
  index: number;
  active: boolean;
  onActivate: () => void;
}) {
  const incidentTag = (hit.tags ?? []).find((t) => t.startsWith("incident:")) ?? "incident:—";
  const serviceTag = (hit.tags ?? []).find((t) => t.startsWith("service:")) ?? "";
  const kindTag = (hit.tags ?? []).find((t) => t.startsWith("kind:")) ?? hit.fact_type ?? "";
  return (
    <button
      onClick={onActivate}
      className={`brackets pointer-events-auto w-full cursor-pointer border px-4 py-3 text-left transition-colors ${
        active
          ? "border-amber-line bg-amber-soft/60"
          : "border-hairline bg-night-2/70 hover:border-vellum-faint/40"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="plate">{incidentTag}</span>
        <span className="tag-mono text-[10px] text-amber">SIM {hit.score.toFixed(3)}</span>
      </div>
      <p
        className={`mt-1 line-clamp-2 font-mono text-[11px] leading-snug ${
          active ? "text-vellum" : "text-vellum-dim"
        }`}
      >
        {hit.text}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-x-4">
        {serviceTag ? <span className="plate">{serviceTag}</span> : null}
        {kindTag ? <span className="plate">{kindTag}</span> : null}
        <span className="plate">FILE {String(index + 1).padStart(3, "0")}</span>
      </div>
    </button>
  );
}

/* one pinned chapter: sticky stage inside a scroll segment */
function Chapter({
  opacity,
  children,
}: {
  opacity: number;
  children: React.ReactNode;
}) {
  return (
    <div className="h-screen sticky top-0">
      <div
        className="pointer-events-none absolute inset-0"
        style={{ opacity }}
        aria-hidden={opacity < 0.02}
      >
        {children}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* The room                                                           */
/* ------------------------------------------------------------------ */
export default function AnalysisRoom({ initial }: { initial: AnalysisDetail | null }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const progressRef = useRef(0);
  const lenisRef = useRef<import("lenis").default | null>(null);
  const [progress, setProgress] = useState(0);
  const [analyses, setAnalyses] = useState<AnalysisRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(initial?.id ?? null);
  const [detail, setDetail] = useState<AnalysisDetail | null>(initial);
  const [feedback, setFeedback] = useState<FeedbackRow[]>([]);
  const [hits, setHits] = useState<MemoryHitDto[]>([]);
  const [activeNode, setActiveNode] = useState(0);
  const [loadingMemory, setLoadingMemory] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [diffText, setDiffText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reducedMotion = useRef(false);

  /* ---------------- data: real only ------------------------------- */
  const loadAnalyses = useCallback(async () => {
    const { analyses } = await api.analyses(60);
    setAnalyses(analyses);
    setSelectedId((cur) => {
      if (cur && analyses.some((a) => a.id === cur)) return cur;
      return analyses.find((a) => a.status === "done")?.id ?? analyses[0]?.id ?? null;
    });
  }, []);

  useEffect(() => {
    void loadAnalyses();
    api.feedback(40).then(({ feedback }) => setFeedback(feedback)).catch(() => setFeedback([]));
  }, [loadAnalyses]);

  useEffect(() => {
    let cancelled = false;
    if (selectedId == null) {
      setDetail(null);
      setHits([]);
      return;
    }
    void (async () => {
      const d = await api.analysis(selectedId);
      if (cancelled) return;
      setDetail(d);
      setActiveNode(0);
      if (d?.change_facts) {
        setLoadingMemory(true);
        const facts = d.change_facts as { summary?: string };
        const query = facts.summary || d.pr_title || "";
        if (query.trim()) {
          const { memories } = await api.memorySearch(query, 22);
          if (!cancelled) setHits(memories);
        } else if (!cancelled) {
          setHits([]);
        }
        if (!cancelled) setLoadingMemory(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const verdict = detail?.verdict ?? null;
  const linkedHits = useMemo(
    () =>
      (verdict?.supporting_memory_ids ?? [])
        .map((id) => hits.find((h) => h.id === id))
        .filter((h): h is MemoryHitDto => Boolean(h)),
    [hits, verdict]
  );

  const nodes = useMemo(() => hits.map((h, i) => parseMemoryNode(h, i)), [hits]);
  const links = useMemo<SceneLink[]>(
    () =>
      (linkedHits.length ? linkedHits : hits.slice(0, 3))
        .map((h) => ({
          nodeSlot: hits.findIndex((x) => x.id === h.id),
          strength: parseLinkStrength(h),
        }))
        .filter((l) => l.nodeSlot >= 0),
    [hits, linkedHits]
  );

  /* ---------------- scroll engine ---------------------------------- */
  useEffect(() => {
    reducedMotion.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const el = wrapRef.current;
    if (!el) return;

    let raf = 0;
    let running = true;
    let max = 1;

    const measure = () => {
      max = Math.max(1, el.scrollHeight - window.innerHeight);
    };

    const applyProgress = () => {
      const p = Math.min(1, Math.max(0, window.scrollY / max));
      progressRef.current = p;
      (window as unknown as { __ntProgress?: number }).__ntProgress = p;
      setProgress(p);
    };

    const onScroll = () => {
      if (raf || !running) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        applyProgress();
      });
    };

    // A settled rAF poll: covers Lenis-driven scrolls that may not emit a
    // window scroll event on some setups, and resize/re-layout changes.
    const poll = () => {
      if (!running) return;
      applyProgress();
      requestAnimationFrame(poll);
    };

    if (!reducedMotion.current) {
      void (async () => {
        const { default: Lenis } = await import("lenis");
        const lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 0.9 });
        lenisRef.current = lenis;
        lenis.on("scroll", onScroll);
        const loop = (time: number) => {
          lenis.raf(time);
          if (running) requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
      })();
    }

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", () => {
      measure();
      onScroll();
    });
    onScroll();
    requestAnimationFrame(poll);
    return () => {
      running = false;
      window.removeEventListener("scroll", onScroll);
      lenisRef.current?.destroy();
      lenisRef.current = null;
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const quality = useMemo<"high" | "medium" | "low">(() => {
    if (typeof window === "undefined") return "high";
    const w = window.innerWidth;
    if (w < 768) return "low";
    if (w < 1200) return "medium";
    return "high";
  }, []);

  const jumpTo = useCallback((at: number) => {
    const el = wrapRef.current;
    if (!el) return;
    const max = el.scrollHeight - window.innerHeight;
    const target = at * max;
    if (lenisRef.current) lenisRef.current.scrollTo(target, { duration: 1.4 });
    else window.scrollTo({ top: target, behavior: reducedMotion.current ? "auto" : "smooth" });
  }, []);

  /* ---------------- submit flow (existing API, unchanged) ---------- */
  async function submit() {
    if (!diffText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ diff: diffText, pr_title: "Analysis Room submission" }),
      });
      if (!res.ok) throw new Error(`analyze failed (${res.status})`);
      const data = (await res.json()) as { analysis_id: number };
      setSubmitOpen(false);
      setDiffText("");
      await loadAnalyses();
      setSelectedId(data.analysis_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  /* ---------------- scrubbed opacities ----------------------------- */
  const o = {
    hero: segmentOpacity(progress, SEGMENTS.hero),
    archive: segmentOpacity(progress, SEGMENTS.archive),
    change: segmentOpacity(progress, SEGMENTS.change),
    recall: segmentOpacity(progress, SEGMENTS.recall),
    reflect: segmentOpacity(progress, SEGMENTS.reflect),
    feedback: segmentOpacity(progress, SEGMENTS.feedback),
    verdict: segmentOpacity(progress, SEGMENTS.verdict),
  };
  const currentChapter = CHAPTERS.slice().reverse().find((c) => progress >= c.at) ?? CHAPTERS[0];

  const feedbackPairs = useMemo(
    () =>
      feedback.slice(0, 6).map((f) => ({
        feedback: f,
        graded: analyses.find((a) => a.id === f.analysis_id) ?? null,
      })),
    [feedback, analyses]
  );

  const confidenceBefore = feedback.length > 0 ? (detail?.confidence ?? null) : null;

  return (
    <div ref={wrapRef} className="archive-night relative">
      {/* fixed WebGL stage */}
      <div className="fixed inset-0 z-0">
        <ArchiveScene progressRef={progressRef} nodes={nodes} links={links} quality={quality} />
        <div className="archive-fx" />
      </div>

      {/* right progress rail */}
      <div className="progress-rail" aria-hidden>
        {CHAPTERS.map((c) => (
          <button
            key={c.id}
            onClick={() => jumpTo(c.at)}
            title={c.label}
            className={`absolute -left-[7px] h-3 w-3 cursor-pointer rounded-full border ${
              currentChapter.id === c.id
                ? "border-amber bg-amber"
                : "border-vellum-faint/50 bg-transparent"
            }`}
            style={{ top: `${c.at * 100}%` }}
          />
        ))}
      </div>

      {/* top chrome */}
      <div className="pointer-events-none fixed left-0 right-0 top-0 z-30 flex items-center justify-between px-5 py-4 md:px-8">
        <span className="plate pointer-events-auto">BLACK BOX ARCHIVE · ANALYSIS ROOM</span>
        <span className="plate pointer-events-auto">
          CASE {selectedId ? `#${String(selectedId).padStart(4, "0")}` : "——"} · {currentChapter.label}
        </span>
      </div>

      {/* the journey: one tall scroll track, each chapter pinned */}
      <div className="relative z-10">
        {/* ---- 01 HERO ---- */}
        <div style={{ height: "150vh" }}>
          <Chapter opacity={o.hero}>
            <div className="flex h-screen flex-col items-center justify-center px-6 text-center">
              <motion.p
                className="plate"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2, duration: 1.2 }}
              >
                ORGANIZATIONAL MEMORY · DEPLOYMENT GATE
              </motion.p>
              <motion.h1
                className="display-serif mt-4 text-[clamp(3rem,10vw,8.5rem)] leading-none text-vellum"
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35, duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
              >
                NEVER TWICE
              </motion.h1>
              <motion.p
                className="mt-5 max-w-xl font-grotesk text-sm text-vellum-dim"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.7, duration: 1.2 }}
              >
                Every change is cross-examined against everything this organization
                has already lived through. Scroll to enter the archive.
              </motion.p>
              <div className="hazard-strip mt-10 w-40" />
            </div>
          </Chapter>
        </div>

        {/* ---- 02 ARCHIVE ---- */}
        <div style={{ height: "130vh" }}>
          <Chapter opacity={o.archive}>
            <div className="flex h-screen items-center justify-center px-6">
              <div className="text-center">
                <p className="plate text-amber">ENTERING MEMORY ARCHIVE</p>
                <p className="display-serif mt-3 text-3xl text-vellum md:text-5xl">
                  {loadingMemory ? "ARCHIVE SEARCH" : `${nodes.length} MEMORIES RETRIEVED`}
                </p>
                <p className="mt-3 font-mono text-xs text-vellum-faint">
                  {nodes.length > 0
                    ? "retained incidents · failed fixes · engineer feedback"
                    : "NO MEMORY RECORDED — run ingestion to populate the archive"}
                </p>
              </div>
            </div>
          </Chapter>
        </div>

        {/* ---- 03 THE CHANGE ---- */}
        <div style={{ height: "170vh" }}>
          <Chapter opacity={o.change}>
            <div className="mx-auto grid h-screen max-w-6xl grid-cols-1 items-center gap-8 px-5 pt-16 md:grid-cols-[0.9fr_1.1fr] md:px-10">
              <div className="pointer-events-auto">
                <SectionFrame>
                  <p className="plate text-amber">CHANGE DETECTED</p>
                  <h2 className="display-serif mt-2 text-2xl text-vellum md:text-3xl">
                    {detail?.pr_title ?? "Untitled change"}
                  </h2>
                  <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-[11px]">
                    <span className="plate">SERVICE</span>
                    <span className="text-vellum">{detail?.service ?? "—"}</span>
                    <span className="plate">CATEGORY</span>
                    <span className="text-vellum">
                      {(detail?.change_facts as { change_category?: string } | null)?.change_category ?? "—"}
                    </span>
                    <span className="plate">STATUS</span>
                    <span className="text-vellum">{detail?.status ?? "—"}</span>
                    <span className="plate">EVIDENCE</span>
                    <span className="text-amber">{detail?.evidence_count ?? 0} memories</span>
                  </div>
                  {detail?.change_facts ? (
                    <p className="mt-4 border-t border-hairline pt-3 font-mono text-[11px] leading-relaxed text-vellum-dim">
                      {(detail.change_facts as { summary?: string }).summary}
                    </p>
                  ) : null}
                </SectionFrame>

                {/* case selector (ascending so early cases stay reachable) */}
                <div className="mt-4 flex items-center gap-2 overflow-x-auto pb-1">
                  {analyses.slice(0, 24).map((a) => a).sort((x, y) => x.id - y.id).map((a) => (
                    <button
                      key={a.id}
                      onClick={() => setSelectedId(a.id)}
                      className={`stamp pointer-events-auto shrink-0 cursor-pointer ${
                        a.id === selectedId ? "border-amber text-amber" : "border-hairline text-vellum-faint"
                      }`}
                    >
                      #{a.id}
                    </button>
                  ))}
                  <button
                    onClick={() => setSubmitOpen(true)}
                    className="stamp pointer-events-auto shrink-0 cursor-pointer border-amber text-amber"
                  >
                    + NEW
                  </button>
                </div>
              </div>
              <div className="pointer-events-auto">
                {detail?.diff ? (
                  <DiffPanel diff={detail.diff} verdict={verdict} />
                ) : (
                  <div className="border border-dashed border-hairline p-10 text-center">
                    <p className="display-serif text-xl text-vellum-dim">NO DIFF ON RECORD</p>
                    <p className="plate mt-2">this case has no stored diff</p>
                  </div>
                )}
              </div>
            </div>
          </Chapter>
        </div>

        {/* ---- 04 MEMORY RECALL ---- */}
        <div style={{ height: "150vh" }}>
          <Chapter opacity={o.recall}>
            <div className="mx-auto flex h-screen max-w-3xl flex-col items-center justify-center px-5 text-center">
              <p className="plate text-amber">MEMORY RECALL</p>
              <p className="display-serif mt-3 text-2xl text-vellum md:text-4xl">
                {nodes.length > 0
                  ? "THIS CHANGE RESEMBLES THINGS THAT FAILED BEFORE"
                  : "NOTHING RECALLED"}
              </p>
              <p className="mt-3 font-mono text-xs text-vellum-faint">
                {nodes.length > 0
                  ? `${nodes.length} nodes retrieved · ${links.length} connected to this change`
                  : "run an analysis whose diff touches recorded memory"}
              </p>
              {links.length > 0 ? (
                <div className="mt-6 space-y-1 font-mono text-[11px] text-vellum-dim">
                  {links.slice(0, 3).map((l) => (
                    <p key={l.nodeSlot}>
                      <span className="text-amber">──</span> {hits[l.nodeSlot]?.text.slice(0, 72)}…
                      <span className="text-amber"> ({hits[l.nodeSlot]?.score.toFixed(3)})</span>
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
          </Chapter>
        </div>

        {/* ---- 05 CASE FILES / REFLECTION ---- */}
        <div style={{ height: "190vh" }}>
          <Chapter opacity={o.reflect}>
            <div className="mx-auto grid h-screen max-w-6xl grid-cols-1 items-center gap-6 px-5 pt-16 md:grid-cols-[1fr_1fr] md:px-10">
              <div className="pointer-events-auto max-h-[62vh] space-y-2 overflow-y-auto pr-1">
                {nodes.length === 0 ? (
                  <div className="border border-dashed border-hairline p-8 text-center">
                    <p className="display-serif text-xl text-vellum-dim">NO MEMORY RECORDED</p>
                    <p className="plate mt-2">ingest postmortems to populate the archive</p>
                  </div>
                ) : (
                  hits.slice(0, 10).map((h, i) => (
                    <CaseFile
                      key={h.id}
                      hit={h}
                      index={i}
                      active={i === activeNode}
                      onActivate={() => setActiveNode(i)}
                    />
                  ))
                )}
              </div>
              <div className="pointer-events-auto">
                {hits[activeNode] ? (
                  <SectionFrame>
                    <p className="plate text-amber">CASE FILE · OPENED</p>
                    <div className="mt-3 space-y-2 font-mono text-[11px]">
                      <div className="flex justify-between gap-4">
                        <span className="plate">INCIDENT ID</span>
                        <span className="text-vellum">
                          {(hits[activeNode].tags ?? []).find((t) => t.startsWith("incident:")) ?? "—"}
                        </span>
                      </div>
                      <div className="flex justify-between gap-4">
                        <span className="plate">SOURCE</span>
                        <span className="text-vellum">
                          {(hits[activeNode].tags ?? []).find((t) => t.startsWith("source:")) ?? "bank memory"}
                        </span>
                      </div>
                      <div className="flex justify-between gap-4">
                        <span className="plate">SIMILARITY</span>
                        <span className="text-amber">{hits[activeNode].score.toFixed(3)}</span>
                      </div>
                    </div>
                    <p className="mt-3 border-t border-hairline pt-3 font-mono text-[11px] leading-relaxed text-vellum-dim">
                      {hits[activeNode].text}
                    </p>
                    <p className="plate mt-3">
                      WHAT FAILED · WHAT WAS TRIED · WHAT WORKED — AS RETAINED
                    </p>
                    {verdict?.rationale ? (
                      <p className="mt-3 border-t border-hairline pt-3 font-mono text-[11px] leading-relaxed text-amber">
                        REFLECTION: {verdict.rationale}
                      </p>
                    ) : null}
                  </SectionFrame>
                ) : null}
              </div>
            </div>
          </Chapter>
        </div>

        {/* ---- 06 THE LOOP ---- */}
        <div style={{ height: "150vh" }}>
          <Chapter opacity={o.feedback}>
            <div className="mx-auto h-screen max-w-4xl px-5 pt-24">
              <p className="plate text-amber">THE LOOP · ORGANIZATIONAL MEMORY CHANGES</p>
              <p className="display-serif mt-2 text-2xl text-vellum md:text-3xl">
                PAST VERDICT → ENGINEER FEEDBACK → MEMORY UPDATED → FUTURE VERDICT
              </p>
              {feedbackPairs.length === 0 ? (
                <div className="mt-8 border border-dashed border-hairline p-10 text-center">
                  <p className="display-serif text-xl text-vellum-dim">NO FEEDBACK YET</p>
                  <p className="plate mt-2">
                    the first engineer grade will be retained as memory and measurably
                    shift future verdicts
                  </p>
                </div>
              ) : (
                <div className="mt-6 space-y-2">
                  {feedbackPairs.map(({ feedback: f, graded }) => (
                    <div
                      key={f.id}
                      className="brackets case-file grid grid-cols-[auto_1fr] items-center gap-4 px-4 py-3"
                    >
                      <span
                        className={`stamp ${
                          f.verdict === "good_catch"
                            ? "border-sage text-sage"
                            : "border-signal-red text-signal-red"
                        }`}
                      >
                        {f.verdict}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-mono text-[11px] text-vellum">
                          case #{f.analysis_id}
                          {graded?.pr_title ? ` · ${graded.pr_title}` : ""}
                        </p>
                        <p className="truncate font-mono text-[10px] text-vellum-faint">
                          {f.reviewer ?? "anonymous"} · retained as kind:feedback memory
                        </p>
                      </div>
                    </div>
                  ))}
                  {confidenceBefore != null ? (
                    <p className="plate mt-3">
                      this case&apos;s confidence, computed with real feedback agreement:{" "}
                      <span className="text-amber">{confidenceBefore.toFixed(4)}</span>
                    </p>
                  ) : null}
                </div>
              )}
            </div>
          </Chapter>
        </div>

        {/* ---- 07 VERDICT ---- */}
        <div style={{ height: "160vh" }}>
          <Chapter opacity={o.verdict}>
            <div className="flex h-screen flex-col items-center justify-center px-6 text-center">
              {verdict ? (
                <>
                  <p className="plate">DEPLOYMENT VERDICT · CASE #{selectedId}</p>
                  <div
                    className={`stamp-lg mt-6 ${LEVEL_STAMP[verdict.level ?? "none"]?.cls ?? "text-vellum"}`}
                  >
                    {LEVEL_STAMP[verdict.level ?? "none"]?.word ?? "REVIEW"}
                  </div>
                  <p className="display-serif mt-6 text-3xl text-vellum md:text-4xl">
                    {(verdict.level ?? "none").toUpperCase()} RISK
                  </p>
                  {verdict.matched_incidents && verdict.matched_incidents.length > 0 ? (
                    <p className="mt-2 font-mono text-xs text-amber">
                      REPEAT OFFENDER PATTERN · {verdict.matched_incidents.length} historical
                      incident{verdict.matched_incidents.length > 1 ? "s" : ""} attached
                    </p>
                  ) : null}
                  <p className="mt-4 max-w-2xl font-mono text-[11px] leading-relaxed text-vellum-dim">
                    {verdict.rationale}
                  </p>
                  <div className="mt-6 flex gap-8 font-mono text-xs">
                    <span className="plate">
                      CONF{" "}
                      <span className="text-vellum">
                        {Math.round((detail?.confidence ?? 0) * 100)}%
                      </span>
                    </span>
                    <span className="plate">
                      EVIDENCE <span className="text-vellum">{detail?.evidence_count ?? 0}</span>
                    </span>
                    <span className="plate">
                      MEMORIES <span className="text-vellum">{nodes.length}</span>
                    </span>
                  </div>
                </>
              ) : detail?.status === "failed" ? (
                <div className="brackets case-file px-10 py-8">
                  <div className="stamp-lg text-signal-red">FAILED</div>
                  <p className="plate mt-4">this analysis failed — the archive records failures</p>
                  <p className="mt-2 font-mono text-[11px] text-vellum-faint">{detail.error}</p>
                </div>
              ) : (
                <div className="brackets case-file px-10 py-8">
                  <p className="display-serif text-2xl text-vellum-dim">NO VERDICT ON RECORD</p>
                  <p className="plate mt-2">submit a diff to open a case</p>
                </div>
              )}
            </div>
          </Chapter>
        </div>
      </div>

      {/* submit drawer */}
      {submitOpen ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-night/70 p-4 backdrop-blur-sm md:items-center">
          <div className="brackets case-file w-full max-w-2xl p-6">
            <p className="plate text-amber">SUBMIT A CHANGE FOR EXAMINATION</p>
            <textarea
              value={diffText}
              onChange={(e) => setDiffText(e.target.value)}
              rows={10}
              spellCheck={false}
              placeholder={"--- a/infra/main.tf\n+++ b/infra/main.tf\n@@\n-  min_healthy_hosts = 2\n+  min_healthy_hosts = 0"}
              className="mt-4 w-full border border-hairline bg-night-2 p-3 font-mono text-xs text-vellum focus:border-amber focus:outline-none"
            />
            {error ? <p className="mt-2 font-mono text-xs text-signal-red">{error}</p> : null}
            <div className="mt-4 flex justify-end gap-3">
              <button
                onClick={() => setSubmitOpen(false)}
                className="stamp cursor-pointer border-hairline text-vellum-dim"
              >
                CANCEL
              </button>
              <button
                onClick={submit}
                disabled={submitting || !diffText.trim()}
                className="stamp cursor-pointer border-amber bg-amber-soft text-amber disabled:opacity-40"
              >
                {submitting ? "EXAMINING…" : "RUN VERDICT"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
