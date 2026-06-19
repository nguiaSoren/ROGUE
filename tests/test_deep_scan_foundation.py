"""Foundation tests for the ``--deep`` scan: true multi-turn, visible modality skips, persona-wrap.

These pin the three correctness fixes the deep-scan foundation introduces, all OFFLINE via a
deterministic recording adapter / the project ``MockAdapter`` (no network, no API keys, no spend):

  * ``TargetPanel.run_conversation`` drives a REAL back-and-forth — N sequential ``invoke`` calls for
    an N-user-turn render, with each model reply interleaved as an assistant turn before the next
    user turn — and returns the FINAL reply, NOT one stacked invoke.
  * A modality skip (image/audio attack vs an incapable target) is REPORTED as a finding (n_trials=0,
    a "skipped: …" marker) by ``run_scan`` / ``scan_endpoint``, never silently dropped to zero rows.
  * ``--deep`` (``deep=True``) applies persona-wrap to each primitive before dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.core import CanonicalMessage, MessageRole
from rogue.core.errors import ContentPolicyError
from rogue.core.invocation import InvocationResult, StopReason, UsageMetrics
from rogue.core.content_blocks import TextBlock
from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.target_panel import ModelResponse, TargetPanel
from rogue.schemas import AttackPrimitive, AttackVector, demo_deployment_configs

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------------- #
# A recording adapter: captures every invoke's message list + returns turn-tagged replies.
# --------------------------------------------------------------------------- #


class _RecordingAdapter:
    """Records the canonical message list passed to each ``invoke`` and replies deterministically.

    Reply text for invoke #k (1-based) is ``"reply-{k}"`` so a test can assert which reply came back
    last AND that earlier replies were fed back in as assistant turns. Optionally raises on a given
    invoke number to exercise the mid-conversation error path.
    """

    def __init__(self, *, raise_on: int | None = None, exc: Exception | None = None) -> None:
        self.calls: list[list[CanonicalMessage]] = []
        self._raise_on = raise_on
        self._exc = exc

    async def invoke(self, messages, *, temperature: float = 0.7, **kwargs) -> InvocationResult:
        # Snapshot role + content blocks (NOT just text) so later mutation of `history` can't rewrite
        # what we saw AND so an attached ImageBlock/AudioBlock is preserved for assertions.
        self.calls.append(
            [CanonicalMessage(role=m.role, content=list(m.content)) for m in messages]
        )
        n = len(self.calls)
        if self._raise_on is not None and n == self._raise_on:
            raise self._exc or ContentPolicyError("blocked", status_code=400)
        return InvocationResult(
            content=[TextBlock(text=f"reply-{n}")],
            usage=UsageMetrics.from_io(3, 2, estimated_cost_usd=0.001),
            stop_reason=StopReason.COMPLETE,
            latency_ms=5,
        )

    async def aclose(self) -> None:
        return None


def _config():
    return next(c for c in demo_deployment_configs() if c.target_model == "openai/gpt-5.4-nano")


def _multi_turn_rendered(turns: list[str]) -> RenderedAttack:
    return RenderedAttack(
        messages=[{"role": "user", "content": t} for t in turns],
        is_multi_turn=True,
        resolved_slots={},
        primitive_id="prim_mt",
        deployment_config_id="dc_test",
    )


# --------------------------------------------------------------------------- #
# 1. True multi-turn back-and-forth
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_conversation_does_n_sequential_invokes_with_interleaved_replies(monkeypatch):
    """3 user turns ⇒ 3 sequential invokes; each model reply is fed back as an assistant turn."""
    adapter = _RecordingAdapter()
    panel = TargetPanel()
    monkeypatch.setattr(panel, "_adapter_for", lambda *a, **k: adapter)

    rendered = _multi_turn_rendered(["turn one", "turn two", "turn three"])
    responses = await panel.run_conversation(rendered, _config(), n_trials=1)

    # Exactly 3 invokes (one per user turn) — NOT a single stacked invoke.
    assert len(adapter.calls) == 3

    # Invoke 1 saw only [user1].
    roles1 = [(m.role, m.text) for m in adapter.calls[0]]
    assert roles1 == [(MessageRole.USER, "turn one")]

    # Invoke 2 saw [user1, assistant(reply-1), user2] — the model's first reply is interleaved.
    roles2 = [(m.role, m.text) for m in adapter.calls[1]]
    assert roles2 == [
        (MessageRole.USER, "turn one"),
        (MessageRole.ASSISTANT, "reply-1"),
        (MessageRole.USER, "turn two"),
    ]

    # Invoke 3 saw the full interleaved history up to the final user turn.
    roles3 = [(m.role, m.text) for m in adapter.calls[2]]
    assert roles3 == [
        (MessageRole.USER, "turn one"),
        (MessageRole.ASSISTANT, "reply-1"),
        (MessageRole.USER, "turn two"),
        (MessageRole.ASSISTANT, "reply-2"),
        (MessageRole.USER, "turn three"),
    ]

    # Exactly one ModelResponse, carrying the FINAL reply; cost/tokens summed over all 3 legs.
    assert len(responses) == 1
    r = responses[0]
    assert isinstance(r, ModelResponse)
    assert r.error is None
    assert r.content == "reply-3"  # the final reply, what the judge grades
    assert r.tokens_in == 9 and r.tokens_out == 6  # 3 legs × (3 in, 2 out)
    assert r.cost_usd == pytest.approx(0.003)  # 3 × 0.001


@pytest.mark.asyncio
async def test_run_conversation_fans_out_trials(monkeypatch):
    """n_trials independent conversations, each returning the final reply, sorted by trial_index."""
    panel = TargetPanel()
    # Each trial gets its own adapter so per-trial call counts stay isolated.
    adapters = [_RecordingAdapter() for _ in range(3)]
    it = iter(adapters)
    monkeypatch.setattr(panel, "_adapter_for", lambda *a, **k: next(it))

    rendered = _multi_turn_rendered(["a", "b"])
    responses = await panel.run_conversation(rendered, _config(), n_trials=3)

    assert [r.trial_index for r in responses] == [0, 1, 2]
    assert all(r.content == "reply-2" for r in responses)  # 2 turns → final reply is reply-2
    assert all(len(a.calls) == 2 for a in adapters)  # each trial did 2 sequential invokes


@pytest.mark.asyncio
async def test_run_conversation_stops_at_mid_conversation_block(monkeypatch):
    """A content-policy block on turn 2 stops the exchange and returns the legacy error tag."""
    adapter = _RecordingAdapter(raise_on=2, exc=ContentPolicyError("nope", status_code=400))
    panel = TargetPanel()
    monkeypatch.setattr(panel, "_adapter_for", lambda *a, **k: adapter)

    rendered = _multi_turn_rendered(["soft opener", "the real ask", "never reached"])
    responses = await panel.run_conversation(rendered, _config(), n_trials=1)

    assert len(adapter.calls) == 2  # stopped after the blocked second turn — no third invoke
    r = responses[0]
    assert r.content == ""
    assert r.error is not None and r.error.startswith("content_policy_or_bad_request")


@pytest.mark.asyncio
async def test_run_conversation_attaches_media_to_final_user_turn(monkeypatch):
    """An out-of-band image rides the LAST user turn of the conversation (multimodal multi-turn)."""
    from rogue.core import ImageBlock

    adapter = _RecordingAdapter()
    panel = TargetPanel()
    monkeypatch.setattr(panel, "_adapter_for", lambda *a, **k: adapter)
    # Drive the real builder (don't stub it) so we exercise media attachment in the conversation path.
    rendered = RenderedAttack(
        messages=[{"role": "user", "content": "turn one"}, {"role": "user", "content": "turn two"}],
        is_multi_turn=True,
        resolved_slots={},
        primitive_id="prim_mt_img",
        deployment_config_id="dc_test",
        image_b64=_TINY_PNG_B64,
    )
    # claude-haiku is vision-capable so it isn't skipped.
    cfg = next(c for c in demo_deployment_configs() if c.target_model == "anthropic/claude-haiku-4-5")
    await panel.run_conversation(rendered, cfg, n_trials=1)

    # The final invoke's last user turn carries the ImageBlock; the first invoke's turn does not.
    first_call_blocks = [type(b) for m in adapter.calls[0] for b in m.content]
    assert ImageBlock not in first_call_blocks
    last_user = [m for m in adapter.calls[1] if m.role == MessageRole.USER][-1]
    assert any(isinstance(b, ImageBlock) for b in last_user.content)


def test_user_turn_count_counts_only_user_turns():
    panel = TargetPanel()
    rendered = RenderedAttack(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "fabricated"},
            {"role": "user", "content": "u2"},
        ],
        is_multi_turn=True,
        resolved_slots={},
        primitive_id="p",
        deployment_config_id="dc",
    )
    assert panel.user_turn_count(rendered) == 2


# --------------------------------------------------------------------------- #
# 2. Multi-turn is the DEFAULT for multi_turn_sequence primitives (run_scan routes it there)
# --------------------------------------------------------------------------- #


class _CountingPanel:
    """A fake panel that records which dispatch method each primitive took."""

    def __init__(self) -> None:
        self.run_attack_calls = 0
        self.run_conversation_calls = 0

    @staticmethod
    def modality_skip_reason(rendered, config):
        return None

    @staticmethod
    def user_turn_count(rendered):
        return sum(1 for m in rendered.messages if m.get("role") == "user")

    async def run_attack(self, rendered, config, temperature=0.7, n_trials=1):
        self.run_attack_calls += 1
        return [_ok_response()]

    async def run_conversation(self, rendered, config, temperature=0.7, n_trials=1):
        self.run_conversation_calls += 1
        return [_ok_response()]

    async def aclose(self):
        return None


def _ok_response() -> ModelResponse:
    return ModelResponse(
        content="ok", latency_ms=1, tokens_in=1, tokens_out=1, cost_usd=0.0,
        error=None, trial_index=0, temperature=0.7,
    )


class _NeverBreachJudge:
    async def judge(self, rendered, content, primitive):
        from rogue.schemas.breach_result import JudgeVerdict

        class _R:
            verdict = JudgeVerdict.REFUSED

        return _R()


def _multi_turn_primitive() -> AttackPrimitive:
    data = json.loads((FIXTURES_DIR / "01_multilingual_african_languages.json").read_text("utf-8"))
    data["vector"] = "user_multi_turn"
    data["requires_multi_turn"] = True
    data["multi_turn_sequence"] = ["soft opener", "the escalation", "the payload"]
    data.pop("slot_requirements", None)
    data["requires_multimodal"] = False
    return AttackPrimitive.model_validate(data)


def _single_turn_primitive() -> AttackPrimitive:
    data = json.loads((FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text("utf-8"))
    data["vector"] = "user_turn"
    data["requires_multi_turn"] = False
    data["multi_turn_sequence"] = None
    data["requires_multimodal"] = False
    return AttackPrimitive.model_validate(data)


@pytest.mark.asyncio
async def test_run_scan_routes_multi_turn_to_conversation_driver():
    from rogue.scan import run_scan

    panel = _CountingPanel()
    await run_scan(
        _config(), [_multi_turn_primitive()], n_trials=1, panel=panel, judge=_NeverBreachJudge()
    )
    assert panel.run_conversation_calls == 1
    assert panel.run_attack_calls == 0  # multi-turn never used the stacked single-invoke path


@pytest.mark.asyncio
async def test_run_scan_keeps_single_turn_on_run_attack():
    from rogue.scan import run_scan

    panel = _CountingPanel()
    await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1, panel=panel, judge=_NeverBreachJudge()
    )
    assert panel.run_attack_calls == 1
    assert panel.run_conversation_calls == 0


# --------------------------------------------------------------------------- #
# 3. Modality skip is REPORTED, not dropped
# --------------------------------------------------------------------------- #


def _multimodal_image_primitive() -> AttackPrimitive:
    data = json.loads((FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text("utf-8"))
    data["vector"] = AttackVector.MULTIMODAL_IMAGE.value
    data["family"] = "language_switching"  # unmapped → plain typographic render
    data["secondary_families"] = []
    data["requires_multimodal"] = True
    return AttackPrimitive.model_validate(data)


@pytest.mark.asyncio
async def test_run_scan_reports_modality_skip_as_finding():
    """An image attack vs text-only Llama is a 'skipped' finding, not zero rows."""
    from rogue.scan import run_scan

    llama = next(
        c for c in demo_deployment_configs() if c.target_model == "meta-llama/llama-3.1-8b-instruct"
    )
    report = await run_scan(
        llama, [_multimodal_image_primitive()], n_trials=3, judge=_NeverBreachJudge()
    )
    assert report.n_tests == 1  # the skip IS surfaced as a finding (not dropped)
    f = report.findings[0]
    assert f.n_trials == 0
    assert "skipped" in f.title and "not multimodal" in f.title


@pytest.mark.asyncio
async def test_scan_endpoint_reports_modality_skip():
    from rogue.reproduce.endpoint_scan import scan_endpoint

    # A real recording panel so we also prove NO dispatch happened for the skipped primitive.
    class _Panel(TargetPanel):
        def __init__(self):
            super().__init__()
            self.dispatched = 0

        async def run_attack(self, *a, **k):
            self.dispatched += 1
            return await super().run_attack(*a, **k)

    panel = _Panel()
    report = await scan_endpoint(
        "https://gw.example/v1",
        "meta-llama/llama-3.1-8b-instruct",  # text-only
        [_multimodal_image_primitive()],
        n_trials=3,
        panel=panel,
        judge=_NeverBreachJudge(),
    )
    assert report.n_skipped == 1
    assert panel.dispatched == 0  # never dispatched the un-renderable media attack
    f = report.findings[0]
    assert f.skipped is not None and f.n_trials == 0
    assert "skipped" in report.summary()
    assert "Skipped" in report.to_markdown()


# --------------------------------------------------------------------------- #
# 4. --deep applies persona-wrap
# --------------------------------------------------------------------------- #


class _FakePersona:
    """Records each wrap and tags the rendered attack so we can assert it was applied."""

    def __init__(self) -> None:
        self.wrapped = 0

    async def wrap_rendered(self, rendered, technique_name):
        self.wrapped += 1
        new = [dict(m) for m in rendered.messages]
        for i in range(len(new) - 1, -1, -1):
            if new[i].get("role") == "user":
                new[i]["content"] = "[PERSONA] " + new[i]["content"]
                break
        return rendered.model_copy(update={"messages": new, "persona_used": technique_name})

    async def aclose(self):
        return None


class _CaptureJudge:
    """Captures the rendered attack text the judge sees, so we can prove the persona frame reached it."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def judge(self, rendered, content, primitive):
        from rogue.schemas.breach_result import JudgeVerdict

        self.seen.append(" ".join(m.get("content", "") for m in rendered.messages))

        class _R:
            verdict = JudgeVerdict.REFUSED

        return _R()


