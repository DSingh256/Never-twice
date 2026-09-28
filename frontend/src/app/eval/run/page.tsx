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
  const run = await api.evalRun(id);
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

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Evaluation run</p>
        <h1 className="mt-2 font-display text-3xl font-bold">
          Run {run.id ?? id}
        </h1>
      </header>

      {run.summary ? (
        <section className="mt-6">
          <ArchivePanel label="Summary">
            <pre className="overflow-x-auto font-mono text-xs">
              {JSON.stringify(run.summary, null, 2)}
            </pre>
          </ArchivePanel>
        </section>
      ) : null}

      <section className="mt-6">
        <h2 className="font-display text-xl font-semibold">Items</h2>
        {run.items && run.items.length > 0 ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-ink text-left">
                  <th className="py-2 pr-4">incident</th>
                  <th className="py-2 pr-4">condition</th>
                  <th className="py-2 pr-4">verdict</th>
                  <th className="py-2 pr-4">confidence</th>
                  <th className="py-2">correct</th>
                </tr>
              </thead>
              <tbody>
                {run.items.map((it, i) => (
                  <tr key={it.id ?? i} className="border-b border-line">
                    <td className="py-1.5 pr-4">{it.incident_id}</td>
                    <td className="py-1.5 pr-4">{it.condition}</td>
                    <td className="py-1.5 pr-4">{it.level ?? "—"}</td>
                    <td className="py-1.5 pr-4">
                      {it.confidence != null ? it.confidence.toFixed(3) : "—"}
                    </td>                    <td className="py-1.5">
                      {it.correct == null ? "—" : it.correct ? "yes" : "no"}
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
