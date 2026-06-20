"""§AufenthG work-authorization corpus — the legal-generalization layer for P3.

WHY: a residence permit ("Aufenthaltstitel") does not always PRINT whether employment
is allowed; for many permit types it is settled by STATUTE. A Blue Card holder may work
by law; a § 16b student is restricted by law. To validate ANY Aufenthaltstitel (not just
the four labelled samples) we keep a small, hand-curated rule set mapping permit type /
legal basis -> default work authorization + whether a Zusatzblatt governs the detail +
the legal citation. The validity logic consults this to resolve permits where
authorization is IMPLIED by law rather than printed, and CITES the basis in its reasons.

Two access paths, by design:
  - lookup()   : DETERMINISTIC substring match (offline, no model). The verdict relies on
                 this, so the common path is pure and unit-testable without any LLM.
  - retrieve() : SEMANTIC match via core.rag (provider-namespaced embeddings). Used only
                 to GENERALIZE to novel wording the deterministic matcher misses.

Citations are hand-curated from German law (AufenthG / FEG). firecrawl is 402/out of
credits right now, so the corpus is curated, not scraped — but `index()` makes it
enrichable from firecrawl later. We do NOT fabricate citations.
"""
from __future__ import annotations

from dataclasses import dataclass

from core import rag

CORPUS = "aufenthg_rules"


@dataclass
class WorkAuthRule:
    id: str
    permit_type: str           # human-readable permit class
    default_work: str          # "permitted" | "restricted" | "prohibited" | "unknown"
    zusatzblatt_required: bool  # does a Zusatzblatt / Nebenbestimmung govern the detail?
    source: str                # the statute, e.g. "§ 18g AufenthG"
    citation: str              # the verbatim-ish legal statement (German)
    note: str                  # plain-English gloss for the reviewer


# Ordered MOST-SPECIFIC first; lookup() returns the first whose tokens match.
# `match` tokens are lowercase; matched against "legal_basis + document_type".
_RULES: list[dict] = [
    {
        "id": "blaue_karte_eu",
        "match": ["blaue karte", "blue card", "18g"],
        "permit_type": "Blaue Karte EU (EU Blue Card)",
        "default_work": "permitted",
        "zusatzblatt_required": False,
        "source": "§ 18g AufenthG",
        "citation": "Die Blaue Karte EU berechtigt zur Ausübung der im Titel bezeichneten "
                    "qualifizierten Beschäftigung (§§ 18g–18i AufenthG; vormals § 18b Abs. 2 AufenthG).",
        "note": "EU Blue Card — qualified employment is authorized by statute.",
    },
    {
        "id": "niederlassungserlaubnis",
        "match": ["niederlassung", "settlement"],
        "permit_type": "Niederlassungserlaubnis (settlement permit)",
        "default_work": "permitted",
        "zusatzblatt_required": False,
        "source": "§ 9 AufenthG",
        "citation": "Die Niederlassungserlaubnis ist unbefristet und berechtigt zur Ausübung "
                    "einer Erwerbstätigkeit (§ 9 Abs. 1 AufenthG).",
        "note": "Permanent settlement permit — gainful employment is permitted.",
    },
    {
        "id": "fachkraft_18a_18b",
        "match": ["18a", "18b", "fachkraft"],
        "permit_type": "Aufenthaltserlaubnis für Fachkräfte (skilled worker)",
        "default_work": "permitted",
        "zusatzblatt_required": False,
        "source": "§ 18a / § 18b AufenthG",
        "citation": "Die Aufenthaltserlaubnis für Fachkräfte mit Berufsausbildung (§ 18a) bzw. "
                    "mit akademischer Ausbildung (§ 18b) berechtigt zur Ausübung einer "
                    "qualifizierten Beschäftigung.",
        "note": "Skilled-worker residence permit — qualified employment is permitted.",
    },
    {
        "id": "beschaeftigung_19c",
        "match": ["19c"],
        "permit_type": "Aufenthaltserlaubnis zur Beschäftigung",
        "default_work": "permitted",
        "zusatzblatt_required": True,
        "source": "§ 19c AufenthG",
        "citation": "Die Aufenthaltserlaubnis nach § 19c AufenthG berechtigt zur Ausübung der "
                    "konkret bezeichneten Beschäftigung nach Maßgabe der Beschäftigungsverordnung.",
        "note": "Employment permit — tied to the specific job named in the Nebenbestimmungen.",
    },
    {
        "id": "studium_16b",
        "match": ["16b", "studium", "student"],
        "permit_type": "Aufenthaltserlaubnis zum Studium",
        "default_work": "restricted",
        "zusatzblatt_required": True,
        "source": "§ 16b AufenthG",
        "citation": "Zum Studium berechtigt die Aufenthaltserlaubnis nur zu einer eingeschränkten "
                    "Erwerbstätigkeit (i.d.R. 140 ganze bzw. 280 halbe Tage je Jahr, § 16b AufenthG); "
                    "eine allgemeine Beschäftigung bedarf der Erlaubnis.",
        "note": "Student permit — employment is restricted; check the Zusatzblatt / day limit.",
    },
    {
        "id": "berufsausbildung_16a",
        "match": ["16a"],
        "permit_type": "Aufenthaltserlaubnis zur Berufsausbildung",
        "default_work": "restricted",
        "zusatzblatt_required": True,
        "source": "§ 16a AufenthG",
        "citation": "Die Aufenthaltserlaubnis zur Berufsausbildung (§ 16a AufenthG) berechtigt zur "
                    "ausbildungsbezogenen Tätigkeit; eine davon unabhängige Beschäftigung ist nur "
                    "eingeschränkt zulässig.",
        "note": "Vocational-training permit — employment is tied to the training; side jobs limited.",
    },
    {
        "id": "voruebergehender_schutz_24",
        "match": ["24 aufenthg", "vorübergehender schutz", "temporary protection"],
        "permit_type": "Aufenthaltserlaubnis (vorübergehender Schutz)",
        "default_work": "permitted",
        "zusatzblatt_required": False,
        "source": "§ 24 AufenthG",
        "citation": "Beim vorübergehenden Schutz nach § 24 AufenthG ist die Erwerbstätigkeit "
                    "gestattet.",
        "note": "Temporary protection (e.g. § 24) — employment is permitted by statute.",
    },
    {
        "id": "humanitaer_25",
        "match": ["25 abs. 1", "25 abs. 2", "25 abs 1", "25 abs 2"],
        "permit_type": "Aufenthaltserlaubnis aus humanitären Gründen",
        "default_work": "permitted",
        "zusatzblatt_required": False,
        "source": "§ 25 Abs. 1 / Abs. 2 AufenthG",
        "citation": "Anerkannte Asylberechtigte, Flüchtlinge und subsidiär Schutzberechtigte "
                    "(§ 25 Abs. 1 bzw. Abs. 2 AufenthG) sind zur Ausübung einer Erwerbstätigkeit "
                    "berechtigt.",
        "note": "Recognized refugee / subsidiary protection — employment is permitted.",
    },
]

