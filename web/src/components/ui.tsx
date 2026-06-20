import { type ReactNode } from "react";

// Mona AI shared UI primitives. The originals (Card, Button, Badge) keep their exact
// signatures so existing flagship pages don't break; new primitives are opt-in and
// derive from the design tokens in globals.css. Tenant accent comes in as a hex string.

/* ---- surfaces ---------------------------------------------------------- */

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-2xl border border-edge bg-paper shadow-[0_1px_2px_rgba(11,15,26,0.04),0_8px_24px_-12px_rgba(11,15,26,0.12)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Section({
  title,
  hint,
  children,
  className = "",
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      {title && (
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 className="font-display text-sm font-semibold uppercase tracking-[0.14em] text-fog">{title}</h2>
          {hint && <span className="font-mono text-xs text-fog">{hint}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

/* ---- controls ---------------------------------------------------------- */

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: "primary" | "ghost" | "accent";
  className?: string;
}) {
  const variants: Record<string, string> = {
    primary: "bg-ink text-chalk hover:bg-ink-3",
    ghost: "border border-edge bg-paper text-ink hover:bg-paper-3",
    accent: "text-white hover:brightness-110",
  };
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition disabled:opacity-50 disabled:pointer-events-none ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

/* ---- labels + signals -------------------------------------------------- */

export function Badge({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: "slate" | "green" | "red" | "amber" | "blue" | "violet";
}) {
  const tones: Record<string, string> = {
    slate: "bg-paper-3 text-fog",
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    amber: "bg-amber-100 text-amber-800",
    blue: "bg-blue-100 text-blue-800",
    violet: "bg-violet-100 text-violet-800",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`font-mono text-xs font-medium uppercase tracking-[0.22em] ${className}`}>
      {children}
    </span>
  );
}

export function StatusDot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {pulse && (
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ backgroundColor: color }}
        />
      )}
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
    </span>
  );
}

/* ---- data display ------------------------------------------------------ */

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div>
      <div className="font-display text-2xl font-semibold tabular-nums text-chalk">{value}</div>
      <div className="mt-0.5 text-xs text-haze">{label}</div>
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[0.82em] ${className}`}>{children}</span>;
}
