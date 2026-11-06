import Link from "next/link";

import { ThemeToggle } from "./theme-toggle";

const REPO = "https://github.com/Gnanasudharsan/polymath-swarm";

/** Brand mark: three agents (nodes) around a shared blackboard, inside a verified shield shape. */
export function LogoMark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="pm-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="color-mix(in oklch, var(--primary) 55%, var(--success))" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#pm-g)" />
      <g stroke="var(--primary-foreground)" strokeWidth="1.6" strokeLinecap="round" opacity="0.9">
        <path d="M16 9.5 L9.5 20.5 M16 9.5 L22.5 20.5 M9.5 20.5 H22.5" />
      </g>
      <g fill="var(--primary-foreground)">
        <circle cx="16" cy="9.5" r="2.6" />
        <circle cx="9.5" cy="20.5" r="2.6" />
        <circle cx="22.5" cy="20.5" r="2.6" />
      </g>
      <circle cx="16" cy="16.8" r="1.5" fill="var(--primary-foreground)" opacity="0.65" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-4" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.93-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.8.06 1.23.83 1.23.83.72 1.22 1.88.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/65">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
          <LogoMark />
          <span>Polymath</span>
          <span className="-ml-1.5 font-normal text-muted-foreground">Swarm</span>
        </Link>
        <nav className="hidden items-center gap-1 text-sm sm:flex">
          <Link
            href="/"
            className="rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            New problem
          </Link>
          <Link
            href="/#runs"
            className="rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            Runs
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <a
            href={REPO}
            target="_blank"
            rel="noreferrer"
            className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Source on GitHub"
          >
            <GitHubIcon />
          </a>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs text-muted-foreground sm:px-6">
        <p>Claims are stated only with evidence: a verified citation, a reproduced computation, or a Lean 4 proof.</p>
        <a href={REPO} target="_blank" rel="noreferrer" className="hover:text-foreground">
          MIT licensed · source
        </a>
      </div>
    </footer>
  );
}
