"""Build the synthetic 3-invoices-in-one PDF for the P1 demo wow beat.

The manifest ships only single-invoice samples, so we concatenate three different
vendors/formats into ONE multi-page PDF. Dropping this single file on the Globus page
(or POSTing it to /agents/invoices) exercises the multi-invoice split end to end:
three invoices come out, each routed independently, with grounded fields + confidence.

Run:  uv run python -m evals.invoices_demo
Output: data/demo/march_invoices_3in1.pdf  (data/ is gitignored — regenerate on demand)
"""
from __future__ import annotations

from pypdf import PdfWriter

from core import config

# Three distinct vendors / categories / languages so routing visibly differs.
SOURCES = [
    "01_stadtwerke_gas_de.pdf",      # Gas (DE)         -> Facilities
    "02_microsoft_licenses_en.pdf",  # Software (EN)    -> IT
    "09_telekom_internet_de.pdf",    # Internet (DE)    -> IT
]


def build() -> str:
    src_dir = config.PATHS["invoices"]
    out_dir = config.DATA_OUT / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "march_invoices_3in1.pdf"

    writer = PdfWriter()
    used = []
    for name in SOURCES:
        p = src_dir / name
        if not p.exists():
            print(f"  skip (missing): {name}")
            continue
        writer.append(str(p))
        used.append(name)
    with open(out, "wb") as fh:
        writer.write(fh)

    print(f"Wrote {out} — {len(used)} invoices concatenated:")
    for n in used:
        print(f"  · {n}")
    print("\nDrop this on the Globus page, or:")
    print(f'  curl -F "email_body=March invoices attached." '
          f'-F "files=@{out}" http://localhost:8000/agents/invoices')
    return str(out)


if __name__ == "__main__":
    build()
