import { api } from "@/lib/api";
import { AnalysisRoom } from "@/components/AnalysisRoom";
import { EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function AnalyzeIndex() {
  const { analyses } = await api.analyses(50);
  const latestDone = analyses.find((a) => a.status === "done") ?? null;
  const detail = latestDone ? await api.analysis(latestDone.id) : null;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · live analysis</p>
        <h1 className="mt-2 font-display text-3xl font-bold">Analysis Room</h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          Paste a diff. The archive recalls the incidents it resembles and a
          verdict is recorded — with every step shown, never hidden.
        </p>
      </header>
      <div className="mt-8">
        <AnalysisRoom initial={detail} />
      </div>
    </main>
  );
}
