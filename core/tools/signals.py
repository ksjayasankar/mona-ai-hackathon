"""P8 external-signal connectors — the pluggable SignalConnector layer.

Each connector returns a SignalReading (defined in agents.pricing_product, the pure
engine that consumes them). Signals attach to the FIXED category taxonomy, never to
SKUs, so they apply to any uploaded catalogue.

  LIVE + keyless:
    WeatherConnector  -> Open-Meteo   (https://api.open-meteo.com)
    HolidayConnector  -> Nager.Date   (https://date.nager.at)
  SEEDED from a committed snapshot (firecrawl-pluggable later; it's 402 now):
    SeededConnector(SEED_NEWS | SEED_SUPPLY | SEED_FOOTBALL)
  HONEST degradation:
    UnconfiguredConnector -> configured=False, never fabricates data

HTTP is stdlib urllib with a short timeout. Any failure degrades to a FLAT reading
(no fabricated demand), so the demo never hangs or 500s when an upstream is slow/down.
fetch_all runs connectors concurrently and drops any that raise.
"""
from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from agents.pricing_product import SignalReading


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_get_json(url: str, timeout: float = 4.0):
    req = urllib.request.Request(url, headers={"User-Agent": "mona-pricing/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted keyless APIs)
        return json.loads(resp.read().decode("utf-8"))


# ---- seeded snapshots (synthetic, committed; swap for firecrawl when credited) ----
SEED_NEWS = {
    "source": "seeded:news", "label": "Regional flu-season uptick",
    "affected_categories": ["cold_remedy"], "direction": "up", "magnitude": 0.5, "health_event": True,
    "evidence": "Cached snapshot: rising influenza/cold activity reported in SW Germany (synthetic demo data).",
}
SEED_SUPPLY = {
    "source": "seeded:supply", "label": "Menthol / eucalyptus supply tightness",
    "affected_categories": ["cold_remedy", "muscle_joint"], "direction": "up", "magnitude": 0.4, "health_event": False,
    "evidence": "Cached snapshot: menthol & eucalyptus-oil spot prices up ~12% QoQ (synthetic demo data).",
}
SEED_FOOTBALL = {
    "source": "seeded:football", "label": "1. FC Saarbruecken home matchday",
    "affected_categories": ["muscle_joint"], "direction": "up", "magnitude": 0.3, "health_event": False,
    "evidence": "Cached fixture snapshot: home match this weekend; recovery-gel demand near the venue (synthetic).",
}


class WeatherConnector:
    """Open-Meteo forecast -> a weather demand signal. Cold snap is a HEALTH event."""
    def __init__(self, lat: float = 49.32, lon: float = 7.34, place: str = "Homburg"):
        self.lat, self.lon, self.place = lat, lon, place
        self.name = "Open-Meteo"

    def _url(self) -> str:
        return (f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}"
                "&daily=temperature_2m_min,temperature_2m_max&forecast_days=1&timezone=auto")

    def fetch(self, *, _get=_http_get_json) -> SignalReading | None:
        try:
            data = _get(self._url(), timeout=4.0)
        except Exception:
            return SignalReading(
                source=self.name, label=f"Weather unavailable ({self.place})", affected_categories=[],
                direction="flat", evidence="Open-Meteo unreachable; no weather signal applied.",
                fetched_at=_now(), configured=True, source_url=self._url())
        return self.parse(data, _now())

    def parse(self, data: dict, fetched_at: str) -> SignalReading:
        daily = data.get("daily", {}) or {}
        tmin = (daily.get("temperature_2m_min") or [None])[0]
        tmax = (daily.get("temperature_2m_max") or [None])[0]
        if tmin is not None and tmin <= 3:
            return SignalReading(
                source=self.name, label=f"Cold snap in {self.place}",
                affected_categories=["cold_remedy", "muscle_joint"], direction="up", magnitude=0.8,
                health_event=True,
                evidence=f"Forecast low {tmin:.0f} C in {self.place} — demand for cold remedies and warming muscle care rises.",
                fetched_at=fetched_at, configured=True, source_url=self._url())
        if tmax is not None and tmax >= 26:
            return SignalReading(
                source=self.name, label=f"Warm spell in {self.place}",
                affected_categories=["sunscreen", "foot_care"], direction="up", magnitude=0.6, health_event=False,
                evidence=f"Forecast high {tmax:.0f} C in {self.place} — sun-protection and foot-care demand rises.",
                fetched_at=fetched_at, configured=True, source_url=self._url())
        return SignalReading(
            source=self.name, label=f"Mild weather in {self.place}", affected_categories=[],
            direction="flat", magnitude=0.0, health_event=False,
            evidence="Mild forecast — no clear weather-driven demand shift.",
            fetched_at=fetched_at, configured=True, source_url=self._url())


class HolidayConnector:
    """Nager.Date public holidays -> a seasonal/gifting signal if one is imminent."""
    def __init__(self, country: str = "DE", window_days: int = 3):
        self.country, self.window_days = country, window_days
        self.name = "Nager.Date"

    def _url(self) -> str:
        year = datetime.now(timezone.utc).year
        return f"https://date.nager.at/api/v3/PublicHolidays/{year}/{self.country}"

    def fetch(self, *, _get=_http_get_json) -> SignalReading | None:
        try:
            data = _get(self._url(), timeout=4.0)
        except Exception:
            return SignalReading(
                source=self.name, label="Holiday calendar unavailable", affected_categories=[],
                direction="flat", evidence="Nager.Date unreachable; no seasonal signal.",
                fetched_at=_now(), configured=True, source_url=self._url())
        return self.parse(data, today=datetime.now(timezone.utc).date().isoformat(), fetched_at=_now())

    def parse(self, data: list, *, today: str, fetched_at: str) -> SignalReading:
        t = date.fromisoformat(today)
        for h in data or []:
            try:
                delta = (date.fromisoformat(h["date"]) - t).days
            except Exception:
                continue
            if 0 <= delta <= self.window_days:
                name = h.get("localName") or h.get("name") or "holiday"
                return SignalReading(
                    source=self.name, label=f"Upcoming holiday: {name}",
                    affected_categories=["cosmetic", "general"], direction="up", magnitude=0.4, health_event=False,
                    evidence=f"{name} in {delta} day(s) — a seasonal/gifting demand lift on gift-able lines.",
                    fetched_at=fetched_at, configured=True, source_url="https://date.nager.at")
        return SignalReading(
            source=self.name, label="No imminent holiday", affected_categories=[],
            direction="flat", magnitude=0.0, health_event=False,
            evidence="No public holiday within the window — no seasonal signal.",
            fetched_at=fetched_at, configured=True, source_url=self._url())


class SeededConnector:
    """Replays one committed snapshot dict as a SignalReading (synthetic but honest)."""
    def __init__(self, seed: dict):
        self.seed = seed
        self.name = seed.get("source", "seeded")

    def fetch(self, **_) -> SignalReading:
        s = self.seed
        return SignalReading(
            source=s["source"], label=s["label"], affected_categories=list(s["affected_categories"]),
            direction=s.get("direction", "flat"), magnitude=s.get("magnitude", 0.0),
            health_event=s.get("health_event", False), evidence=s.get("evidence", ""),
            fetched_at=_now(), configured=True, source_url=s.get("source_url"))


class UnconfiguredConnector:
    """A connector that is not wired up. Degrades honestly — never fabricates data."""
    def __init__(self, name: str, label: str):
        self.name, self.label = name, label

    def fetch(self, **_) -> SignalReading:
        return SignalReading(
            source=self.name, label=f"{self.label} (not configured)", affected_categories=[],
            direction="flat", magnitude=0.0, health_event=False,
            evidence="Connector not configured — no data fetched (firecrawl/API key absent).",
            fetched_at=_now(), configured=False)


def default_connectors(place: str = "Homburg", country: str = "DE") -> list:
    """The standard Dr. Theiss signal set: live weather + holidays, seeded rest."""
    return [
        WeatherConnector(place=place),
        HolidayConnector(country=country),
        SeededConnector(SEED_NEWS),
        SeededConnector(SEED_SUPPLY),
        SeededConnector(SEED_FOOTBALL),
        UnconfiguredConnector("firecrawl:competitors", "Competitor price scrape"),
    ]


def fetch_all(connectors: list, *, timeout: float = 6.0) -> list[SignalReading]:
    """Fetch every connector concurrently; drop any that raise. Never blocks forever."""
    out: list[SignalReading] = []
    with ThreadPoolExecutor(max_workers=max(1, len(connectors))) as ex:
        futures = [ex.submit(c.fetch) for c in connectors]
        for fut in futures:
            try:
                r = fut.result(timeout=timeout)
            except Exception:
                continue
            if r is not None:
                out.append(r)
    return out
