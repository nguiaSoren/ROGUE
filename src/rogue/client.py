"""The ROGUE SDK ``Client`` — the only thing most users touch.

    from rogue import Client
    client = Client(endpoint="https://api.company.com/v1", api_key="...")
    report = client.scan()
    print(report.summary())

Or against a known provider::

    client = Client(provider="openai")   # uses $OPENAI_API_KEY
    client.validate()

The Client holds exactly two things — ``self.adapter`` (how to reach the target) and ``self.config``
(what target). No attack logic, no orchestration, no benchmark internals; those live behind
:meth:`scan` / :meth:`validate` / :meth:`benchmark`. Internal ROGUE types (TargetPanel,
DeploymentConfig, BreachResult, AttackPrimitive, harvest, …) are never exposed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .adapters import AdapterConfig, registry
from .core import CanonicalMessage
from .core.errors import AdapterError, AuthenticationError
from .report import BenchmarkReport, ScanReport, ValidationResult
from .schemas import DeploymentConfig

# A sensible default model per provider (real panel models) when the user gives only ``provider=``.
_DEFAULT_MODELS: dict[str, str] = {
    "openai": "openai/gpt-5.4-nano",
    "anthropic": "anthropic/claude-haiku-4-5",
    "openrouter": "meta-llama/llama-3.1-8b-instruct",
    "gemini": "google/gemini-3.1-flash-lite",
    "groq": "groq/llama-3.1-8b-instant",
}


class Client:
    """Entry point to the ROGUE red-team SDK."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        *,
        system_prompt: str = "",
        tools: list[str] | None = None,
        forbidden_tools: list[str] | None = None,
        judge_model: str | None = None,
        _adapter_extra: dict[str, Any] | None = None,
        _judge: Any = None,
    ):
        """Point the client at a target.

        Pass an OpenAI-compatible ``endpoint`` (a company gateway / vLLM / proxy), **or** a known
        ``provider`` (``openai`` / ``anthropic`` / ``openrouter`` / ``gemini`` / ``groq``). ``model``
        is optional — defaults to the endpoint's default or a per-provider default. ``api_key`` falls
        back to the provider's standard env var. ``judge_model`` overrides the grading model (env
        ``JUDGE_MODEL`` otherwise).
        """
        if endpoint:
            base_url: str | None = endpoint
            target_model = model or "default"
            provider_slug = "custom"
        elif provider:
            base_url = None
            if model:
                target_model = model if "/" in model else f"{provider}/{model}"
            elif provider in _DEFAULT_MODELS:
                target_model = _DEFAULT_MODELS[provider]
            else:
                raise ValueError(
                    f"no default model for provider {provider!r}; pass model=... "
                    f"(known providers with defaults: {', '.join(sorted(_DEFAULT_MODELS))})"
                )
            provider_slug = provider
        else:
            raise ValueError("Client needs either endpoint=... or provider=...")

        self.config = DeploymentConfig(
            config_id="sdk-scan-0001",
            customer_id="sdk",
            name=base_url or target_model,
            target_model=target_model,
            system_prompt=system_prompt,
            declared_tools=tools or [],
            forbidden_tools=forbidden_tools or [],
            base_url=base_url,
        )
        # adapter_extra is threaded into every adapter (api_key, or an injected client for tests).
        self._adapter_extra: dict[str, Any] = dict(_adapter_extra or {})
        if api_key:
            self._adapter_extra.setdefault("api_key", api_key)
        self._judge_model = judge_model
        self._judge = _judge  # injected judge (tests); None → a real JudgeAgent is built per scan
        self.adapter = registry.create(
            provider_slug,
            AdapterConfig(model=target_model, base_url=base_url, api_key=api_key, extra=self._adapter_extra),
        )

    # --- operation #3: validate (cheap pre-flight) --------------------------------------------

    def validate(self) -> ValidationResult:
        """Check the target is reachable, authenticated, responds, and what modalities it supports.

        One tiny call — run this before spending on a full scan.
        """
        return asyncio.run(self._validate_async())

    async def _validate_async(self) -> ValidationResult:
        target = self.config.base_url or self.config.target_model
        reachable = authenticated = model_responds = False
        error: str | None = None
        supports_image = supports_audio = False
        try:
            caps = await self.adapter.capabilities()
            supports_image, supports_audio = caps.supports_image, caps.supports_audio
            try:
                await self.adapter.invoke([CanonicalMessage.user("Reply with the single word OK.")])
                reachable = authenticated = model_responds = True
            except AuthenticationError as e:
                reachable, error = True, str(e)  # reached the endpoint; credentials rejected
            except AdapterError as e:
                reachable = authenticated = True  # reached + authed (rate-limit / provider 5xx / etc)
                error = str(e)
            except Exception as e:  # network / DNS / timeout — couldn't reach it
                error = str(e)
        finally:
            await self.adapter.aclose()
        return ValidationResult(
            target=target,
            reachable=reachable,
            authenticated=authenticated,
            model_responds=model_responds,
            supports_image=supports_image,
            supports_audio=supports_audio,
            error=error,
        )

    # --- operation #1: scan (the one that matters) --------------------------------------------

    def scan(
        self,
        attacks: list[str] | None = None,
        max_tests: int = 100,
        budget: float | None = None,
        *,
        pack: str = "default",
        n_trials: int = 1,
        agent_exec: bool = True,
        agent_exec_seeds: int = 3,
        agent_exec_framing: str = "raw",
    ) -> ScanReport:
        """Run an attack pack against the target and return a :class:`ScanReport`.

        :param attacks: only run these attack families/names (e.g. ``["dan", "crescendo"]``).
        :param max_tests: cap on the number of attacks run.
        :param budget: stop once this many USD of target-call cost is spent.
        :param pack: which bundled pack to load (default ``"default"``).
        :param agent_exec: run the tool-execution stage when the config declares tools (auto,
            inert otherwise). Set ``False`` to skip it.
        :param agent_exec_seeds: trials per agentic primitive (for a stable rate).
        :param agent_exec_framing: ``"raw"`` (real harvested attack, default) or ``"amplified"``
            (upper-bound: adds an authoritative "important_instructions" wrapper).
        """
        from .packs import filter_attacks, load_pack
        from .scan import run_scan

        primitives = filter_attacks(load_pack(pack), attacks)[:max_tests]
        return asyncio.run(
            run_scan(
                self.config,
                primitives,
                n_trials=n_trials,
                budget=budget,
                adapter_extra=self._adapter_extra,
                judge=self._judge,
                judge_model=self._judge_model,
                agent_exec=agent_exec,
                agent_exec_seeds=agent_exec_seeds,
                agent_exec_framing=agent_exec_framing,
            )
        )

    # --- operation #2: benchmark (research-grade) ---------------------------------------------

    def benchmark(self, dataset: str = "advbench_100", max_goals: int = 25) -> BenchmarkReport:
        """Measure attack-success-rate against a standard dataset (AdvBench / JBB)."""
        from .benchmark import run_benchmark

        return asyncio.run(
            run_benchmark(
                self.config,
                dataset=dataset,
                max_goals=max_goals,
                adapter_extra=self._adapter_extra,
                judge_model=self._judge_model,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Client(target={self.config.base_url or self.config.target_model!r})"


__all__ = ["Client"]
