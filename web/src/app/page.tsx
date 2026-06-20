import Link from "next/link";
import { TENANTS, STATUS_LABEL, type AgentStatus, type Tenant } from "@/lib/brand";
import { Eyebrow, StatusDot, Stat } from "@/components/ui";

const NODE: Record<AgentStatus, { color: string; pulse: boolean }> = {
  live: { color: "#1f9d57", pulse: true },
  building: { color: "#c98a16", pulse: true },
  locked: { color: "#5b8cff", pulse: false },
  prototype: { color: "#8a9bb4", pulse: false },
};

function Station({ t }: { t: Tenant }) {
  const node = NODE[t.status];
  const inner = (
    <div
      style={{ ["--accent" as string]: t.color } as React.CSSProperties}
      className="group relative flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-ink-2 p-5 transition duration-200 hover:-translate-y-0.5 hover:border-[var(--accent)] hover:bg-ink-3"
    >
      {/* brand-rail: which tenant, encoded as color */}
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ backgroundColor: t.color }} />

      <div className="flex items-start justify-between">
        <span
          className="flex h-10 w-10 items-center justify-center rounded-xl border text-lg"
          style={{ backgroundColor: `${t.color}1f`, borderColor: `${t.color}55` }}
        >
          {t.icon}
        </span>
        <div className="flex items-center gap-2">
          <StatusDot color={node.color} pulse={node.pulse} />
          <span className="text-xs font-medium text-haze">{STATUS_LABEL[t.status]}</span>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <span className="font-mono text-xs text-haze">P{String(t.n).padStart(2, "0")}</span>
        <span className="font-mono text-xs text-haze">·</span>
        <span className="font-mono text-xs text-haze">{t.dept}</span>
      </div>

      <h3 className="mt-1 font-display text-lg font-semibold text-chalk">{t.agent}</h3>
      <div className="text-sm font-medium text-haze">{t.company}</div>
      <p className="mt-3 text-sm leading-relaxed text-haze/90">{t.promise}</p>

      <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
        <span className="font-mono text-xs text-haze">{t.city}</span>
        {t.href ? (
          <span className="inline-flex items-center gap-1 text-sm font-semibold text-chalk transition group-hover:gap-2">
            Open <span aria-hidden>→</span>
          </span>
        ) : (
          <span className="font-mono text-xs text-haze/70">
            {t.status === "prototype" ? "in Streamlit suite" : "wiring up"}
          </span>
        )}
      </div>
    </div>
  );

  return t.href ? (
    <Link href={t.href} className="block h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-signal rounded-2xl">
      {inner}
    </Link>
  ) : (
    inner
  );
}

export default function Home() {
  const flagships = TENANTS.filter((t) => t.status !== "prototype").length;
  const live = TENANTS.filter((t) => t.status === "live").length;

  return (
    <main className="min-h-screen bg-ink text-chalk">
      <div className="mx-auto max-w-6xl px-6 py-6">
        {/* top bar */}
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-signal/15 font-display text-sm font-bold text-signal">
              M
            </span>
            <Eyebrow className="text-haze">Mona AI · Agent Platform</Eyebrow>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1">
            <StatusDot color="#1f9d57" pulse />
            <span className="font-mono text-xs text-haze">env: dev</span>
          </span>
        </header>

        {/* hero — open with the most characteristic thing: a fleet of branded agents */}
        <section className="grid gap-10 py-16 md:grid-cols-[1.5fr_1fr] md:items-end">
          <div>
            <Eyebrow className="text-signal">Ten customers · one secure platform</Eyebrow>
            <h1 className="mt-4 font-display text-5xl font-bold leading-[1.04] tracking-tight text-chalk md:text-6xl">
              An agent for every
              <br />
              back-office that hurts.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-haze">
              Each customer gets their own agent and their own brand — sharing one multi-tenant
              spine: a tool-using agent loop, scoped data, and injection-resistant document intake
              by default. Same platform, ten identities.
            </p>
          </div>

          <div className="grid grid-cols-3 gap-6 rounded-2xl border border-line bg-ink-2 p-6 md:grid-cols-1 md:gap-5">
            <Stat value={TENANTS.length} label="Customer agents" />
            <Stat value={flagships} label="Productized flagships" />
            <Stat value={live} label="Live end-to-end" />
          </div>
        </section>

        {/* the stations */}
        <section className="pb-20">
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="font-display text-sm font-semibold uppercase tracking-[0.16em] text-haze">
              Agent stations
            </h2>
            <span className="font-mono text-xs text-haze">color = tenant</span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {TENANTS.map((t) => (
              <Station key={t.key} t={t} />
            ))}
          </div>
        </section>

        <footer className="border-t border-line py-8">
          <p className="font-mono text-xs text-haze">
            Mona AI Hackathon 2026 · FastAPI + Next.js + Supabase · provider-switch LLM
          </p>
        </footer>
      </div>
    </main>
  );
}
