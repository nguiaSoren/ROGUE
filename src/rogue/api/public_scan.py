"""Public, DB-free ``POST /api/public-scan`` — the keyless "scan → breach card" hero endpoint.

A web visitor hands us an OpenAI-compatible ``endpoint`` + ``model`` + their TARGET ``api_key`` and we
run a tiny slice of ROGUE's corpus against it, grade the responses, and hand back a shareable breach
card (PNG + SVG) plus a one-line summary. Our side spends ~$0: the visitor's target key pays for the
target calls, and grading is either the keyless heuristic judge (no key) or — when the visitor also
supplies a ``judge_key`` — ROGUE's calibrated v3 LLM judge billed to THAT key. Nothing is persisted.

This router is self-contained and mounted by the API orchestrator (it does not edit ``main.py``).

Security posture (this is a security product — the gate matters):
  * **SSRF.** ``endpoint`` is validated by :mod:`rogue.api._ssrf` before any request: http/https only,
    hostname resolved, EVERY resolved IP must be globally-routable public unicast. Loopback / private /
    link-local (incl. 169.254.169.254 + other cloud-metadata IPs) / unique-local / reserved /
    multicast / unspecified are all blocked → 400. The scan's HTTP client (OpenAI SDK over httpx) does
    NOT follow redirects by default, so a 3xx from the validated endpoint into a blocked IP is surfaced
    as a request error, not chased — we rely on that default and never re-enable redirects on this path.
  * **Keys.** ``api_key`` / ``judge_key`` are used in-memory only — never persisted, never logged, and
    scrubbed from any error ``detail`` (we raise generic messages, never echoing request content).
  * **Caps.** ≤6 primitives, ≤2 trials, regardless of ``pack`` (cost/latency/abuse). Per-IP rate limit
    (``PUBLIC_SCAN_RATE``, default 5/hour) + a module-level concurrency semaphore. 90s wall-clock cap.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from rogue.api._ssrf import SsrfBlocked, validate_public_endpoint

_log = logging.getLogger("rogue.api.public_scan")

# --- non-negotiable caps (cost / latency / abuse) ------------------------------------------------
MAX_PRIMITIVES = 6  # hard cap on attacks fired, even for "aggressive"
MAX_TRIALS = 2  # hard cap on trials per primitive
WALL_TIME_S = 90.0  # hard wall-clock cap on the whole scan → 504 on overrun

# Per-IP rate limit (env-overridable) + bounded concurrency.
PUBLIC_SCAN_RATE = os.environ.get("PUBLIC_SCAN_RATE", "5/hour")
_MAX_CONCURRENT = int(os.environ.get("PUBLIC_SCAN_MAX_CONCURRENT", "2"))
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

router = APIRouter(tags=["public"])


class PublicScanRequest(BaseModel):
    """Visitor-supplied scan parameters. ``api_key`` / ``judge_key`` are in-memory only."""

    endpoint: str = Field(..., min_length=1, description="OpenAI-compatible base URL")
    model: str = Field(..., min_length=1, description="model id the endpoint serves")
    api_key: str = Field(..., min_length=1, description="visitor's TARGET key (never stored/logged)")
    judge_key: str | None = Field(None, description="optional: enables the calibrated v3 LLM judge")
    judge_model: str | None = Field(None, description="optional judge model id (provider/model)")
    system_prompt: str | None = Field(None, description="optional system prompt for the target")
    pack: str = Field("default", description="'default' | 'aggressive'")


class PublicScanSummary(BaseModel):
    model_label: str
    breached: int
    trials: int
    rate: float
    judge: str  # "keyless" | "calibrated-v3"


class PublicScanResponse(BaseModel):
    card_png_base64: str
    card_svg: str
    summary: PublicScanSummary


def _build_calibrated_judge(judge_key: str, judge_model: str | None) -> Any:
    """Build a calibrated v3 :class:`JudgeAgent` whose provider client uses the VISITOR's key.

    The key is injected directly into the lazily-built provider client rather than the process
    environment — so concurrent public scans never race on a shared env var and the key stays
    request-scoped. The model prefix (``anthropic/`` | ``openai/`` | ``openrouter/``) picks which
    client to pre-seed; default is the v3 harm judge model.
    """
    from rogue.reproduce.judge import _MAX_RETRIES, _REQUEST_TIMEOUT_S, JudgeAgent

    judge = JudgeAgent(model=judge_model) if judge_model else JudgeAgent()
    model = judge.model

    if model.startswith("anthropic/"):
        from anthropic import AsyncAnthropic

        judge._anthropic_client = AsyncAnthropic(
            api_key=judge_key, timeout=_REQUEST_TIMEOUT_S, max_retries=_MAX_RETRIES
        )
    elif model.startswith("openai/"):
        from openai import AsyncOpenAI

        judge._openai_client = AsyncOpenAI(
            api_key=judge_key, timeout=_REQUEST_TIMEOUT_S, max_retries=_MAX_RETRIES
        )
    elif model.startswith("openrouter/"):
        from openai import AsyncOpenAI

        judge._openrouter_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=judge_key,
            timeout=_REQUEST_TIMEOUT_S,
            max_retries=_MAX_RETRIES,
        )
    return judge


def _card_from_report(report: Any, model_label: str, tier: str, measured_date: str) -> dict:
    """Mirror the ``rogue scan`` / ``rogue try`` card dict from an :class:`EndpointScanReport`.

    ``measured_date`` is passed in (the route supplies today's date as a literal string) so this stays
    pure. ``top_attack`` is the family of the first breached finding; ``families`` is every family the
    scan covered (``render_breach_card`` only needs the distinct count).
    """
    findings = list(getattr(report, "findings", []) or [])
    families = [f.family for f in findings if getattr(f, "family", None)]
    top = next((f.family for f in findings if getattr(f, "breached", False)), None)
    return {
        "model_label": model_label,
        "breach_rate": float(getattr(report, "breach_rate", 0.0) or 0.0),
        "trials": int(getattr(report, "n_primitives", 0) or 0),
        "breaches": int(getattr(report, "n_breached", 0) or 0),
        "top_attack": top or "",
        "families": families,
        "verdict_counts": {},
        "tier": tier,
        "generated_at": measured_date,
    }


async def public_scan(request: Request, body: PublicScanRequest) -> PublicScanResponse:
    """Run a capped, DB-free scan and return a shareable breach card. See module docstring for policy."""
    # 1) SSRF gate — validate the endpoint BEFORE any outbound request. 400 on block (generic detail).
    try:
        validate_public_endpoint(body.endpoint)
    except SsrfBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if body.pack not in ("default", "aggressive"):
        raise HTTPException(status_code=400, detail="pack must be 'default' or 'aggressive'")

    # 2) Corpus — load the pack, HARD-CAP primitives (≤6) and trials (≤2) regardless of pack.
    from rogue.packs import load_pack

    try:
        primitives = load_pack(body.pack)[:MAX_PRIMITIVES]
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="unknown attack pack") from None
    if not primitives:
        raise HTTPException(status_code=400, detail="attack pack is empty")

    # 3) Judge selection — keyless heuristic by default; calibrated v3 (visitor key) when judge_key set.
    if body.judge_key:
        judge = _build_calibrated_judge(body.judge_key, body.judge_model)
        judge_label = "calibrated-v3"
    else:
        from rogue.reproduce.heuristic_judge import HeuristicJudge

        judge = HeuristicJudge()
        judge_label = "keyless"

    # 4) Bounded concurrency — fail fast (429) rather than queueing if the box is already busy.
    #    A short acquire timeout means a saturated box rejects immediately instead of piling up.
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="too many concurrent scans; retry shortly") from None

    try:
        from rogue.reproduce.endpoint_scan import scan_endpoint

        # 5) The scan — DB-free (persist=False, database_url=None), wall-clock capped.
        try:
            report = await asyncio.wait_for(
                scan_endpoint(
                    body.endpoint,
                    body.model,
                    primitives,
                    api_key=body.api_key,
                    system_prompt=body.system_prompt or "",
                    n_trials=MAX_TRIALS,
                    judge=judge,
                    persist=False,
                    database_url=None,
                ),
                timeout=WALL_TIME_S,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="scan timed out") from None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — map any target/transport failure to 502, key-free
            _log.warning("public scan target unreachable: %s", type(exc).__name__)
            raise HTTPException(status_code=502, detail="target endpoint unreachable") from None
    finally:
        _semaphore.release()

    # 6) Render the card into a throwaway temp dir → base64 PNG + SVG text, then clean up.
    from rogue.report_card import render_breach_card

    measured_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    card = _card_from_report(report, body.model, "calibrated" if body.judge_key else "quick", measured_date)
    try:
        with tempfile.TemporaryDirectory(prefix="rogue-public-scan-") as tmp:
            paths = render_breach_card(card, Path(tmp))
            svg_text = Path(paths["svg"]).read_text(encoding="utf-8")
            png_b64 = ""
            png_path = paths.get("png")
            if png_path is not None:
                png_b64 = base64.b64encode(Path(png_path).read_bytes()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — a render failure must not leak internals
        _log.warning("public scan card render failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="card render failed") from None

    return PublicScanResponse(
        card_png_base64=png_b64,
        card_svg=svg_text,
        summary=PublicScanSummary(
            model_label=body.model,
            breached=int(getattr(report, "n_breached", 0) or 0),
            trials=int(getattr(report, "n_primitives", 0) or 0),
            rate=float(getattr(report, "breach_rate", 0.0) or 0.0),
            judge=judge_label,
        ),
    )


# --- rate limiting + route registration -----------------------------------------------------------
# Reuse the app's SlowAPI limiter (per-IP). When slowapi is absent the limiter is None and the route
# is registered undecorated (degrade gracefully — same posture as the rest of the API). The decorator
# MUST wrap the handler BEFORE it is added to the router, so the registered endpoint carries the
# limit. SlowAPI's per-route limit relies on the ``request: Request`` parameter (present above).
try:
    from rogue.api.observability import get_limiter

    _limiter = get_limiter()
except Exception:  # pragma: no cover - never let limiter wiring break import
    _limiter = None

_handler = public_scan
if _limiter is not None:  # pragma: no cover - exercised only with slowapi installed
    _handler = _limiter.limit(PUBLIC_SCAN_RATE)(_handler)

router.post("/api/public-scan", response_model=PublicScanResponse)(_handler)


__all__ = ["router", "PublicScanRequest", "PublicScanResponse", "PublicScanSummary"]
