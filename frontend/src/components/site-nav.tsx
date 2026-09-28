"use client";

/* Global navigation — the black-box lid shared by every page.
 * Sticky (never fixed) so it participates in layout on both the paper
 * briefing pages and the cinematic dark rooms. Active route is amber. */

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Briefing" },
  { href: "/tribunal", label: "Tribunal" },
  { href: "/analyze", label: "Analysis Room" },
  { href: "/archive", label: "Archive" },
  { href: "/atlas", label: "Atlas" },
  { href: "/learning-lab", label: "Learning Lab" },
  { href: "/eval", label: "Eval" },
];

export function SiteNav() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-50 border-b border-black/25 bg-night/95 text-vellum backdrop-blur">
      <div className="mx-auto flex h-11 max-w-6xl items-center gap-6 px-4 md:px-6">
        <Link
          href="/"
          className="flex shrink-0 cursor-pointer items-center gap-2"
          aria-label="Never Twice — briefing"
        >
          <span className="inline-block h-2 w-2 bg-amber" aria-hidden />
          <span className="font-mono text-[10px] uppercase tracking-[0.28em] text-amber">
            Never Twice
          </span>
        </Link>
        <nav className="min-w-0 flex-1 overflow-x-auto" aria-label="Primary">
          <ul className="flex items-center gap-4 whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.12em] md:gap-5">
            {LINKS.map((l) => {
              const active = isActive(l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={active ? "page" : undefined}
                    className={`cursor-pointer transition-colors ${
                      active ? "text-amber" : "text-vellum-dim hover:text-amber"
                    }`}
                  >
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