_BY_ID = {r["id"]: r for r in _RULES}


def _to_rule(d: dict) -> WorkAuthRule:
    return WorkAuthRule(**{k: v for k, v in d.items() if k != "match"})


def lookup(legal_basis: str | None, document_type: str | None = None) -> WorkAuthRule | None:
    """Deterministic match. Offline, no model. Returns None if nothing matches."""
    hay = " ".join(x for x in (legal_basis, document_type) if x).lower()
    if not hay.strip():
        return None
    for rule in _RULES:
        if any(tok in hay for tok in rule["match"]):
            return _to_rule(rule)
    return None


def _doc_text(r: dict) -> str:
    return f"{r['permit_type']}. Rechtsgrundlage {r['source']}. {r['citation']} {r['note']}"


def seed_corpus(provider: str | None = None, reset: bool = False) -> int:
    """Index the rules into core.rag (provider-namespaced). Idempotent (upsert)."""
    docs = [{"id": r["id"], "text": _doc_text(r), "meta": {"id": r["id"], "source": r["source"]}}
            for r in _RULES]
    return rag.index(CORPUS, docs, provider=provider, reset=reset)


def retrieve(query: str, provider: str | None = None) -> WorkAuthRule | None:
    """Semantic fallback via core.rag — generalizes to wording lookup() misses.
    Degrades honestly to None if the vector store / embeddings are unavailable."""
    try:
        if not rag.retrieve(CORPUS, "ping", k=1, provider=provider):
            seed_corpus(provider=provider)
        hits = rag.retrieve(CORPUS, query, k=1, provider=provider)
    except Exception:
        return None
    if not hits:
        return None
    rid = (hits[0].get("meta") or {}).get("id")
    return _to_rule(_BY_ID[rid]) if rid in _BY_ID else None


def resolve(legal_basis: str | None, document_type: str | None = None, *,
            use_rag: bool = False, provider: str | None = None) -> WorkAuthRule | None:
    """Deterministic lookup first (pure); semantic RAG fallback only if asked and needed."""
    rule = lookup(legal_basis, document_type)
    if rule is None and use_rag:
        q = " ".join(x for x in (legal_basis, document_type) if x).strip()
        if q:
            rule = retrieve(q, provider=provider)
    return rule
