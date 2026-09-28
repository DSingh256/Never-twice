import { api, type EvalRunSummary } from "@/lib/api";
import { ArchivePanel, EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function EvalPage() {
  const data: EvalRunSummary = await api.evalRuns();

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · ablation</p>
        <h1 className="mt-2 font-display text-3xl font-bold">Evaluation</h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          The same held-out incidents, judged three ways: with no memory, with
          memory, and with memory plus the feedback loop. Results are measured,
          never asserted.
        </p>
      </header>

      {!data || data.runs.length === 0 ? (
        <div className="mt-6">
          <EmptyState>
            No evaluation has been run yet. Execute the A/B/C ablation to fill
            this table with real numbers.
          </EmptyState>
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {data.runs.map((run) => (
            <ArchivePanel
              key={run.id}
              label={`run ${run.id} · ${run.created_at ? new Date(run.created_at).toLocaleString() : ""}`}
            >
              <pre className="overflow-x-auto font-mono text-xs">
                {JSON.stringify(run.summary ?? {}, null, 2)}
              </pre>
            </ArchivePanel>
          ))}
        </div>
      )}
    </main>
  );
}
