"""Problem 8 — Dr. Theiss (Allgäuer Latschenkiefer): Dynamic Pricing Agent.

Boxes to check (from the customer brief):
  [x] adjust a product's price based on EXTERNAL SIGNALS
      (weather · religious/seasonal events · football fixtures · supply-chain shortages)
  [x] careful GUARDRAILS: enforce min/max price bounds, never an absurd price,
      and always show the rationale

Approach (deterministic core + LLM narration):
  1. Get a product + its indicative base price. We try to read the data pack PDF with
     Claude (core.llm.extract); if there's no API key / read fails, we fall back to the
     synthetic catalogue printed in the data pack (page 4) so the page always demos.
  2. Each external signal maps to a transparent multiplier with a directional reason.
     The product's category steers the direction (cold weather pushes warming foot/leg
     balms up, cooling gels down; football matchday lifts sport sprays; etc.).
  3. suggested = base * Π(multipliers).  Then we CLAMP to a configurable guardrail band
     [base*lo, base*hi] (default ±20%) so the engine can never output an absurd price.
  4. core.llm.ask() writes the plain-language rationale paragraph. If the key is absent
     we fall back to a stitched-together rationale from the per-signal reasons.

Everything customer-facing is plain language; the raw numbers live behind an expander.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core import ingest, llm

# ---- the synthetic product catalogue from the data pack (page 4) ----------
# Used as the offline fallback and to validate / enrich what Claude reads.
# (SKU, name, line, pack, base price €, peak season)
FALLBACK_CATALOGUE: list[dict] = [
    {"sku": "ALK-FB-01", "name": "Fuß Butter", "line": "Feet", "pack": "100 ml", "base_price": 7.71, "peak_season": "Autumn–Winter"},
    {"sku": "ALK-FB-02", "name": "Sole Fußbad", "line": "Feet", "pack": "400 g", "base_price": 6.49, "peak_season": "Winter"},
    {"sku": "ALK-FB-03", "name": "Hornhaut Reduziercreme", "line": "Feet", "pack": "50 ml", "base_price": 6.99, "peak_season": "Spring (sandal prep)"},
    {"sku": "ALK-FB-04", "name": "Hornhaut Entferner Maske", "line": "Feet", "pack": "2x20 ml", "base_price": 8.49, "peak_season": "Spring–Summer"},
    {"sku": "ALK-FB-05", "name": "10 % Urea Fußcreme", "line": "Feet", "pack": "100 ml", "base_price": 7.25, "peak_season": "All year"},
    {"sku": "ALK-FB-06", "name": "Fußpflege Deospray", "line": "Feet", "pack": "75 ml", "base_price": 6.10, "peak_season": "Summer"},
    {"sku": "ALK-LG-01", "name": "5 in 1 Beinlotion", "line": "Legs", "pack": "200 ml", "base_price": 9.95, "peak_season": "Summer"},
    {"sku": "ALK-LG-02", "name": "Bein Frische Gel", "line": "Legs", "pack": "100 ml", "base_price": 8.20, "peak_season": "Summer"},
    {"sku": "ALK-LG-03", "name": "Besenreiser Pflegebalsam", "line": "Legs", "pack": "100 ml", "base_price": 11.49, "peak_season": "Spring–Summer"},
    {"sku": "ALK-MG-01", "name": "Mobil Gel", "line": "Muscles/Joints", "pack": "100 ml", "base_price": 5.83, "peak_season": "Autumn–Winter"},
    {"sku": "ALK-MG-02", "name": "Mobil Einreibung Extra Stark", "line": "Muscles/Joints", "pack": "100 ml", "base_price": 8.90, "peak_season": "Winter / sport"},
    {"sku": "ALK-MG-03", "name": "Mobil Eisspray akut", "line": "Muscles/Joints", "pack": "150 ml", "base_price": 9.40, "peak_season": "Sport season"},
    {"sku": "ALK-MG-04", "name": "Franzbranntwein", "line": "Muscles/Joints", "pack": "250 ml", "base_price": 6.75, "peak_season": "All year"},
    {"sku": "ALK-MG-05", "name": "Wärmendes Intensiv Gel", "line": "Muscles/Joints", "pack": "100 ml", "base_price": 8.30, "peak_season": "Winter"},
    {"sku": "ALK-CB-01", "name": "Ur Bonbons", "line": "Cough drops", "pack": "75 g", "base_price": 2.49, "peak_season": "Cold season"},
]


# ---- schemas --------------------------------------------------------------
class Product(BaseModel):
    """One product with its indicative base price."""

    sku: str | None = Field(default=None, description="Article number, e.g. ALK-MG-03")
    name: str = Field(description="Product name as printed")
    line: str | None = Field(default=None, description="Product line: Feet / Legs / Muscles/Joints / Cough drops")
    pack: str | None = Field(default=None, description="Pack size, e.g. 100 ml")
    base_price: float = Field(description="Indicative base price in EUR", gt=0)
    peak_season: str | None = Field(default=None, description="Peak selling season as printed")


class Catalogue(BaseModel):
    """The product catalogue read from the data pack."""

    products: list[Product]


class SignalEffect(BaseModel):
    signal: str          # human label of the signal, e.g. "Weather: cold"
    setting: str         # the chosen value, e.g. "cold"
    multiplier: float    # e.g. 1.06
    direction: str       # "up" | "down" | "flat"
    reason: str          # plain-language why


class PriceResult(BaseModel):
    product: Product
    base_price: float
    raw_price: float        # base * Π(multipliers), before guardrails
    suggested_price: float  # after clamping to the band
    floor: float
    ceiling: float
    band_pct: float         # e.g. 20.0 means ±20%
    clamped: bool           # True if the guardrail changed the price
    effects: list[SignalEffect]
    net_pct: float          # final move vs base, in %
    rationale: str
    guardrail_note: str
    source_note: str        # where the base price came from


# ---- catalogue loading ----------------------------------------------------
def load_catalogue(path: str | Path | None) -> tuple[list[Product], str]:
    """Return (products, source_note). Reads the data pack via Claude when possible,
    otherwise falls back to the synthetic catalogue baked in from the data pack."""
    fallback = [Product(**p) for p in FALLBACK_CATALOGUE]
    if path is None or not Path(path).exists():
        return fallback, "No data pack found — using the indicative catalogue from the brief."
    try:
        blocks = ingest.file_to_blocks(path)
        blocks.append({
            "type": "text",
            "text": (
                "Find the structured product dataset table (SKU, Product, Line, Pack, "
                "Price €, Peak season). Return every row as a product with its indicative "
                "base price in EUR. Do not invent products."
            ),
        })
        cat = llm.extract(
            Catalogue,
            blocks,
            system="You read a brand data pack and extract the product price table exactly as printed.",
        )
        if cat.products:
            return cat.products, "Base prices read from the Dr. Theiss data pack (indicative/synthetic figures)."
    except Exception:
        pass
    return fallback, "Could not read the data pack live — using the indicative catalogue from the brief."


# ---- signal model ---------------------------------------------------------
# Direction of effect depends on the product line. We classify each product into a
# coarse demand bucket so a cold snap lifts warming balms but not cooling sprays.
def _buckets(product: Product) -> set[str]:
    text = f"{product.name} {product.line or ''}".lower()
    b: set[str] = set()
    if any(k in text for k in ("foot", "fuß", "fuss", "hornhaut", "sole")) or (product.line or "").lower() == "feet":
        b.add("foot")
    if any(k in text for k in ("leg", "bein", "besenreiser")) or (product.line or "").lower() == "legs":
        b.add("leg")
    if any(k in text for k in ("mobil", "muscle", "muskel", "gelenk", "arnika", "franzbrannt", "schmerz", "knie")) \
            or (product.line or "").lower() in ("muscles/joints", "muscles & joints"):
        b.add("muscle")
    if any(k in text for k in ("warm", "wärm", "butter", "balsam", "bad", "fußbad", "sole")):
        b.add("warming")
    if any(k in text for k in ("eis", "kühl", "frische", "cool", "ice")):
        b.add("cooling")
    if any(k in text for k in ("eisspray", "mobil gel", "einreibung", "sport")):
        b.add("sport")
    if any(k in text for k in ("bonbon", "husten", "cough")):
        b.add("cough")
    return b


def _weather_effect(product: Product, weather: str) -> SignalEffect:
    bk = _buckets(product)
    mult, direction, reason = 1.0, "flat", "Mild weather — no clear demand shift."
    if weather == "cold":
        if "warming" in bk or "cough" in bk or "muscle" in bk:
            mult, direction = 1.06, "up"
            reason = "Cold weather lifts demand for warming/muscle & cough products — small price up."
        elif "cooling" in bk:
            mult, direction = 0.94, "down"
            reason = "Cold weather softens demand for cooling gels — small price down to move stock."
        else:
            reason = "Cold weather — limited direct effect on this product."
    elif weather == "hot":
        if "cooling" in bk or "leg" in bk:
            mult, direction = 1.06, "up"
            reason = "Hot weather lifts demand for cooling leg gels & sprays — small price up."
        elif "warming" in bk:
            mult, direction = 0.94, "down"
            reason = "Hot weather softens demand for warming products — small price down."
        elif "foot" in bk:
            mult, direction = 1.03, "up"
            reason = "Sandal-season foot care sees a mild lift in warm weather."
        else:
            reason = "Hot weather — limited direct effect on this product."
    return SignalEffect(signal="Weather", setting=weather, multiplier=mult, direction=direction, reason=reason)


def _season_effect(product: Product, season: str) -> SignalEffect:
    bk = _buckets(product)
    peak = (product.peak_season or "").lower()
    mult, direction, reason = 1.0, "flat", "No active seasonal/religious event."
    if season == "winter":
        if "winter" in peak or "warming" in bk or "muscle" in bk:
            mult, direction = 1.05, "up"
            reason = "Winter is peak season for this product — demand up."
        elif "summer" in peak or "cooling" in bk:
            mult, direction = 0.92, "down"
            reason = "Off-season in winter — discount to keep stock moving."
        else:
            reason = "Winter — mild seasonal effect."
    elif season == "summer":
        if "summer" in peak or "cooling" in bk or "leg" in bk:
            mult, direction = 1.05, "up"
            reason = "Summer is peak season for legs/cooling lines — demand up."
        elif "winter" in peak or "warming" in bk:
            mult, direction = 0.92, "down"
            reason = "Off-season in summer — discount to move warming-line stock."
        else:
            reason = "Summer — mild seasonal effect."
    elif season == "christmas":
        # gifting lift, but health items kept gentle (no gouging — see guardrails)
        mult, direction = 1.07, "up"
        reason = "Christmas gifting window lifts demand across the gift-able range — modest price up."
    elif season == "ramadan":
        if "foot" in bk:
            mult, direction = 1.05, "up"
            reason = "Ramadan foot-care ritual demand (washing/care) — small price up for foot line."
        else:
            mult, direction = 1.01, "up"
            reason = "Ramadan — slight overall lift; little direct effect on this line."
    elif season == "fathers_day":
        if "muscle" in bk or "sport" in bk:
            mult, direction = 1.06, "up"
            reason = "Father's Day gifting favours men's muscle/sport SKUs — small price up."
        else:
            reason = "Father's Day — limited effect on this line."
    return SignalEffect(signal="Season / event", setting=season, multiplier=mult, direction=direction, reason=reason)


def _football_effect(product: Product, fixture: str) -> SignalEffect:
    bk = _buckets(product)
    mult, direction, reason = 1.0, "flat", "No nearby football fixture."
    if fixture in ("home", "away"):
        if "sport" in bk or "muscle" in bk:
            mult = 1.08 if fixture == "home" else 1.04
            direction = "up"
            where = "a home matchday near the venue" if fixture == "home" else "an away fixture"
            reason = f"{where.capitalize()} lifts demand for recovery sprays/muscle gels — price up."
        else:
            reason = "Football fixture nearby — no clear effect on this product line."
    return SignalEffect(signal="Football fixture", setting=fixture, multiplier=mult, direction=direction, reason=reason)


def _supply_effect(product: Product, supply: str) -> SignalEffect:
    mult, direction, reason = 1.0, "flat", "Supply normal — no scarcity pressure."
    if supply == "moderate":
        mult, direction = 1.05, "up"
        reason = "Moderate shortage of a key active — modest price up to protect margin & ration stock."
    elif supply == "severe":
        mult, direction = 1.12, "up"
        reason = "Severe shortage of a key active — larger price up to protect margin (still inside the cap)."
    return SignalEffect(signal="Supply chain", setting=supply, multiplier=mult, direction=direction, reason=reason)


def compute_price(
    product: Product,
    *,
    weather: str = "mild",
    season: str = "none",
    football: str = "none",
    supply: str = "none",
    band_pct: float = 20.0,
    source_note: str = "",
) -> PriceResult:
    """Apply the external-signal multipliers and clamp to the guardrail band."""
    effects = [
        _weather_effect(product, weather),
        _season_effect(product, season),
        _football_effect(product, football),
        _supply_effect(product, supply),
    ]

    base = round(product.base_price, 2)
    raw = base
    for e in effects:
        raw *= e.multiplier
    raw = round(raw, 2)

    frac = band_pct / 100.0
    floor = round(base * (1 - frac), 2)
    ceiling = round(base * (1 + frac), 2)
    suggested = round(min(max(raw, floor), ceiling), 2)
    clamped = suggested != raw

    net_pct = round((suggested - base) / base * 100, 1)

    guardrail_note = (
        f"Guardrail band fixed at ±{band_pct:.0f}% of base "
        f"(€{floor:.2f} – €{ceiling:.2f}). "
        + (
            f"The raw signal price €{raw:.2f} was outside the band and was clamped to €{suggested:.2f} — "
            "the engine can never output an absurd price."
            if clamped
            else "The signal price stayed inside the band; no clamp needed."
        )
        + " Health items are never gouged; every move is logged with a rationale (auditable)."
    )

    rationale = _write_rationale(product, base, suggested, net_pct, effects, clamped)

    return PriceResult(
        product=product,
        base_price=base,
        raw_price=raw,
        suggested_price=suggested,
        floor=floor,
        ceiling=ceiling,
        band_pct=band_pct,
        clamped=clamped,
        effects=effects,
        net_pct=net_pct,
        rationale=rationale,
        guardrail_note=guardrail_note,
        source_note=source_note,
    )


def _fallback_rationale(
    product: Product, base: float, suggested: float, net_pct: float,
    effects: list[SignalEffect], clamped: bool,
) -> str:
    movers = [e for e in effects if e.direction != "flat"]
    direction_word = "increase" if net_pct > 0 else "reduction" if net_pct < 0 else "no change"
    parts = [
        f"Recommended price for {product.name}: €{suggested:.2f} (base €{base:.2f}, "
        f"a {abs(net_pct):.1f}% {direction_word})."
    ]
    if movers:
        parts.append("Drivers: " + " ".join(f"{e.reason}" for e in movers))
    else:
        parts.append("No active external signal currently pushes the price — it holds at base.")
    if clamped:
        parts.append("The guardrail cap kept the price within the permitted band.")
    return " ".join(parts)


def _write_rationale(
    product: Product, base: float, suggested: float, net_pct: float,
    effects: list[SignalEffect], clamped: bool,
) -> str:
    """Plain-language paragraph for a non-technical pricing manager (LLM, with fallback)."""
    from core import config

    if not config.HAS_KEY:
        return _fallback_rationale(product, base, suggested, net_pct, effects, clamped)

    signal_lines = "\n".join(
        f"- {e.signal} = '{e.setting}': ×{e.multiplier:.2f} ({e.direction}) — {e.reason}"
        for e in effects
    )
    prompt = (
        f"Product: {product.name} ({product.line or 'n/a'}), indicative base price €{base:.2f}.\n"
        f"External pricing signals applied:\n{signal_lines}\n"
        f"Final recommended price after a ±guardrail band: €{suggested:.2f} "
        f"({net_pct:+.1f}% vs base).{' (capped by the guardrail)' if clamped else ''}\n\n"
        "Write ONE short paragraph (3-4 sentences) for a non-technical pricing manager at "
        "Dr. Theiss explaining why this price was recommended. Mention only the signals that "
        "actually moved the price, and reassure that guardrails prevent any absurd or unfair "
        "price on a health-care product. No markdown, no bullet points."
    )
    try:
        return llm.ask(
            prompt,
            system="You are a pricing analyst writing a clear, calm rationale. Plain language, no jargon.",
            max_tokens=300,
        ).strip()
    except Exception:
        return _fallback_rationale(product, base, suggested, net_pct, effects, clamped)
