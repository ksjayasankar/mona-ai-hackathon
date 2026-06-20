import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 text-slate-900">
      <p className="text-xs font-semibold tracking-widest text-slate-500">MONA AI · AGENT SUITE</p>
      <h1 className="mt-2 text-4xl font-bold">Customer Agents</h1>
      <p className="mt-3 text-slate-600">
        Production build. Phase 0 ships the shared foundation (auth · multi-tenant DB · tool-using
        agent loop · RAG) with the first flagship wired end-to-end.
      </p>

      <div className="mt-8 space-y-3">
        <Link
          href="/rheinmetall"
          className="block rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-400"
        >
          <div className="text-xs font-semibold tracking-widest text-slate-500">P10 · RHEINMETALL</div>
          <div className="text-lg font-bold">🛡️ Secure Intake Agent</div>
          <div className="text-sm text-slate-600">
            Injection-resistant applicant intake + required-document completeness. Live.
          </div>
        </Link>

        <div className="rounded-xl border border-dashed border-slate-200 p-5 text-slate-400">
          <div className="text-lg font-semibold">P2 UKS · P4 Persowerk</div>
          <div className="text-sm">Next flagships — built in parallel worktrees on this foundation.</div>
        </div>
      </div>
    </main>
  );
}
