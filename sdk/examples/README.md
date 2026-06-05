# ROGUE SDK examples

These scripts demonstrate the full customer flow — register a deployment, run a scan, read the risk report, and register provider credentials. Every example runs against the in-memory `MockTransport`, so they need no API key and no network: they are fully offline and deterministic, and double as the SDK's smoke test.

Run each from the `sdk/` directory:

```sh
PYTHONPATH=src python3 examples/quickstart.py   # register -> scan -> summary -> top findings -> export Markdown
PYTHONPATH=src python3 examples/async_scan.py   # scan_async -> poll status/progress -> report
PYTHONPATH=src python3 examples/providers.py    # register_openai/anthropic/vertex/custom -> list providers
```

To point an example at the live Hosted API instead of the mock, drop the `transport=MockTransport()` argument and pass a real key (`Rogue(api_key="rk_live_...")`) or set `ROGUE_API_KEY`.
