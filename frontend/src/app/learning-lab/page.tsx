import { api } from "@/lib/api";
import { ArchivePanel, EmptyState, Tag } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function LearningLab() {
  const { feedback } = await api.feedback(100);

  const good = feedback.filter((f) => f.verdict === "good_catch").length;
  const bad = feedback.filter((f) => f.verdict === "false_positive").length;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · feedback loop</p>
        <h1 className="mt-2 font-display text-3xl font-bold">Learning Lab</h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          Engineers grade the gate. Every grade is retained as memory, so the
          next verdict on a similar change is different — measurably.
        </p>
      </header>

      <section className="mt-6 grid gap-3 sm:grid-cols-3">
        <ArchivePanel label="good_catch">
          <p className="font-display text-3xl font-bold text-ok">{good}</p>
          <p className="evidence-label mt-1">reinforces flagging</p>
        </ArchivePanel>
        <ArchivePanel label="false_positive">
          <p className="font-display text-3xl font-bold text-danger">{bad}</p>
          <p className="evidence-label mt-1">dampens future alarms</p>
        </ArchivePanel>
        <ArchivePanel label="retained memories">
          <p className="font-display text-3xl font-bold">{feedback.length}</p>
          <p className="evidence-label mt-1">kind:feedback units</p>
        </ArchivePanel>
      </section>

      <section className="mt-6">
        <h2 className="font-display text-xl font-semibold">
          How the loop closes
        </h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li>An engineer confirms or rejects a verdict (signed submission).</li>
          <li>The feedback is retained into Hindsight with kind:feedback tags.</li>
          <li>Future analyses recall these memories and weigh them in the verdict.</li>
          <li>
            Confidence math includes a feedback term — see the archive record of
            any re-analyzed diff.
          </li>
        </ol>
      </section>

      <section className="mt-6">
        <h2 className="font-display text-xl font-semibold">Feedback ledger</h2>
        {feedback.length === 0 ? (
          <div className="mt-3">
            <EmptyState>
              No grades yet. The first signed feedback submission will appear
              here and in the memory bank.
            </EmptyState>
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {feedback.map((f) => (
              <div
                key={f.id}
                className="border border-line bg-paper-raised px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`stamp ${
                      f.verdict === "good_catch"
                        ? "text-ok border-ok"
                        : "text-danger border-danger"
                    }`}
                  >
                    {f.verdict}
                  </span>
                  <span className="font-mono text-xs text-ink-soft">
                    case #{f.analysis_id} · {f.reviewer ?? "anonymous"} ·{" "}
                    {f.created_at ? new Date(f.created_at).toLocaleString() : ""}
                  </span>
                </div>
                {f.note ? (
                  <p className="mt-2 font-display text-sm">“{f.note}”</p>
                ) : null}
                <div className="mt-2">
                  <Tag>analysis:{f.analysis_id}</Tag>
                  <Tag>feedback_verdict:{f.verdict}</Tag>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
