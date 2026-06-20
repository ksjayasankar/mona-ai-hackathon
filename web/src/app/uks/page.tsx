"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, type GapState, type Outreach, createGap, escalate, seed, startOutreach } from "./api";
import { CandidateRow } from "./components/CandidateRow";
import { IntakePhone } from "./components/IntakePhone";
import { ScheduleGrid } from "./components/ScheduleGrid";
import { StatusPill } from "./components/StatusPill";

const ESCALATE_AFTER = 30; // seconds before auto-escalating to the next candidate

export default function UksDashboard() {
  const [gapId, setGapId] = useState<string | null>(null);
  const [st, setSt] = useState<GapState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);
  const [secs, setSecs] = useState(ESCALATE_AFTER);

  // ---- live updates over SSE -------------------------------------------------
  useEffect(() => {
    if (!gapId) return;
    const es = new EventSource(`${API_BASE}/agents/shift/gaps/${gapId}/events`);
    es.onmessage = (e) => {
      try {
        setSt(JSON.parse(e.data) as GapState);
      } catch {
        /* keep-alive / non-JSON frame */
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [gapId]);

  const open = st?.gap.status === "open";
  const sentCount = st?.outreach.filter((o) => o.status === "sent").length ?? 0;
  const hasQueued = st?.outreach.some((o) => o.status === "queued") ?? false;
  const outreachStarted = (st?.outreach.length ?? 0) > 0;

  // ---- auto-escalate countdown (resets each time a new candidate is contacted)
  const escalateNow = useCallback(async () => {
    if (!gapId) return;
    try {
      setSt((await escalate(gapId)) as unknown as GapState);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [gapId]);

  useEffect(() => setSecs(ESCALATE_AFTER), [sentCount]);
  const escalateRef = useRef(escalateNow);
  escalateRef.current = escalateNow;
  useEffect(() => {
    if (!(open && hasQueued && sentCount > 0)) return;
    const t = setInterval(() => {
      setSecs((s) => {
        if (s <= 1) {
          escalateRef.current();
          return ESCALATE_AFTER;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [open, hasQueued, sentCount]);

  async function load(body: { message?: string; structured?: object }) {
    setBusy(true);
    setErr(null);
    try {
      await seed();
      const state = await createGap(body);
      setSt(state);
      setGapId(state.gap.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onStartOutreach() {
    if (!gapId) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await startOutreach(gapId);
      if ((res as GapState)?.gap) setSt(res as GapState);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const outreachByEmp = new Map<string, Outreach>();
  st?.outreach.forEach((o) => {
    if (o.employee_id) outreachByEmp.set(o.employee_id, o);
  });

  const win = (start: string | null, end: string | null) =>
    start && end ? `${start.slice(11, 16)}–${end.slice(11, 16)}` : "";

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      {/* top bar */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#b3122b] text-lg text-white">🏥</div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                Universitätsklinikum des Saarlandes · HR / Staffing
              </div>
              <h1 className="text-lg font-bold leading-tight">Shift Replacement Agent</h1>
            </div>
          </div>
          {st && <StatusPill status={st.gap.status} />}
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-8 lg:grid-cols-[380px_1fr]">
        {/* left rail: intake + schedule */}
        <div className="space-y-6">
          <IntakePhone onSubmit={load} busy={busy} parsed={st?.gap ?? null} />
          {err && <p className="text-sm text-rose-700">⚠️ {err}</p>}

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Roster · this week</h2>
              {st?.schedule_preview?.gap_day && (
                <span className="text-[11px] text-slate-400">gap: {st.schedule_preview.gap_day}</span>
              )}
            </div>
            <ScheduleGrid preview={st?.schedule_preview} />
            {st?.roster_sync?.link && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
                ✅ Roster updated in{" "}
                {st.roster_sync.target === "google_sheets" ? "Google Sheets" : "the schedule file"} —{" "}
                {st.roster_sync.target === "google_sheets" ? (
                  <a className="font-medium text-[#b3122b] underline" href={st.roster_sync.link} target="_blank" rel="noreferrer">
                    open sheet
                  </a>
                ) : (
                  <code className="break-all text-slate-600">{st.roster_sync.link}</code>
                )}
              </p>
            )}
          </section>
        </div>

        {/* main column */}
        <div className="space-y-6">
          {!st && (
            <div className="grid place-items-center rounded-2xl border border-dashed border-slate-300 bg-white p-16 text-center text-slate-400">
              Send the sick-call from the phone on the left to see ranked, ArbZG-compliant cover options appear here — live.
            </div>
          )}

          {st && (
            <>
              {/* gap header */}
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">The gap</div>
                    <h2 className="mt-1 text-xl font-bold">
                      {st.gap.role}
                      {st.gap.department ? ` · ${st.gap.department}` : ""}
                    </h2>
                    <p className="mt-0.5 text-sm text-slate-500">
                      {st.gap.shift} shift · {st.gap.day_label}
                      {win(st.gap.shift_start, st.gap.shift_end) ? ` · ${win(st.gap.shift_start, st.gap.shift_end)}` : ""} ·
                      certs: {st.gap.required_certs.join(", ") || "role-based"}
                    </p>
                    {st.gap.person_out && (
                      <p className="mt-0.5 text-sm text-slate-400">
                        out sick: <span className="font-medium text-slate-600">{st.gap.person_out}</span>
                      </p>
                    )}
                  </div>
                  <div className="text-right text-xs text-slate-400">
                    <div className="text-2xl font-bold text-slate-900">{st.counts.eligible}</div>
                    eligible
                    <div className="mt-1">
                      {st.counts.active} screened · {st.excluded.length} excluded
                    </div>
                  </div>
                </div>

                {st.filled_by && (
                  <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                    ✅ <strong>{st.filled_by.name}</strong> is now covering the {st.gap.shift} shift — roster cell flipped to{" "}
                    <span className="font-bold">{st.gap.shift === "night" ? "N" : "D"}</span>.
                  </div>
                )}
              </section>

              {/* outreach controls */}
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Outreach</h2>
                  {!outreachStarted ? (
                    <button
                      onClick={onStartOutreach}
                      disabled={busy || st.counts.eligible === 0}
                      className="rounded-lg bg-[#b3122b] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#8f0e22] disabled:opacity-50"
                    >
                      📤 Start outreach (SMS #1)
                    </button>
                  ) : open ? (
                    <div className="flex items-center gap-3">
                      {hasQueued && sentCount > 0 && (
                        <span className="text-xs text-slate-400">auto-escalates in {secs}s</span>
                      )}
                      <button
                        onClick={escalateNow}
                        disabled={busy || !hasQueued}
                        className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                      >
                        ⏭ Escalate now
                      </button>
                    </div>
                  ) : (
                    <StatusPill status="filled" />
                  )}
                </div>
                {outreachStarted && (
                  <ol className="mt-3 space-y-1.5 text-sm">
                    {st.outreach.map((o) => (
                      <li key={o.id} className="flex items-center justify-between">
                        <span className="text-slate-600">
                          <span className="text-slate-400">#{o.seq + 1}</span> {o.staff_name}
                        </span>
                        <StatusPill status={o.status} />
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              {/* ranked candidates */}
              <section>
                <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-500">
                  Ranked cover options{" "}
                  <span className="font-normal normal-case text-slate-400">(eligible &amp; compliant)</span>
                </h2>
                {st.eligible.length === 0 ? (
                  <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
                    No one currently qualifies. Widen the role or relax certs.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {st.eligible.map((c, i) => (
                      <CandidateRow key={c.employee_id} c={c} rank={i + 1} outreach={outreachByEmp.get(c.employee_id)} />
                    ))}
                  </div>
                )}
              </section>

              {/* excluded */}
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <button className="flex w-full items-center justify-between text-left" onClick={() => setShowExcluded((v) => !v)}>
                  <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">
                    Why others were excluded <span className="font-normal text-slate-400">({st.excluded.length})</span>
                  </h2>
                  <span className="text-slate-400">{showExcluded ? "▲" : "▼"}</span>
                </button>
                {showExcluded && (
                  <ul className="mt-3 space-y-2 text-sm">
                    {st.excluded.map((e) => (
                      <li key={e.employee_id} className="flex items-start justify-between gap-3 border-t border-slate-100 pt-2">
                        <span className="text-slate-600">
                          <strong className="text-slate-800">{e.name}</strong> · {e.role}
                          {e.department ? ` / ${e.department}` : ""} — {e.reason}
                        </span>
                        <span className="shrink-0 rounded bg-rose-50 px-1.5 py-0.5 text-[11px] font-semibold text-rose-700">
                          {e.rule}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
