import Link from "next/link";
import { api, type EvalRunSummary } from "@/lib/api";
import { ArchivePanel, EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

type CondMetrics = {
  scored?: number;
  errors?: number;
  accuracy?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  false_positive_rate?: number;
  mean_confidence?: number | null;
  mean_latency_ms?: number | null;
};

const LABELS: Record<string, string> = {
  A: "A · LLM only",
  B: "B · LLM + recall",
  C: "C · LLM + recall + reflect + feedback",
};

function Pct({ v }: { v?: number | null }) {
  return <>{v == null ? "—" : `${Math.round(v * 100)}%`}</>;
}

export default async function EvalPage() {
  const data: EvalRunSummary = await api.evalRuns();
  const latest = data.runs[0];

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
          {data.runs.slice(0, 3).map((run) => {
            const conds = (run.summary?.conditions ?? {}) as Record<
              string,
              CondMetrics
            >;
            return (
              <ArchivePanel
                key={run.id}
                label={`run ${run.id} · ${run.created_at ? new Date(run.created_at).toLocaleString() : ""} · label ${run.label ?? "—"}`}
              >
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse font-mono text-xs">
                    <thead>
                      <tr className="border-b border-ink text-left">
                        <th className="py-1.5 pr-3">condition</th>
                        <th className="py-1.5 pr-3">scored</th>
                        <th className="py-1.5 pr-3">errors</th>
                        <th className="py-1.5 pr-3">acc</th>
                        <th className="py-1.5 pr-3">prec</th>
                        <th className="py-1.5 pr-3">rec</th>
                        <th className="py-1.5 pr-3">f1</th>
                        <th className="py-1.5 pr-3">fpr</th>
                        <th className="py-1.5">mean conf</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(["A", "B", "C"] as const).map((c) => {
                        const m = conds[c] ?? {};
                        return (
                          <tr key={c} className="border-b border-line">
                            <td className="py-1.5 pr-3">{LABELS[c]}</td>
                            <td className="py-1.5 pr-3">{m.scored ?? 0}</td>
                            <td className="py-1.5 pr-3">{m.errors ?? 0}</td>
                            <td className="py-1.5 pr-3 font-semibold">
                              <Pct v={m.accuracy} />
                            </td>
                            <td className="py-1.5 pr-3">
                              <Pct v={m.precision} />
                            </td>
                            <td className="py-1.5 pr-3">
                              <Pct v={m.recall} />
                            </td>
                            <td className="py-1.5 pr-3">
                              <Pct v={m.f1} />
                            </td>
                            <td className="py-1.5 pr-3">
                              <Pct v={m.false_positive_rate} />
                            </td>
                            <td className="py-1.5">
                              {m.mean_confidence == null
                                ? "—"
                                : m.mean_confidence.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 font-mono text-xs">
                  <Link href={`/eval/${run.id}`} className="underline">
                    per-item breakdown →
                  </Link>
                </p>
              </ArchivePanel>
            );
          })}
          <p className="evidence-label">
            every number computed from eval_items rows · run config snapshotted
            at execution
          </p>
        </div>
      )}
    </main>
  );
}
