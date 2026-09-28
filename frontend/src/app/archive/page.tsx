import { api } from "@/lib/api";
import { ArchivePanel, EmptyState, LevelStamp, Tag } from "@/components/ui";
import type { Verdict } from "@/lib/api";

export const dynamic = "force-dynamic";

type FbDetail = {
  id: number;
  analysis_id: number;
  verdict: string;
  note: string | null;
  reviewer: string | null;
  created_at: string | null;
  tags?: string[];
};

export default async function Archive() {
  const [health, { analyses }, { feedback }] = await Promise.all([
    api.health(),
    api.analyses(100),
    api.feedback(100),
  ]);

  const failed = analyses.filter((a) => a.status === "failed");
  const done = analyses.filter((a) => a.status === "done");

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · full record</p>
        <h1 className="mt-2 font-display text-3xl font-bold">Archive</h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          The complete case file: every analysis, every failure, every grade.
          Failures are kept on purpose — a black box that hides crashes teaches
          nothing.
        </p>
      </header>

      <section className="mt-6">
        <h2 className="font-display text-xl font-semibold">
          Cases ({done.length} verdicts, {failed.length} failures)
        </h2>
        {analyses.length === 0 ? (
          <div className="mt-3">
            <EmptyState>No cases in the archive yet.</EmptyState>
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {analyses.map((a) => (
              <a
                key={a.id}
                href={`/analyze/${a.id}`}
                className="block border border-line bg-paper-raised px-4 py-3 hover:border-accent"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-ink-soft">
                    case #{a.id} · {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                  </span>
                  <LevelStamp
                    level={a.level ?? (a.status === "failed" ? "failed" : "none")}
                  />
                </div>
                <p className="mt-1 font-display text-sm">
                  {a.pr_title ?? a.service ?? `Analysis ${a.id}`}
                </p>
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="font-display text-xl font-semibold">Feedback ledger</h2>
        {feedback.length === 0 ? (
          <p className="mt-2 text-sm text-ink-soft">
            No feedback recorded yet.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {feedback.map((f) => (
              <div key={f.id} className="border border-line bg-paper-raised px-4 py-3">
                <span
                  className={`stamp ${
                    f.verdict === "good_catch"
                      ? "text-ok border-ok"
                      : "text-danger border-danger"
                  }`}
                >
                  {f.verdict}
                </span>
                <span className="ml-3 font-mono text-xs text-ink-soft">
                  case #{f.analysis_id} · {f.reviewer ?? "anonymous"}
                </span>
                {f.note ? (
                  <p className="mt-1 font-display text-sm">“{f.note}”</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-8">
        <ArchivePanel label="System status">
          <div className="flex flex-wrap gap-x-8 gap-y-1 font-mono text-xs">
            <span>
              hindsight {health?.hindsight?.ok ? "online" : "offline"} ·{" "}
              {health?.hindsight?.version ?? "?"}
            </span>
            <span>llm {health?.llm?.ok ? health.llm.model : "offline"}</span>
            <span>db {health?.database?.ok ? "ok" : "down"}</span>
          </div>
        </ArchivePanel>
      </section>
    </main>
  );
}