@pytest.mark.asyncio
async def test_deep_applies_persona_wrap_in_run_scan():
    from rogue.scan import run_scan

    persona = _FakePersona()
    judge = _CaptureJudge()
    panel = _CountingPanel()
    await run_scan(
        _config(),
        [_single_turn_primitive()],
        n_trials=1,
        panel=panel,
        judge=judge,
        deep=True,
        persona=persona,
        # Isolate the persona stage — PAIR + escalation are exercised by test_deep_pair_escalation.py.
        pair_max_iters=0,
        escalate=False,
    )
    assert persona.wrapped == 1  # persona-wrap was applied
    assert any("[PERSONA]" in s for s in judge.seen)  # and the framed payload reached dispatch/judge


@pytest.mark.asyncio
async def test_no_deep_skips_persona_wrap():
    from rogue.scan import run_scan

    persona = _FakePersona()
    await run_scan(
        _config(),
        [_single_turn_primitive()],
        n_trials=1,
        panel=_CountingPanel(),
        judge=_NeverBreachJudge(),
        deep=False,
        persona=persona,
    )
    assert persona.wrapped == 0  # default fast scan never persona-wraps


@pytest.mark.asyncio
async def test_deep_applies_persona_wrap_in_scan_endpoint():
    from rogue.reproduce.endpoint_scan import scan_endpoint

    persona = _FakePersona()
    judge = _CaptureJudge()

    # A panel whose dispatch returns one OK response without network.
    class _Panel(TargetPanel):
        async def run_attack(self, rendered, config, temperature=0.7, n_trials=1):
            return [_ok_response()]

    await scan_endpoint(
        "https://gw.example/v1",
        "openai/gpt-5.4-nano",
        [_single_turn_primitive()],
        n_trials=1,
        panel=_Panel(),
        judge=judge,
        deep=True,
        persona=persona,
        # Isolate the persona stage — PAIR + escalation are exercised by test_deep_pair_escalation.py.
        pair_max_iters=0,
        escalate=False,
    )
    assert persona.wrapped == 1
    assert any("[PERSONA]" in s for s in judge.seen)
