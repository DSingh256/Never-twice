"use client";

/* Shared UI primitives for the Black Box Archive. */

const LEVEL_STYLES: Record<string, { label: string; cls: string }> = {
  high: { label: "HIGH RISK", cls: "text-danger border-danger" },
  medium: { label: "ELEVATED", cls: "text-warn border-warn" },
  low: { label: "LOW RISK", cls: "text-ok border-ok" },
  none: { label: "NO RISK", cls: "text-ink-soft border-line" },
  failed: { label: "FAILED", cls: "text-danger border-danger" },
};

export function LevelStamp({ level }: { level?: string | null }) {
  const key = (level ?? "none").toLowerCase();
  const s = LEVEL_STYLES[key] ?? LEVEL_STYLES.none;
  return <span className={`stamp ${s.cls}`}>{s.label}</span>;
}

export function ConfidenceBar({
  value,
}: {
  value: number | null | undefined;
}) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  return (
    <span
      className="inline-flex items-center gap-2"
      title={`confidence ${value}`}
    >
      <span className="evidence-label">conf</span>
      <span className="relative inline-block h-1.5 w-24 bg-line align-middle">
        <span
          className="absolute left-0 top-0 h-full bg-accent"
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="font-mono text-xs">{pct}%</span>
    </span>
  );
}

export function ArchivePanel({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`border border-line bg-paper-raised ${className}`}
    >
      <header className="border-b border-line px-4 py-2">
        <span className="evidence-label">{label}</span>
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-dashed border-line bg-paper-raised px-6 py-10 text-center">
      <p className="font-display text-lg italic text-ink-soft">{children}</p>
      <p className="mt-2 font-mono text-xs text-ink-soft">
        No fabricated data. The archive fills as real memory is ingested.
      </p>
    </div>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="mr-1 inline-block bg-ink/5 px-1.5 py-0.5 font-mono text-[0.65rem] text-ink-soft">
      {children}
    </span>
  );
}
