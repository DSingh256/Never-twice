import { notFound } from "next/navigation";
import { api, type EvalRunDetail } from "@/lib/api";
import { ArchivePanel, EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function EvalRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const run: EvalRunDetail | null = await api.evalRun(id);
  if (!run) notFound();

  if (run.error) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-10">
        <EmptyState>
          Evaluation run {id} failed: {run.error}
        </EmptyState>
      </main>
    );
  }

  const summary = (run.summary ?? {}) as {
    conditions?: Record<
      string,
      { scored?: number; errors?: number; accuracy?: number }
    >;
    benchmark_cases?: number;
  };
  const snapshot = run.config_snapshot
    ? JSON.stringify(run.config_snapshot, null, 2)
    : null;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Evaluation run</p>
        <h1 className="mt-2 font-display text-3xl font-bold">
          Run {run.id ?? id}
        </h1>
        <p className="evidence-label mt-2">
          {run.created_at ? new Date(run.created_at).toLocaleString() : ""} ·
          status {run.status} · {summary.benchmark_cases ?? "?"} benchmark cases
        </p>
      </header>

      {snapshot ? (
        <section className="mt-6">
          <ArchivePanel label="Exact config used (snapshotted at run time)">
            <pre className="overflow-x-auto font-mono text-xs">{snapshot}</pre>
          </ArchivePanel>
        </section>
      ) : null}

      <section className="mt-6">
        <h2 className="font-display text-xl font-semibold">Per-item results</h2>
        {run.items && run.items.length > 0 ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-ink text-left">
                  <th className="py-2 pr-4">case</th>
                  <th className="py-2 pr-4">cond</th>
                  <th className="py-2 pr-4">expected</th>
                  <th className="py-2 pr-4">predicted</th>
                  <th className="py-2 pr-4">confidence</th>
                  <th className="py-2">correct</th>
                </tr>
              </thead>
              <tbody>
                {run.items.map((it, i) => (
                  <tr key={it.id ?? i} className="border-b border-line">
                    <td className="py-1.5 pr-4">{it.case_id}</td>
                    <td className="py-1.5 pr-4">{it.condition}</td>
                    <td className="py-1.5 pr-4">
                      {it.expected_label === 1 ? "risky" : "safe"}
                    </td>
                    <td className="py-1.5 pr-4">{it.predicted_level}</td>
                    <td className="py-1.5 pr-4">
                      {it.confidence != null ? it.confidence.toFixed(3) : "—"}
                    </td>
                    <td
                      className={`py-1.5 ${
                        it.correct == null
                          ? "text-ink-soft"
                          : it.correct
                            ? "text-ok"
                            : "text-danger"
                      }`}
                    >
                      {it.error
                        ? `error: ${it.error.slice(0, 60)}`
                        : it.correct == null
                          ? "—"
                          : it.correct
                            ? "yes"
                            : "NO"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm text-ink-soft">no items recorded</p>
        )}
      </section>
    </main>
  );
}
