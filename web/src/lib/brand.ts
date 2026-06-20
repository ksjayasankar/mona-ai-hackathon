// TS mirror of core/config.py CUSTOMERS — the single source for per-tenant branding
// on the web. Keep colors/icons in sync with the Python registry. Each flagship that
// ships a real page sets `href`; until then the station shows its build status.

export type AgentStatus = "live" | "locked" | "building" | "prototype";

export interface Tenant {
  key: string;
  n: number;
  company: string;
  city: string;
  dept: string;
  color: string; // brand hex — drives the station's rail + chip + node
  icon: string;
  agent: string;
  promise: string;
  status: AgentStatus;
  href?: string; // set once the flagship's page lands
}

export const STATUS_LABEL: Record<AgentStatus, string> = {
  live: "Live",
  locked: "Spec locked",
  building: "In build",
  prototype: "Prototype",
};

// order = problem number
export const TENANTS: Tenant[] = [
  {
    key: "globus", n: 1, company: "Globus Group", city: "St. Wendel", dept: "Finance",
    color: "#0a7d3f", icon: "🧾", agent: "Invoice Triage Agent", status: "locked",
    promise: "Reads any invoice, extracts the key fields, and routes it to the right department for a one-click confirm.",
  },
  {
    key: "uks", n: 2, company: "Universitätsklinikum des Saarlandes", city: "Homburg", dept: "HR / Staffing",
    color: "#b3122b", icon: "🏥", agent: "Shift Replacement Agent", status: "live", href: "/uks",
    promise: "Message it a shift gap; it finds available, qualified staff and drafts the outreach automatically.",
  },
  {
    key: "leistenschneider", n: 3, company: "Leistenschneider", city: "Saarbrücken", dept: "Compliance",
    color: "#1f4e8c", icon: "🛂", agent: "Work-Permit Validator", status: "live", href: "/leistenschneider",
    promise: "Confirms a document really is a work permit, with a calibrated confidence % and the valid-until date.",
  },
  {
    key: "persowerk", n: 4, company: "Persowerk Deutschland", city: "Saarbrücken", dept: "Talent / Verification",
    color: "#6b21a8", icon: "🔎", agent: "CV & Certificate Authenticity Agent", status: "live", href: "/persowerk",
    promise: "Cross-checks work history, flags fabrication signals, and verifies certificates are real and current.",
  },
  {
    key: "kohlpharma", n: 5, company: "Kohlpharma", city: "Merzig", dept: "Hiring Manager",
    color: "#0e7490", icon: "💬", agent: "Interview Copilot", status: "live", href: "/kohlpharma",
    promise: "Turns a job offer into role-relevant interview questions and a red-flag checklist.",
  },
  {
    key: "theiss_reels", n: 6, company: "Dr. Theiss Naturwaren", city: "Homburg", dept: "Marketing",
    color: "#15803d", icon: "🎬", agent: "Reel Studio Agent", status: "live", href: "/theiss-reels",
    promise: "Generates a vertical reel with script, captions and voiceover — text kept inside platform safe zones.",
  },
  {
    key: "theiss_analytics", n: 7, company: "Dr. Theiss Naturwaren", city: "Homburg", dept: "Marketing",
    color: "#15803d", icon: "📊", agent: "Targeting Analytics Agent", status: "live", href: "/theiss-analytics",
    promise: "Segments customer data, recommends the best date/time to market, then measures the lift.",
  },
  {
    key: "theiss_pricing", n: 8, company: "Dr. Theiss Naturwaren", city: "Homburg", dept: "Marketing / Pricing",
    color: "#15803d", icon: "💶", agent: "Dynamic Pricing Agent", status: "live", href: "/theiss-pricing",
    promise: "A signal-driven pricing engine with hard guardrails and a written rationale for every move.",
  },
  {
    key: "theiss_gaps", n: 9, company: "Dr. Theiss Naturwaren", city: "Homburg", dept: "Marketing / Strategy",
    color: "#15803d", icon: "🧭", agent: "Competitive Gap Agent", status: "live", href: "/theiss-gaps",
    promise: "Benchmarks the product set against competitors and surfaces concrete white-space gaps to capture.",
  },
  {
    key: "rheinmetall", n: 10, company: "Rheinmetall", city: "Düsseldorf", dept: "Recruiting / Security",
    color: "#3f6ea5", icon: "🛡️", agent: "Secure Intake Agent", status: "live", href: "/rheinmetall",
    promise: "Processes applicant emails + documents injection-resistant, and checks every required document is present.",
  },
];

export const tenantByKey = (key: string): Tenant | undefined =>
  TENANTS.find((t) => t.key === key);
