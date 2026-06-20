"""Headless accuracy check for the invoice triage agent vs 00_manifest.csv.

Grades the agent's extracted vendor / total / currency / VAT-rate against the
ground-truth manifest, and prints the routed department for each invoice.

Run:  uv run python -m evals.invoices_eval
"""
from __future__ import annotations

import pandas as pd

from core import config
from agents import invoices


def _norm(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _digits(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _currency(s) -> str:
    """Normalize a currency to an ISO-ish code: € -> EUR, $ -> USD, £ -> GBP."""
    t = str(s or "").upper()
    if "EUR" in t or "€" in t:
        return "EUR"
    if "USD" in t or "$" in t:
        return "USD"
    if "GBP" in t or "£" in t:
        return "GBP"
    return _norm(t)[:3]


def _sample_files():
    d = config.PATHS["invoices"]
    files = []
    for pat in ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.docx"):
        files.extend(d.glob(pat))
    return sorted(f for f in files if not f.name.startswith("00_manifest"))


def main() -> None:
    samples = _sample_files()
    if not samples:
        print("No invoices found at", config.PATHS["invoices"])
        return

    manifest_path = config.PATHS["invoices"] / "00_manifest.csv"
    man = pd.read_csv(manifest_path) if manifest_path.exists() else pd.DataFrame()
    man_by_file = {str(row["file"]): row for _, row in man.iterrows()}

    vendor_hits = total_hits = currency_hits = vat_hits = 0
    for p in samples:
        r = invoices.triage_invoice(p)
        truth = man_by_file.get(p.name, {})
        exp_vendor = truth.get("vendor", "") if len(truth) else ""
        exp_total = truth.get("total", "") if len(truth) else ""
        exp_currency = truth.get("currency", "") if len(truth) else ""
        exp_vat = truth.get("vat_rate", "") if len(truth) else ""

        gv, ev = _norm(r.fields.vendor), _norm(exp_vendor)
        vendor_ok = bool(gv) and bool(ev) and (gv in ev or ev in gv)
        gt, et = _digits(r.fields.total), _digits(exp_total)
        total_ok = bool(gt) and gt == et
        currency_ok = bool(exp_currency) and _currency(r.fields.currency) == _currency(exp_currency)
        gvat, evat = _digits(r.fields.vat_rate), _digits(exp_vat)
        vat_ok = bool(evat) and gvat == evat

        vendor_hits += vendor_ok
        total_hits += total_ok
        currency_hits += currency_ok
        vat_hits += vat_ok
        print(f"{'✅' if vendor_ok else '❌'}vend {'✅' if total_ok else '❌'}tot "
              f"{'✅' if currency_ok else '❌'}cur {'✅' if vat_ok else '❌'}vat  "
              f"{p.name:34s} got={r.fields.vendor!s:22s} {r.fields.total!s:11s} "
              f"{r.fields.currency!s:4s} {r.fields.vat_rate!s:5s} -> {r.department}")

    n = len(samples)
    print(f"\nVendor   accuracy: {vendor_hits}/{n} = {100*vendor_hits/n:.0f}%")
    print(f"Total    accuracy: {total_hits}/{n} = {100*total_hits/n:.0f}%")
    print(f"Currency accuracy: {currency_hits}/{n} = {100*currency_hits/n:.0f}%")
    print(f"VAT-rate accuracy: {vat_hits}/{n} = {100*vat_hits/n:.0f}%")


if __name__ == "__main__":
    main()
