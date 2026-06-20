# Design System — Mona AI Agent Suite (web) · Globus flagship reference

> **Read this before any visual/UI work in `web/`.** It is the production handoff the
> `ui.tsx` comment promises ("the production look will come from a Claude Design handoff
> bundle"). Tokens, type scale, color, spacing, motion, and the invoice-triage component
> patterns are defined here. Do not deviate without explicit user approval.
>
> **Scope.** Part 1 is the **shared web foundation** every flagship inherits. Part 2 is the
> **Globus Invoice Triage** layer (the first worked flagship). Future flagships (P2 UKS,
> P4 Persowerk, …) should **extend** this file with their own Part-2 section keyed on their
> `core.config.CUSTOMERS` accent — not fork a new design system.
>
> _Created by `/design-consultation` (2026-06-20). The project's hard rules forbid editing
> `CLAUDE.md`/`web/AGENTS.md`, so the "read DESIGN.md first" pointer lives here rather than
> there._

---

# Part 1 — Shared web foundation (the suite)

## Product context
- **What this is:** A suite of customer AI agents presented as **one app, ten distinct
  customer products** (per `core/config.py`: "not ten tabs of one tool"). Each agent gets
  its own branded page; all share one design foundation.
- **Who it's for:** Non-technical business users (an AP clerk, a recruiter, a staffer) who
  must reach a clear verdict in one upload/click — no terminal, no JSON.
- **Stack:** Next.js 16 · React 19 · **Tailwind v4** (CSS-first: `@import "tailwindcss"`
  + `@theme inline`, no `tailwind.config.js`) · Geist Sans / Geist Mono.
- **Reference page:** `web/src/app/rheinmetall/page.tsx` (the layout idiom). Shared
  primitives: `web/src/components/ui.tsx` (`Card`, `Button`, `Badge`).

## Aesthetic direction
- **Direction:** Industrial / Utilitarian — function-first, data-dense, restrained.
- **Decoration:** Minimal. Type, the per-customer accent, and semantic status color do all
  the work. No textures, gradients, blobs, or decorative chrome.
- **Mood:** Precise, trustworthy, calm. Looks like serious software for serious work. The
  product earns trust by looking exact, not decorated.

## Typography
- **Display / page title:** **Geist Sans 700**, `letter-spacing:-0.02em`. No separate
  display face — staying on Geist keeps the suite coherent.
- **Body / UI:** **Geist Sans** 400 (body), 500/600 (labels, buttons, chips).
- **Data / money / IDs:** **Geist Mono** with **`tabular-nums`** — mandatory for every
  amount, invoice number, date, VAT %, and confidence %. Aligned decimals let a clerk scan a
  column of totals. (Tailwind: `font-mono tabular-nums`.)
- **Loading:** Geist is already wired in `web/src/app/layout.tsx` via `next/font/google`
  (`--font-geist-sans`, `--font-geist-mono`).
- **Scale (px):** eyebrow 11 · caption 12 · body 14 · UI 13 · h3 17 · h2-section-label 13
  (uppercase, tracked) · h1 30.
- ⚠️ **Finding to fix (`web/src/app/globals.css:25`):** `body { font-family: Arial, … }`
  overrides Geist even though it is loaded. Body renders in Arial today. The implementer
  should switch `body` to `var(--font-geist-sans)`. (Shared file — out of the design pass's
  edit scope; flagged here.)

## Color
- **Approach:** Balanced — slate neutral frame + one per-customer brand accent + semantic
  status tones. Color is meaningful, never decorative.
- **Neutrals (slate):** `50 #f8fafc · 100 #f1f5f9 · 200 #e2e8f0 · 300 #cbd5e1 · 400 #94a3b8
  · 500 #64748b · 600 #475569 · 700 #334155 · 900 #0f172a`. Ink = 900, sub/eyebrow = 500/600,
  lines = 200.
- **Per-customer accent:** comes from `core.config.CUSTOMERS[key].color`. Used for the header
  rule, primary CTAs, and the eyebrow accent **only**. (Globus = `#0a7d3f`, see Part 2.)
- **Semantic status** (shared, from `Badge` tones): success `green-100/800` · warning
  `amber-100/800` · error `red-100/800` · neutral `slate-100/700`.
- **Dark mode:** redesign surfaces (don't just invert); reduce accent saturation ~10–20%.
  Suite default today is light; pages should be legible in both.

## Spacing
- **Base unit:** 4px. Scale: `2xs 2 · xs 4 · sm 8 · md 16 · lg 24 · xl 32 · 2xl 48`.
- **Density:** comfortable for landing/marketing; **compact** for data-dense agent
  workspaces (Card `p-4`/`p-5`, list rows `space-y-1.5`).

## Layout
- **Approach:** grid-disciplined. Page container `mx-auto max-w-5xl px-6 py-10`.
- **Branded header idiom:** `border-l-4 border-[accent] pl-4` → eyebrow
  (`text-xs font-semibold tracking-widest text-slate-500`, uppercase) → emoji + `h1` →
  one-line `text-slate-600` subtitle.
- **Body:** two-column `md:grid-cols-2` (input → results); results may use an asymmetric
  split (~0.8 / 1.2) when the result side is data-dense.
- **Border radius:** `sm 6 · md 10 · lg 14 · pill 9999`. Cards `rounded-xl` (matches
  existing `ui.tsx`).

## Motion
- **Approach:** minimal-functional. Plain transitions on hover/state.
- **Easing/duration:** enter `ease-out`, exit `ease-in`, move `ease-in-out`; micro 50–100ms,
  short 150–250ms, medium 250–400ms.
- **One sanctioned entrance beat per agent** where it carries meaning (see Globus split
  reveal). No scroll choreography, no ambient animation.

---

# Part 2 — Globus · Invoice Triage Agent (P1 flagship)

**`core.config.CUSTOMERS["globus"]`:** company "Globus Group" · St. Wendel · dept Finance ·
**color `#0a7d3f`** · icon **🧾** · agent "Invoice Triage Agent".

## North star — the one memorable thing
**"I'm still in control."** Every extracted number is grounded to the printed text it was
read from and carries a confidence; nothing is approved automatically; anything below
threshold routes to a human first. This is the headline acceptance box ("flag for human
confirm") and what separates it from naive OCR.

## The color contract (the heart of the system)
Two color languages, never mixed:
- **Brand green `#0a7d3f`** is spent **only on human actions and trust**: the header rule,
  primary CTAs (*Approve*, *Send to approver*), the routing chip, the evidence highlight.
  Hover `#0a6a36`; tints `green-50 #e9f4ee`, `green-100 #d2e9dc`.
- **Status color is the invoice's own trust state**, never brand:
  - **Grounded / high** → green `ok #16a34a` (bg `#f0fdf4`, fg `#166534`, border `#bbf7d0`)
  - **Needs review / medium** → amber `warn #d97706` (bg `#fffbeb`, fg `#92400e`, border `#fde68a`)
  - **Blocked / duplicate / low** → red `bad #dc2626` (bg `#fef2f2`, fg `#991b1b`, border `#fecaca`)
- **Evidence highlight:** verbatim source snippet sits on `#ecfdf3` ("we read it here").
- Discipline so it never looks like a traffic light: status color appears only on the
  **status chip + the card's 4px left border + the per-field confidence pill** — fills stay
  muted (`-50`/`-100`), never saturated blocks.

## Confidence threshold contract
- **Per-field confidence (0–100%)** rendered as a pill: `≥85 ok · 70–84 warn · <70 bad`.
- **Invoice status from its fields:**
  - all fields grounded **and** all ≥85 → **grounded** (approvable, may auto-route by rule).
  - any field <70, or any field ungrounded (no source snippet) → **needs_review** (held;
    not approvable until a human confirms the flagged fields).
  - fingerprint collision → **duplicate** (held; see below) regardless of confidence.
- The threshold (`70`) lives in one place in code; the UI reads it, never hard-codes per row.

## Triage component patterns (the implementer's spec)
Build these in `web/src/app/globus/` (page) reusing `Card`/`Button`/`Badge`; add new
primitives to `ui.tsx` only if a pattern is reused. Keep `ui.tsx` easy to restyle.

1. **Branded header** — Part-1 idiom with `border-[#0a7d3f]`, eyebrow
   `PROBLEM 1 · GLOBUS GROUP · ST. WENDEL · FINANCE / AP`, `🧾 Invoice Triage Agent`, subtitle.
2. **Intake panel** (left col) — email body `textarea` + multi-file drop (PDF/photo/Word) +
   *Run triage* (primary green). One note that the **IMAP/Gmail connector is pluggable but the
   demo uses a simulated inbox** (no creds) — matches the P10 secure-intake pattern.
3. **Split stack** (right col) — header `Detected invoices · N found · counts by status`.
   One **invoice card** per split result:
   - 4px left border colored by status; number glyph (①②③); vendor title; meta line
     (`invoice # · filename · page/evidence span`); status **badge** top-right.
   - **Evidence-first field rows** (`grid 96px / 1fr / auto`): key · (value in
     `mono tabular-nums` + verbatim snippet on `#ecfdf3`) · **confidence pill**.
   - **Routing row:** category → **routing chip** (green, `→ Operations`). When the rule
     table falls through to *Finance review*, show the **LLM-suggested** dept with its
     one-line reason and a neutral "suggested" treatment (not a confident green chip).
   - **Card action bar:** rule provenance badge · *View source* (ghost) · status-appropriate
     primary (*Approve →* green when grounded; *Confirm N fields* amber when needs_review).
4. **needs_review card** — amber border; amber banner "*N fields below the 70% threshold —
   routed to a human to confirm before approval*"; low-confidence field shows a `?` marker and
   a snippet describing why (e.g. "glare over middle digit"); held, not approvable.
5. **duplicate / amended card** — red border; red banner naming the match ("*same vendor +
   invoice number as ①, total differs €1,420 vs €1,240 — possible amendment, not auto-dropped*");
   shows the **fingerprint** `vendor·number·total·date`; actions *Compare · Keep both · Reject*.
   Never silently drop.
6. **Approval & audit** — approve panel ("all fields grounded · routed to X") with *Approve &
   route* + *Send to approver*; note that approval writes **approver + timestamp + outcome** to
   the audit log. **Recent triage** history list = timestamp + status badges (+ dept chip).
7. **Raw JSON** — only ever inside an expander, never the primary surface.

## Split reveal (the one sanctioned motion beat)
When N invoices are detected they **stagger in** (≈420ms `cubic-bezier(.2,.7,.3,1)`,
~60–80ms stagger, `translateY(8px)`→0 + fade). Makes "it split them" felt — the demo wow
beat. Everything else is plain transitions. Respect `prefers-reduced-motion`.

## Implementation notes
- Tailwind v4: add Globus tokens (`--color-globus`, status tints) via `@theme` in
  `globals.css` **only if** the implementer is authorized to touch that shared file; otherwise
  use the hex values above inline / via a local CSS module in `web/src/app/globus/`.
- Reuse `Badge` tones (`green/amber/red/slate`) for status; they already match the contract.
- Numbers: always `font-mono tabular-nums`. Money right-aligned in any column view.
- A static, faithful HTML render of all the above lives at the preview produced this session
  (the `/tmp/globus-design-preview-*.html` artifact) — use it as the visual source of truth.

---

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-20 | Created DESIGN.md (suite foundation + Globus flagship) via `/design-consultation` | No prior design doc; system was implicit in `rheinmetall/page.tsx` + `ui.tsx` + `core.config.CUSTOMERS`. |
| 2026-06-20 | Direction: **inherit the suite, add a green AP + confidence layer** (not a distinct fork) | Honors `config.py` "one app, ten distinct products"; coherent with Rheinmetall; demoable on deadline. |
| 2026-06-20 | North star: **"I'm still in control"** (trust through transparency) | Headline P1 acceptance box is "flag for human confirm"; grounded extraction + per-field confidence is the differentiator vs OCR. |
| 2026-06-20 | **Color contract:** brand green = human actions/trust; status color = invoice trust state | Lets a clerk read trust at a glance without the UI becoming a traffic light. |
| 2026-06-20 | **Geist Mono + tabular-nums** mandatory for all numeric data | Aligned decimals are table stakes for scanning AP totals. |
| 2026-06-20 | Did **not** edit CLAUDE.md / web/AGENTS.md to add the design pointer | Project hard rules forbid it; pointer lives at the top of this file instead. |
| 2026-06-20 | globals.css Arial override flagged, not fixed | Shared file outside the design pass's edit scope; implementer to switch `body` to Geist. |
