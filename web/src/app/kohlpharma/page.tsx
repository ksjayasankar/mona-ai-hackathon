"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { tenantByKey } from "@/lib/brand";
import {
  postInterview,
  type CompetencyGroup,
  type InterviewKit,
} from "@/lib/api/interview";

// ---- Kohlpharma branding (core.config CUSTOMERS["kohlpharma"]) ----
const T = tenantByKey("kohlpharma");
const BRAND = T?.color ?? "#0e7490";

const COMPETENCY_META: Record<string, { icon: string; blurb: string }> = {
  Technical: { icon: "🛠️", blurb: "Can they actually do the work?" },
  "Problem-solving": { icon: "🧩", blurb: "How do they think under pressure?" },
  Behavioural: { icon: "🤝", blurb: "How do they work with people?" },
};

function PrimaryButton({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{ backgroundColor: BRAND }}
      className="inline-flex items-center rounded-lg px-3.5 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function QuestionRow({ q, n }: { q: CompetencyGroup["questions"][number]; n: number }) {
  return (
    <li className="px-5 py-4">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold text-white"
          style={{ backgroundColor: BRAND }}
        >
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-slate-900">{q.question}</p>
          <div className="mt-2 space-y-1.5 text-sm">
            <p className="flex gap-2 text-slate-700">
              <span aria-hidden>✅</span>
              <span>
                <span className="font-medium text-slate-600">Strong answer includes: </span>
                {q.strong_answer}
              </span>
            </p>
            <p className="flex gap-2 text-slate-700">
              <span aria-hidden>🚩</span>
              <span>
                <span className="font-medium text-slate-600">Red flag if: </span>
                {q.red_flag}
              </span>
            </p>
          </div>
        </div>
      </div>
    </li>
  );
}

function CompetencyCard({ group, startAt }: { group: CompetencyGroup; startAt: number }) {
  const meta = COMPETENCY_META[group.competency] ?? { icon: "💬", blurb: "" };
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-lg" aria-hidden>
            {meta.icon}
          </span>
          <div>
            <h3 className="font-semibold text-slate-900">{group.competency}</h3>
            {meta.blurb && <p className="text-xs text-slate-500">{meta.blurb}</p>}
          </div>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
          {group.questions.length} question{group.questions.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="divide-y divide-slate-100">
        {group.questions.map((q, i) => (
          <QuestionRow key={i} q={q} n={startAt + i} />
        ))}
      </ul>
    </Card>
  );
}

function KitView({ kit }: { kit: InterviewKit }) {
  // running question number across competency groups
  let running = 1;
  return (
    <div className="space-y-6">
      {/* role hero */}
      <Card className="overflow-hidden">
        <div className="px-6 py-5" style={{ backgroundColor: `${BRAND}12` }}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: BRAND }}>
                Interview kit for
              </p>
              <h2 className="mt-0.5 text-2xl font-bold tracking-tight text-slate-900">{kit.role_title}</h2>
              <p className="mt-1.5 max-w-prose text-sm text-slate-600">{kit.role_overview}</p>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-3xl font-bold tabular-nums" style={{ color: BRAND }}>
                {kit.confidence.toFixed(0)}%
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-slate-400">fit</div>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-6 py-3 text-xs text-slate-500">
          <span>
            {kit.question_count} question{kit.question_count === 1 ? "" : "s"} ·{" "}
            {kit.competencies.length} competenc{kit.competencies.length === 1 ? "y" : "ies"}
          </span>
          {kit.roles_found.length > 1 && (
            <span>
              Also found in this offer:{" "}
              {kit.roles_found
                .slice(1)
                .map((r) => r.title)
                .join(", ")}
            </span>
          )}
          <span className="text-slate-400">{kit.source_note}</span>
        </div>
      </Card>

      {/* questions grouped by competency */}
      <section className="space-y-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Questions to ask — grouped by what they test
        </h2>
        {kit.competencies.map((group) => {
          const start = running;
          running += group.questions.length;
          return <CompetencyCard key={group.competency} group={group} startAt={start} />;
        })}
      </section>

      {/* red-flag checklist */}
      <Card className="overflow-hidden">
        <div className="flex items-center gap-2.5 border-b border-amber-200 bg-amber-50 px-5 py-3">
          <span className="text-lg" aria-hidden>
            🚩
          </span>
          <div>
            <h3 className="font-semibold text-amber-900">Red-flag checklist</h3>
            <p className="text-xs text-amber-800/90">General warning signs to watch for in any candidate.</p>
          </div>
        </div>
        <ul className="divide-y divide-slate-100">
          {kit.red_flag_checklist.map((item, i) => (
            <li key={i} className="flex items-start gap-3 px-5 py-3 text-sm text-slate-700">
              <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-amber-500" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </Card>

      {/* raw JSON */}
      <details className="rounded-xl border border-slate-200 bg-white px-4 py-3">
        <summary className="cursor-pointer text-xs text-slate-400">Raw interview kit (JSON)</summary>
        <pre className="mt-2 overflow-auto rounded bg-slate-50 p-3 text-xs text-slate-600">
          {JSON.stringify(kit, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export default function KohlpharmaPage() {
  const [kit, setKit] = useState<InterviewKit | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(file: File | null, label: string) {
    setBusy(label);
    setError(null);
    setKit(null);
    try {
      setKit(await postInterview(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-slate-900">
      {/* header */}
      <header className="mb-8 border-l-4 pl-4" style={{ borderColor: BRAND }}>
        <p className="text-xs font-semibold tracking-widest" style={{ color: BRAND }}>
          KOHLPHARMA · HIRING MANAGER
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">{T?.icon ?? "💬"} Interview Copilot</h1>
        <p className="mt-1.5 text-slate-600">
          Turns a job offer into role-relevant interview questions and a red-flag checklist — written so a
          non-technical manager can tell a strong answer from a weak one.
        </p>
      </header>

      {error && <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">⚠️ {error}</p>}

      {/* input */}
      <Card className="mb-6 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <PrimaryButton onClick={() => run(null, "sample")} disabled={busy !== null}>
            {busy === "sample" ? "Reading the job offer…" : "Use the sample job offer"}
          </PrimaryButton>
          <span className="text-sm text-slate-500">— or upload your own:</span>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.docx,.txt"
            className="text-sm text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200"
            disabled={busy !== null}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) run(file, file.name);
            }}
          />
        </div>
        <p className="mt-3 text-xs text-slate-400">
          The copilot reads the offer, picks the open role, and writes the interview kit. One click — no setup.
        </p>
      </Card>

      {/* result */}
      {busy && !kit && (
        <Card className="p-6 text-sm text-slate-500">Reading the job offer and writing your interview kit…</Card>
      )}
      {kit && <KitView kit={kit} />}
      {!kit && !busy && (
        <Card className="p-6 text-sm text-slate-500">
          Click “Use the sample job offer” (or upload one) to generate the interview questions and red-flag checklist.
        </Card>
      )}
    </main>
  );
}
