"""Headless accuracy check for the invoice triage agent vs 00_manifest.csv.

Compares the agent's extracted vendor & total against the ground-truth manifest, and
prints the routed department for each invoice.

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

    vendor_hits = total_hits = 0
    for p in samples:
        r = invoices.triage_invoice(p)
        truth = man_by_file.get(p.name, {})
        exp_vendor = truth.get("vendor", "") if len(truth) else ""
        exp_total = truth.get("total", "") if len(truth) else ""

        gv, ev = _norm(r.fields.vendor), _norm(exp_vendor)
        vendor_ok = bool(gv) and bool(ev) and (gv in ev or ev in gv)
        gt, et = _digits(r.fields.total), _digits(exp_total)
        total_ok = bool(gt) and gt == et

        vendor_hits += vendor_ok
        total_hits += total_ok
        print(f"{'✅' if vendor_ok else '❌'}vend {'✅' if total_ok else '❌'}tot  "
              f"{p.name:34s} got={r.fields.vendor!s:24s} total={r.fields.total!s:12s} "
              f"-> {r.department}")

    n = len(samples)
    print(f"\nVendor accuracy: {vendor_hits}/{n} = {100*vendor_hits/n:.0f}%")
    print(f"Total  accuracy: {total_hits}/{n} = {100*total_hits/n:.0f}%")


if __name__ == "__main__":
    main()
