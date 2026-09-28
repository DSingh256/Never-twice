import Link from "next/link";
import { api } from "@/lib/api";
import {
  ArchivePanel,
  ConfidenceBar,
  EmptyState,
  LevelStamp,
} from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Briefing() {
  const health = await api.health();
  const { analyses } = await api.analyses(30);
  const { feedback } = await api.feedback(20);

  const recent = analyses.slice(0, 8);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · operational memory</p>
        <h1 className="mt-2 font-display text-4xl font-bold tracking-tight">
          Never Twice
        </h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          Every deployment is cross-examined against everything this
          organization has already lived through.
        </p>
      </header>

      <section className="mt-6 flex flex-wrap gap-x-8 gap-y-2 font-mono text-xs">
        <span>
          <span className="evidence-label">hindsight </span>
          {health?.hindsight?.ok ? (
            <span className="text-ok">online ({health.hindsight.bank_id})</span>
          ) : (
            <span className="text-danger">offline</span>
          )}
        </span>
        <span>
          <span className="evidence-label">verdict llm </span>
          {health?.llm?.ok ? (
            <span className="text-ok">{health.llm.model}</span>
          ) : (
            <span className="text-danger">offline</span>
          )}
        </span>
        <span>
          <span className="evidence-label">archive db </span>
          {health?.database?.ok ? (
            <span className="text-ok">ok</span>
          ) : (
            <span className="text-danger">down</span>
          )}
        </span>
        <span>
          <span className="evidence-label">analyses </span>
          {analyses.length}
        </span>
        <span>
          <span className="evidence-label">feedback </span>
          {feedback.length}
        </span>
      </section>

      <section className="mt-10">
        <h2 className="font-display text-2xl font-semibold">
          The wall of prior verdicts
        </h2>
        <p className="mt-1 text-sm text-ink-soft">
          Each card is a real verdict with its evidence count and computed
          confidence — no sample data.
        </p>
        {recent.length === 0 ? (
          <div className="mt-4">
            <EmptyState>
              The archive is empty. Ingest incident reports and run an
              analysis in the{" "}
              <Link href="/analyze" className="underline">
                Analysis Room
              </Link>
              .
            </EmptyState>
          </div>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {recent.map((a) => (
              <Link
                key={a.id}
                href={`/analyze/${a.id}`}
                className="border border-line bg-paper-raised p-4 transition-colors hover:border-accent"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-ink-soft">
                    case #{a.id}
                  </span>
                  <LevelStamp level={a.level ?? (a.status === "failed" ? "failed" : "none")} />
                </div>
                <p className="mt-2 truncate font-display text-base">
                  {a.pr_title ?? a.service ?? `Analysis ${a.id}`}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <ConfidenceBar value={a.confidence} />
                  <span className="evidence-label">
                    ev {a.evidence_count ?? 0}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10 grid gap-4 md:grid-cols-2">
        <ArchivePanel label="Learning Lab · feedback loop">
          {feedback.length === 0 ? (
            <p className="text-sm text-ink-soft">
              No engineer feedback recorded yet. The first confirmation or
              rejection will be retained to memory and start shifting future
              verdicts.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {feedback.slice(0, 5).map((f) => (
                <li key={f.id} className="flex gap-2">
                  <span
                    className={`stamp ${
                      f.verdict === "good_catch"
                        ? "text-ok border-ok"
                        : "text-danger border-danger"
                    }`}
                  >
                    {f.verdict}
                  </span>
                  <span className="text-ink-soft">
                    on case #{f.analysis_id}
                    {f.note ? ` — “${f.note.slice(0, 60)}”` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3">
            <Link href="/learning-lab" className="font-mono text-xs underline">
              open the Learning Lab →
            </Link>
          </p>
        </ArchivePanel>

        <ArchivePanel label="Archive index">
          <ul className="space-y-2 font-mono text-xs">
            <li>
              <Link href="/tribunal" className="underline">
                Tribunal
              </Link>{" "}
              — one diff, judged with and without memory, live
            </li>
            <li>
              <Link href="/atlas" className="underline">
                Atlas
              </Link>{" "}
              — the memory bank, mapped
            </li>
            <li>
              <Link href="/analyze" className="underline">
                Analysis Room
              </Link>{" "}
              — submit a diff, watch the verdict
            </li>
            <li>
              <Link href="/learning-lab" className="underline">
                Learning Lab
              </Link>{" "}
              — where verdicts learn from engineers
            </li>
            <li>
              <Link href="/eval" className="underline">
                Evaluation
              </Link>{" "}
              — A/B/C ablation over held-out incidents
            </li>
          </ul>
        </ArchivePanel>
      </section>
    </main>
  );
}
