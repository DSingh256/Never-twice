import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { StepStream } from "@/components/AnalysisRoom";
import { ArchivePanel, ConfidenceBar, EmptyState, LevelStamp } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function AnalysisDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const num = Number(id);
  if (!Number.isFinite(num)) notFound();

  const a = await api.analysis(num);
  if (!a) notFound();

  const v = a.verdict ?? null;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Archived case</p>
        <h1 className="mt-2 font-display text-3xl font-bold">
          Case #{a.id} — {a.pr_title ?? a.service ?? "untitled change"}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <LevelStamp
            level={v?.level ?? (a.status === "failed" ? "failed" : "none")}
          />
          <ConfidenceBar value={a.confidence} />
          <span className="evidence-label">status {a.status}</span>
          <span className="evidence-label">evidence {a.evidence_count ?? 0}</span>
        </div>
      </header>

      {a.status === "failed" ? (
        <div className="mt-6">
          <EmptyState>
            This analysis failed before a verdict was reached — the archive
            records failures too, it does not invent one.
          </EmptyState>
        </div>
      ) : null}

      {v?.rationale ? (
        <section className="mt-6">
          <ArchivePanel label="Verdict rationale">
            <p className="font-display text-sm leading-relaxed">{v.rationale}</p>
          </ArchivePanel>
        </section>
      ) : null}

      <section className="mt-6">
        <ArchivePanel label="How this verdict was reached (replay)">
          <StepStream analysisId={a.id} done={a.status !== "running"} />
        </ArchivePanel>
      </section>

      {v?.matched_incidents && v.matched_incidents.length > 0 ? (
        <section className="mt-6">
          <h2 className="font-display text-xl font-semibold">
            Memories the verdict stood on
          </h2>
          <div className="mt-3 space-y-3">
            {v.matched_incidents.map((m, i) => (
              <ArchivePanel key={i} label={`memory ${i + 1}`}>
                {m.title ? (
                  <p className="font-display text-sm font-semibold">{m.title}</p>
                ) : null}
                {m.why_similar ? (
                  <p className="mt-1 text-sm">{m.why_similar}</p>
                ) : null}
                {m.what_failed_before ? (
                  <p className="mt-1 text-sm text-ink-soft">
                    <span className="evidence-label">what failed before </span>
                    {m.what_failed_before}
                  </p>
                ) : null}
                {m.what_worked ? (
                  <p className="mt-1 text-sm text-ink-soft">
                    <span className="evidence-label">what worked </span>
                    {m.what_worked}
                  </p>
                ) : null}
              </ArchivePanel>
            ))}
          </div>
        </section>
      ) : null}

      {v?.suggested_checks && v.suggested_checks.length > 0 ? (
        <section className="mt-6">
          <ArchivePanel label="Checks before merge">
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {v.suggested_checks.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </ArchivePanel>
        </section>
      ) : null}

      {v?.learned_from_feedback && v.learned_from_feedback.length > 0 ? (
        <section className="mt-6">
          <ArchivePanel label="Learned from feedback">
            <ul className="space-y-1 text-sm">
              {v.learned_from_feedback.map((f, i) => (
                <li key={i}>“{f.note ?? "(no note)"}”</li>
              ))}
            </ul>
          </ArchivePanel>
        </section>
      ) : null}

      <section className="mt-6">
        <details>
          <summary className="cursor-pointer font-mono text-xs uppercase tracking-widest text-ink-soft">
            the diff under examination
          </summary>
          <pre className="mt-2 overflow-x-auto border border-line bg-paper-raised p-3 font-mono text-xs">
            {a.diff ?? "(diff not archived)"}
          </pre>
        </details>
      </section>

      <p className="mt-8 font-mono text-xs">
        <Link href="/analyze" className="underline">
          ← back to the Analysis Room
        </Link>
      </p>
    </main>
  );
}
