import { api } from "@/lib/api";
import AnalysisRoom from "./AnalysisRoom";
import { EmptyState } from "@/components/ui";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function AnalyzeIndex() {
  const { analyses } = await api.analyses(60);
  const latestDone = analyses.find((a) => a.status === "done") ?? analyses[0] ?? null;
  const detail = latestDone ? await api.analysis(latestDone.id) : null;

  if (!detail) {
    return (
      <main className="archive-night relative min-h-screen">
        <div className="archive-fx" />
        <div className="relative z-10 mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 text-center">
          <p className="plate text-amber">BLACK BOX ARCHIVE · ANALYSIS ROOM</p>
          <h1 className="display-serif mt-4 text-4xl text-vellum">NO CASES ON RECORD</h1>
          <p className="mt-4 max-w-md font-grotesk text-sm text-vellum-dim">
            The archive is empty. Ingest incident reports to build organizational
            memory, then submit a diff to open the first case.
          </p>
          <div className="hazard-strip mt-8 w-40" />
          <Link href="/" className="plate mt-8 underline">
            ← return to the briefing
          </Link>
        </div>
      </main>
    );
  }

  return <AnalysisRoom initial={detail} />;
}
