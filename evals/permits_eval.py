"""Headless accuracy check for the work-permit agent against the labelled sample set.

Run:  uv run python -m evals.permits_eval
"""
from __future__ import annotations

from core import config
from agents import permits


def main() -> None:
    samples = sorted(config.PATHS["permits"].glob("*.pdf"))
    if not samples:
        print("No samples found at", config.PATHS["permits"])
        return
    correct = 0
    for p in samples:
        expected = "VALID" if ("valid" in p.name and "invalid" not in p.name) else "INVALID"
        r = permits.validate_permit(p)
        got = "VALID" if r.decision == "VALID" else "INVALID"
        ok = got == expected
        correct += ok
        print(f"{'✅' if ok else '❌'} {p.name:35s} expected={expected:8s} agent={r.decision:12s} "
              f"valid_until={r.valid_until} conf={r.confidence}")
    print(f"\nAccuracy: {correct}/{len(samples)} = {100*correct/len(samples):.0f}%")


if __name__ == "__main__":
    main()
