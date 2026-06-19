"""Probe the Featherless flagship-model shortlist — verify each actually SERVES (HTTP 200) before a
sweep, and write the verified list to ``scripts/sweep/featherless_models.json`` for the runner.

Being in the catalog is NOT enough: e.g. ``mistralai/Mistral-7B-Instruct-v0.3`` is listed +
``available_on_current_plan`` yet 400s on every call. So we send each candidate a minimal
``/chat/completions`` ("hi", max_tokens 8) and keep only the ones that return a real completion.

Run:
    uv run python scripts/sweep/probe_featherless_models.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

_FL = "https://api.featherless.ai/v1/chat/completions"
_KEY = os.environ.get("FEATHERLESS_API_KEY", "").strip()
_OUT = _ROOT / "scripts" / "sweep" / "featherless_models.json"

# ~22 recognizable flagships across families (over-provisioned to net ~18 that serve). The
# 2 huihui abliterations are the dramatic "uncensored breaks everything" entries — note one is the
# abliterated twin of meta-llama/Meta-Llama-3.1-8B-Instruct (same base, censored vs not).
CANDIDATES: list[tuple[str, str]] = [
    ("Llama", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
    ("Llama", "meta-llama/Llama-3.3-70B-Instruct"),
    ("Llama", "meta-llama/Meta-Llama-3.1-70B-Instruct"),
    ("Qwen", "Qwen/Qwen2.5-7B-Instruct"),
    ("Qwen", "Qwen/Qwen2.5-72B-Instruct"),
    ("Qwen", "Qwen/QwQ-32B"),
    ("Qwen", "Qwen/Qwen3-32B"),
    ("Qwen", "Qwen/Qwen3-235B-A22B"),
    ("Mistral", "mistralai/Mistral-7B-Instruct-v0.2"),
    ("Mistral", "mistralai/Mistral-Nemo-Instruct-2407"),
    ("Mistral", "mistralai/Mistral-Small-24B-Instruct-2501"),
    ("DeepSeek", "deepseek-ai/DeepSeek-V3.1"),
    ("DeepSeek", "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"),
    ("Gemma", "google/gemma-2-9b-it"),
    ("Gemma", "google/gemma-2-27b-it"),
    ("Gemma", "google/gemma-3-27b-it"),
    ("Phi", "microsoft/phi-4"),
    ("MiniMax", "MiniMaxAI/MiniMax-M2"),
    ("Kimi", "moonshotai/Kimi-K2-Instruct"),
    ("GLM", "zai-org/GLM-4-9B-0414"),
    ("Uncensored", "huihui-ai/Meta-Llama-3.1-8B-Instruct-abliterated"),
    ("Uncensored", "huihui-ai/Qwen2.5-7B-Instruct-abliterated"),
]


def probe(item: tuple[str, str]) -> dict:
    family, model = item
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
    ).encode()
    t0 = time.time()
    # 403/429/503 from Featherless is usually a transient throttle / cold-load (not a per-model
    # verdict) — back off and retry patiently so it doesn't mislabel a good model as broken. A real
    # bad model 400s instantly (no retry helps). 400/404 are treated as terminal.
    last = "no-attempt"
    for attempt in range(6):
        req = urllib.request.Request(
            _FL, data=body,
            # A real User-Agent is REQUIRED: Featherless's edge 403s the default "Python-urllib" UA
            # (bot protection). Any normal/honest UA passes. (scan_endpoint uses the OpenAI SDK/httpx,
            # which already sends an httpx UA, so the sweep itself was never affected — only this raw
            # urllib probe was.)
            headers={
                "Authorization": f"Bearer {_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "ROGUE-redteam-probe/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310 - trusted endpoint
                payload = json.loads(r.read())
            has = payload.get("choices", [{}])[0].get("message", {}).get("content") is not None
            return {"family": family, "model": model, "ok": bool(has), "code": 200, "secs": time.time() - t0}
        except urllib.error.HTTPError as e:
            last = e.code
            if e.code in (403, 429, 503) and attempt < 5:
                time.sleep(5 * (attempt + 1))  # 5,10,15,20,25s — patient on the rate-throttle
                continue
            return {"family": family, "model": model, "ok": False, "code": e.code, "secs": time.time() - t0}
        except Exception as e:
            last = str(e)[:40]
            if attempt < 5:
                time.sleep(5 * (attempt + 1))
                continue
            break
    return {"family": family, "model": model, "ok": False, "code": last, "secs": time.time() - t0}


def main() -> None:
    if not _KEY:
        raise SystemExit("FEATHERLESS_API_KEY missing in .env")
    # Merge with any already-verified list so re-runs only re-probe the unconfirmed models (and don't
    # waste calls / rate budget re-hitting known-good ones). The key has a REQUEST-RATE limit (429),
    # not just concurrency — so probe SEQUENTIALLY with a gap; bursts trip the throttle.
    already = {v["model"]: v for v in json.loads(_OUT.read_text())} if _OUT.exists() else {}
    todo = [c for c in CANDIDATES if c[1] not in already]
    print(f"{len(already)} already verified; probing {len(todo)} unconfirmed, sequentially…\n")

    verified: list[dict] = list(already.values())
    for item in todo:
        r = probe(item)
        mark = "✓ 200" if r["ok"] else f"✗ {r['code']}"
        print(f"  {mark:<10} {r['secs']:>5.1f}s  [{r['family']:<10}] {r['model']}", flush=True)
        if r["ok"]:
            verified.append({"family": r["family"], "model": r["model"]})
        time.sleep(2)  # gentle inter-probe gap to stay under the request-rate limit

    verified.sort(key=lambda v: (v["family"], v["model"]))
    _OUT.write_text(json.dumps(verified, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(verified)}/{len(CANDIDATES)} serve → wrote {_OUT}")
    fams = sorted({v["family"] for v in verified})
    print(f"families covered: {', '.join(fams)}")


if __name__ == "__main__":
    main()
