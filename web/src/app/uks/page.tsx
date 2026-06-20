"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import {
  API_BASE,
  type Eligible,
  type GapState,
  type Outreach,
  createGap,
  escalate,
  seed,
  startOutreach,
} from "./api";

const SAMPLE_MSG =
  "Felix Haddad (HOSP-1059) just called in sick for tonight's ICU night shift " +
  "(Sat 06/20, 19:00-07:00). He's a Registered Nurse, ICU needs BLS + ACLS. Find me cover ASAP.";

const FELIX_STRUCTURED = {
  role: "Registered Nurse",
  department: "ICU",
  shift: "night",
  day_label: "Sat 06/20",
  required_certs: ["BLS", "ACLS"],
  person_out: "Felix Haddad (HOSP-1059)",
};

const ESCALATE_AFTER = 30; // seconds before auto-escalating to the next candidate

const STATUS_TONE: Record<string, "slate" | "green" | "red" | "amber"> = {
  queued: "slate",
  sent: "amber",
  accepted: "green",
  declined: "red",
  closed: "slate",
};

export default function UksDashboard() {
  const [message, setMessage] = useState(SAMPLE_MSG);
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
      if (res?.gap) setSt(res as GapState);
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

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 text-slate-900">
      {/* branded header */}
      <div className="mb-8 border-l-4 pl-4" style={{ borderColor: "#b3122b" }}>
        <p className="text-xs font-semibold tracking-widest text-slate-500">
          PROBLEM 2 · UNIVERSITÄTSKLINIKUM DES SAARLANDES (UKS) · HR / STAFFING
        </p>
        <h1 className="text-3xl font-bold">🏥 Shift Replacement Agent</h1>
        <p className="mt-1 text-slate-600">
          Message the gap. It finds <strong>available, qualified, ArbZG-compliant</strong> staff, reaches out in
          fairness order, and locks the first to accept — live.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        {/* intake */}
        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="mb-3 text-lg font-semibold">Report a shift gap</h2>
            <label className="mb-1 block text-sm font-medium">Sick-call message</label>
            <textarea
              className="mb-3 h-36 w-full rounded-lg border border-slate-300 p-2 text-sm"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <div className="flex flex-col gap-2">
              <Button onClick={() => load({ message })} disabled={busy}>
                {busy ? "Working…" : "Find cover (AI parses the message)"}
              </Button>
              <button
                onClick={() => load({ structured: FELIX_STRUCTURED })}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Load tonight&apos;s ICU scenario (no AI)
              </button>
            </div>
            {err && <p className="mt-3 text-sm text-red-700">⚠️ {err}</p>}
          </Card>

          {st && (
            <Card className="p-5">
              <h2 className="mb-2 text-lg font-semibold">The gap</h2>
              <p className="text-sm text-slate-700">
                <strong>{st.gap.person_out ?? "A staff member"}</strong> is out.
              </p>
              <ul className="mt-2 space-y-1 text-sm text-slate-600">
                <li>
                  Role: <strong>{st.gap.role}</strong>
                  {st.gap.department ? ` · ${st.gap.department}` : ""}
                </li>
                <li>
                  {st.gap.shift} shift · {st.gap.day_label}
                  {st.gap.shift_start && st.gap.shift_end
                    ? ` · ${st.gap.shift_start.slice(11, 16)}–${st.gap.shift_end.slice(11, 16)}`
                    : ""}
                </li>
                <li>Certs: {st.gap.required_certs.join(", ") || "role-based"}</li>
              </ul>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge tone={open ? "amber" : "green"}>{open ? "OPEN" : st.gap.status.toUpperCase()}</Badge>
                <span className="text-xs text-slate-500">
                  {st.counts.active} active screened · {st.counts.eligible} eligible · {st.excluded.length} excluded
                </span>
              </div>
            </Card>
          )}
        </div>

        {/* live board */}
        <div className="space-y-4">
          {!st && (
            <Card className="p-8 text-center text-slate-500">
              Report a gap to see ranked, compliant cover options appear here — live.
            </Card>
          )}

          {st && (
            <>
              {/* schedule strip */}
              <Card className={`p-5 ${open ? "" : "border-green-300 bg-green-50"}`}>
                <h2 className="mb-2 text-lg font-semibold">Schedule · {st.gap.day_label}</h2>
                {st.filled_by ? (
                  <p className="text-sm text-green-800">
                    ✅ <strong>{st.filled_by.name}</strong> is now covering the {st.gap.shift} shift — the roster cell
                    just flipped to <Badge tone="green">N</Badge>.
                  </p>
                ) : (
                  <p className="text-sm text-amber-700">
                    ⚠️ {st.gap.shift} shift is <strong>OPEN</strong> — reaching out to candidates in fairness order.
                  </p>
                )}
              </Card>

              {/* outreach controls */}
              <Card className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-lg font-semibold">Outreach</h2>
                  {!outreachStarted ? (
                    <Button onClick={onStartOutreach} disabled={busy || st.counts.eligible === 0}>
                      📤 Start outreach (SMS candidate #1)
                    </Button>
                  ) : open ? (
                    <div className="flex items-center gap-3">
                      {hasQueued && sentCount > 0 && (
                        <span className="text-xs text-slate-500">auto-escalates in {secs}s</span>
                      )}
                      <Button onClick={escalateNow} disabled={busy || !hasQueued}>
                        ⏭ Escalate now
                      </Button>
                    </div>
                  ) : (
                    <Badge tone="green">filled</Badge>
                  )}
                </div>
                {outreachStarted && (
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {st.outreach.map((o) => (
                      <li key={o.id} className="flex items-center justify-between">
                        <span>
                          #{o.seq + 1} {o.staff_name}
                        </span>
                        <Badge tone={STATUS_TONE[o.status] ?? "slate"}>{o.status}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              {/* ranked eligible */}
              <Card className="p-5">
                <h2 className="mb-3 text-lg font-semibold">
                  Ranked cover options <span className="text-sm font-normal text-slate-500">(eligible &amp; compliant)</span>
                </h2>
                {st.eligible.length === 0 ? (
                  <p className="text-sm text-slate-500">No one currently qualifies. Widen the role or relax certs.</p>
                ) : (
                  <div className="space-y-3">
                    {st.eligible.map((c, i) => (
                      <CandidateCard key={c.employee_id} c={c} rank={i + 1} outreach={outreachByEmp.get(c.employee_id)} />
                    ))}
                  </div>
                )}
              </Card>

              {/* excluded with reasons */}
              <Card className="p-5">
                <button
                  className="flex w-full items-center justify-between text-left"
                  onClick={() => setShowExcluded((v) => !v)}
                >
                  <h2 className="text-lg font-semibold">
                    Why others were excluded <span className="text-sm font-normal text-slate-500">({st.excluded.length})</span>
                  </h2>
                  <span className="text-slate-400">{showExcluded ? "▲" : "▼"}</span>
                </button>
                {showExcluded && (
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {st.excluded.map((e) => (
                      <li key={e.employee_id} className="flex items-start justify-between gap-3">
                        <span className="text-slate-700">
                          <strong>{e.name}</strong> · {e.role}
                          {e.department ? ` / ${e.department}` : ""} — {e.reason}
                        </span>
                        <Badge tone="red">{e.rule}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function CandidateCard({ c, rank, outreach }: { c: Eligible; rank: number; outreach?: Outreach }) {
  return (
    <div className={`rounded-lg border p-3 ${rank === 1 ? "border-amber-300 bg-amber-50" : "border-slate-200"}`}>
      <div className="flex items-center justify-between">
        <div className="font-semibold">
          {rank === 1 ? "🥇 " : `${rank}. `}
          {c.name} <span className="font-normal text-slate-500">· {c.role} / {c.department}</span>
        </div>
        <div className="flex items-center gap-2">
          {outreach && <Badge tone={STATUS_TONE[outreach.status] ?? "slate"}>{outreach.status}</Badge>}
          <Badge tone="slate">score {c.score}</Badge>
        </div>
      </div>
      <div className="mt-1 text-xs text-slate-500">
        📞 {c.phone} · {c.contract} · {Math.round(c.scheduled_hours)}/{Math.round(c.max_hours)}h this week ·{" "}
        {c.overtime_ok ? "OT OK ✅" : "OT: no"}
        {c.rest_hours != null ? ` · ${Math.round(c.rest_hours)}h rest` : ""}
      </div>
      <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">
        {c.why.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}
