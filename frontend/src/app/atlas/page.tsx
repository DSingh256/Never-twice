import { api } from "@/lib/api";
import { ArchivePanel, EmptyState, Tag } from "@/components/ui";

export const dynamic = "force-dynamic";

/* Sections mirror backend/api/memory.py ATLAS_SECTIONS: the tag convention
 * `retain.py` actually writes. Every unit shown is a real retained memory. */
const KINDS = [
  { tag: "kind:incident_summary", label: "Incident summaries" },
  { tag: "kind:failed_fix", label: "Failed fixes" },
  { tag: "kind:successful_fix", label: "What finally worked" },
  { tag: "kind:precursor_signature", label: "Precursor signatures" },
  { tag: "kind:feedback", label: "Engineer feedback" },
];

export default async function Atlas() {
  const [stats, ...sections] = await Promise.all([
    api.memoryStats(),
    ...KINDS.map(async (k) => ({ ...k, result: await api.memories(k.tag, 12) })),
  ]);

  const total = sections.reduce(
    (n, s) => n + (s.result.total ?? s.result.memories.length),
    0
  );

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="border-b border-ink pb-6">
        <p className="evidence-label">Black Box Archive · memory map</p>
        <h1 className="mt-2 font-display text-3xl font-bold">Atlas</h1>
        <p className="mt-2 max-w-2xl font-display text-lg italic text-ink-soft">
          The organization&apos;s memory, read straight from the bank — incidents,
          failed fixes, what finally worked, and every grade engineers have
          given the gate.
        </p>
      </header>

      {stats ? (
        <section className="mt-4 flex flex-wrap gap-x-8 gap-y-2 font-mono text-xs">
          <span>
            <span className="evidence-label">bank </span>
            {stats.bank_id}
          </span>
          <span>
            <span className="evidence-label">memory units </span>
            {stats.total_memory_units}
          </span>
          <span>
            <span className="evidence-label">documents </span>
            {stats.documents}
          </span>
          {Object.entries(stats.by_type).map(([t, n]) => (
            <span key={t}>
              <span className="evidence-label">{t} </span>
              {n}
            </span>
          ))}
        </section>
      ) : null}

      {total === 0 ? (
        <div className="mt-6">
          <EmptyState>
            The memory bank shows nothing yet. Run ingestion to retain real
            incident memory.
          </EmptyState>
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          {sections.map((s) => (
            <section key={s.tag}>
              <h2 className="font-display text-xl font-semibold">
                {s.label} <span className="evidence-label">{s.tag}</span>
              </h2>
              {s.result.memories.length === 0 ? (
                <p className="mt-2 text-sm text-ink-soft">
                  nothing retained under this tag yet
                </p>
              ) : (
                <div className="mt-3 space-y-2">
                  {s.result.memories.map((m) => (
                    <div
                      key={m.id}
                      className="border border-line bg-paper-raised px-4 py-3"
                    >
                      <p className="text-sm">
                        {m.text ?? m.content ?? "(memory text unavailable)"}
                      </p>
                      {m.tags && m.tags.length > 0 ? (
                        <div className="mt-2">
                          {m.tags.slice(0, 6).map((t) => (
                            <Tag key={t}>{t}</Tag>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
    </main>
  );
}
