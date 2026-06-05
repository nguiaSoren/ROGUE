"""ROGUE SDK quickstart — the headline flow, offline against MockTransport.

Run from the sdk/ directory (no API key, no network required):

    PYTHONPATH=src python3 examples/quickstart.py

Register a deployment -> run a scan -> read the risk summary -> list the top
findings -> export a Markdown report. This is exactly the flow a customer runs
against the Hosted API; here we point it at the in-memory MockTransport so it
works immediately, fully offline.
"""

import tempfile
from pathlib import Path

from rogue import Rogue, MockTransport


def main() -> None:
    # MockTransport serves the whole v1 contract in-memory; api_key can be anything.
    rogue = Rogue(api_key="demo", transport=MockTransport())

    deployment = rogue.register(
        name="Customer Support Agent",
        model="gpt-5",
        system_prompt="You are a helpful support agent.",
    )
    print("Registered:", deployment)

    # scan() blocks: it starts the server-side job, polls it, and returns the Report.
    report = rogue.scan(deployment)

    print()
    print(report.summary())
    print("risk:", report.risk_score, report.risk_level.value)

    print()
    print("Top findings:")
    for f in report.top_findings(5):
        print(f"  [{f.severity.value:<8}] {f.success_pct:>4}  {f.title}")

    out = Path(tempfile.gettempdir()) / "rogue_quickstart_report.md"
    report.export_markdown(out)
    print()
    print("Markdown report written to:", out)


if __name__ == "__main__":
    main()
