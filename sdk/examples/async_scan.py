"""ROGUE SDK async-scan polling — offline against MockTransport.

Run from the sdk/ directory (no API key, no network required):

    PYTHONPATH=src python3 examples/async_scan.py

A real scan is a server-side job that takes minutes. scan_async() returns a
Scan job handle immediately; you then poll it (refresh / status / progress) or
just block with job.wait(). Here MockTransport(complete_after_polls=3) keeps the
job 'running' for a few polls so the polling loop is exercised deterministically.
"""

import time

from rogue import Rogue, MockTransport


def main() -> None:
    # complete_after_polls=3: the mock scan stays 'running' until the 3rd status poll.
    rogue = Rogue(api_key="demo", transport=MockTransport(complete_after_polls=3))

    deployment = rogue.register(
        name="Customer Support Agent",
        model="mistral-small",
        system_prompt="You are a helpful support agent.",
    )

    job = rogue.scan_async(deployment)
    print("Started:", job)

    # Manual polling loop. Each refresh() re-fetches state from the (mock) API; the
    # mock advances the job one step per poll, so no real sleep is needed here.
    while not job.done:
        job.refresh()
        print(f"  status={job.status.value:<10} progress={round(job.progress * 100)}%")
        time.sleep(0)  # a real deployment would sleep poll_interval seconds here

    # Simpler equivalent (blocks, polls, raises on failure/timeout):
    #     job.wait(poll_interval=0)

    report = job.report()
    print()
    print("Done:", job.status.value)
    print(report.summary())
    print("risk:", report.risk_score, report.risk_level.value)


if __name__ == "__main__":
    main()
