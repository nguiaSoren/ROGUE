"""Render an AttackPrimitive against a DeploymentConfig into a chat-message list.

Position in pipeline: this module is consumed by `reproduce/target_panel.py`
(`run_attack`), which feeds the returned `RenderedAttack.messages` directly to
the target LLM client (OpenAI / Anthropic / Groq / Mistral / Google SDKs all
accept the same `[{"role": ..., "content": ...}, ...]` shape we emit here).

Slot-resolution precedence (highest to lowest):
  1. `customer_slot_overrides` — per-render dict passed by the caller; lets the
     dashboard or a customer-specific reproduction force a specific topic
     (e.g. swap `{target_topic}` to a forbidden topic from this customer's
     DeploymentConfig.forbidden_topics).
  2. `primitive.payload_slots` — defaults baked into the harvested primitive,
     e.g. the language code chosen by the original source author.
  3. `_SLOT_DEFAULTS` (loaded from tests/fixtures/slot_defaults.json) —
     last-resort fallback so every one of the 14 vocabulary slots is always
     populated and `str.format_map` cannot KeyError on a missing standard slot.

Multi-turn handling: if `primitive.multi_turn_sequence` is non-empty, each turn
is substituted and emitted as its own user message in order. Otherwise the
single `payload_template` becomes one user message.

`requires_system_prompt_access` flag: when True AND the DeploymentConfig has a
non-empty system_prompt, we prepend that system prompt to the message list so
the attack can target the prompt content directly (the threat model for
system-prompt-leak attacks is that the prompt is present in-context). When
False, we do NOT inject the system prompt client-side — the target deployment
will apply it server-side and injecting it twice would change the experiment.

Spec: ROGUE_PLAN.md §8.4 + §4.3 (slot vocabulary) + §4.4 (multi-turn rationale).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from rogue.schemas import AttackPrimitive, DeploymentConfig

__all__ = ["RenderedAttack", "render", "render_multi_turn"]


# ---------- Slot defaults (loaded once at import) ----------

SLOT_DEFAULTS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tests"
    / "fixtures"
    / "slot_defaults.json"
)

# Loaded at import time on purpose: slot_defaults.json is a committed static
# fixture, not user input. A missing/malformed file is a deployment bug and
# should fail loudly at import time — not silently at the first render() call
# in production. The dict is small (14 keys); the one-time cost is negligible.
with SLOT_DEFAULTS_PATH.open(encoding="utf-8") as _f:
    _SLOT_DEFAULTS: dict[str, str] = json.load(_f)


# ---------- The output model ----------


class RenderedAttack(BaseModel):
    """Immutable bundle: an AttackPrimitive resolved against a DeploymentConfig.

    Produced by `render()`, consumed by `reproduce.target_panel.run_attack`,
    which forwards `messages` to the target LLM and stores `resolved_slots` +
    `primitive_id` + `deployment_config_id` on the resulting BreachResult so
    every breach is fully reproducible from the persisted record alone.

    Fields:
      messages: OpenAI / Anthropic-compatible chat-message list. Always at
        least one entry. For single-turn attacks: one user message, optionally
        preceded by a system message. For multi-turn: ordered user messages
        from `multi_turn_sequence`, optionally preceded by a system message.
      is_multi_turn: True iff the source primitive had `requires_multi_turn`
        AND a non-empty `multi_turn_sequence` was used to build `messages`.
      resolved_slots: the 14 (or more) slot values that were substituted in.
        Audit trail for BreachResult.rendered_payload debugging.
      primitive_id: back-reference to the source AttackPrimitive.
      deployment_config_id: back-reference to the target DeploymentConfig.
      persona_used: PAP persuasion technique applied by
        ``reproduce.persona_wrap.PersonaWrapper`` (§10.7), or None for an
        unwrapped baseline render. When set, the LAST user message in
        ``messages`` is the persuasion-framed variant; earlier turns and
        the system prompt are unchanged. Persisted to
        ``breach_results.persona_used`` so the dashboard A/B can group
        wrapped vs unwrapped runs.
    """

    messages: list[dict[str, str]]
    is_multi_turn: bool
    resolved_slots: dict[str, str]
    primitive_id: str
    deployment_config_id: str
    persona_used: str | None = None

    model_config = {"frozen": True}


# ---------- Private helpers ----------


def _resolve_slots(
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    customer_slot_overrides: dict[str, str] | None,
) -> dict[str, str]:
    """Merge slot sources by precedence; return a fully populated dict.

    Precedence: customer_slot_overrides > primitive.payload_slots > _SLOT_DEFAULTS.
    Result is guaranteed to contain every key in _SLOT_DEFAULTS (all 14 standard
    vocabulary slots), plus any extra slots the primitive or the customer
    defined (e.g. `{target_behavior_l1}` in the multilingual fixture).

    `config` is accepted in the signature for forward compatibility — future
    versions may auto-derive slots like `{target_topic}` from
    `config.forbidden_topics`. Today, the caller is responsible for that via
    `customer_slot_overrides`.
    """
    del config  # reserved for future auto-derivation; see docstring
    resolved: dict[str, str] = dict(_SLOT_DEFAULTS)
    resolved.update(primitive.payload_slots)
    if customer_slot_overrides:
        resolved.update(customer_slot_overrides)
    return resolved


_SLOT_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _apply_substitutions(template: str, slots: dict[str, str]) -> str:
    """Substitute `{slot_name}` placeholders in `template` using `slots`.

    2026-05-26 rewrite: switched away from `str.format_map` to a regex-based
    substitution because Pliny-style jailbreak payloads use `{GODMODE: ENABLED}`
    / `{!:SystemUserOverride}` / etc. as **literal in-prompt jailbreak markers**
    (not Python format placeholders), and `format_map` raises KeyError on every
    one of them — silently dropping ~30-40% of the harvested corpus from the
    reproduction sweep.

    The new rule: only substitute `{slot_name}` patterns where `slot_name` is a
    valid Python identifier AND appears in ``slots``. Everything else (including
    `{GODMODE: ENABLED}`, `{}`, `{0:.2f}`-style format specs) passes through as
    literal text, exactly as the attack author wrote it.

    Trade-off: a typo'd known-slot reference like `{taget_query}` (typo in
    `target` ) will silently pass through instead of raising — that's the cost
    of being permissive enough to handle Pliny's corpus. The extraction LLM
    rarely typo's slot names in practice (verified across 171 primitives).
    """
    if not slots:
        # Fast path — no substitutions to make; preserve literal `{...}` text.
        return template

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in slots:
            return str(slots[name])
        return match.group(0)  # leave the literal `{name}` intact

    return _SLOT_RE.sub(_replace, template)


def render_multi_turn(
    primitive: AttackPrimitive,
    resolved_slots: dict[str, str],
) -> list[dict[str, str]]:
    """Render every turn of a multi-turn primitive's sequence with slot validation.

    Extracted as a public surface 2026-05-27 for §10.7 — the multi-turn
    escalation planner (`reproduce.escalation_planner`) emits primitives with
    a non-None ``slot_requirements`` map keyed by turn index. This function
    enforces that every required slot for a given turn is actually present in
    the resolved slot dict before substitution, raising ``ValueError`` on
    miss so the planner's contract failures surface loudly rather than
    silently producing under-specified prompts.

    ``slot_requirements`` is OPTIONAL: pre-§10.7 multi-turn primitives leave
    it as None, in which case no per-turn validation runs and the function
    just renders the sequence verbatim (identical behavior to the prior
    `_build_messages` branch).

    Raises:
        ValueError: when ``primitive.multi_turn_sequence`` is None/empty, or
            when ``slot_requirements[turn_idx]`` references a slot that is
            missing from ``resolved_slots`` (or maps to an empty string —
            empty values are functionally equivalent to missing for the
            attack-prompt rendering use case).
    """
    if not primitive.multi_turn_sequence:
        raise ValueError(
            "render_multi_turn called on primitive with no multi_turn_sequence: "
            f"{primitive.primitive_id!r}",
        )

    requirements = primitive.slot_requirements or {}
    messages: list[dict[str, str]] = []
    for turn_idx, turn_template in enumerate(primitive.multi_turn_sequence):
        required_for_turn = requirements.get(str(turn_idx), [])
        missing: list[str] = []
        for slot_name in required_for_turn:
            value = resolved_slots.get(slot_name, "")
            if not value:
                missing.append(slot_name)
        if missing:
            raise ValueError(
                f"render_multi_turn: primitive {primitive.primitive_id!r} "
                f"turn {turn_idx} requires slots {missing!r} but none were "
                "populated (either pass them via customer_slot_overrides or "
                "extend tests/fixtures/slot_defaults.json)",
            )
        messages.append(
            {
                "role": "user",
                "content": _apply_substitutions(turn_template, resolved_slots),
            },
        )
    return messages


def _build_messages(
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    resolved_slots: dict[str, str],
) -> tuple[list[dict[str, str]], bool]:
    """Assemble the chat-message list.

    Returns (messages, is_multi_turn). The is_multi_turn flag is reported back
    up to `render()` so the RenderedAttack field is consistent with what was
    actually built (not just with the primitive's `requires_multi_turn` flag).
    """
    messages: list[dict[str, str]] = []

    # NOTE: We only inject `config.system_prompt` into the chat history when
    # the primitive's `requires_system_prompt_access` flag is True. The target
    # deployment will always apply its own system prompt server-side; injecting
    # it client-side here too would double-apply it and skew the experiment.
    # The exception — system-prompt-leak / role-hijack attacks — needs the
    # prompt to be present in the *attacker-visible* context, because the
    # threat model is precisely "attacker can see and operate on this prompt
    # in-context." For those, we deliberately mirror the server-side prompt
    # into the message list.
    if primitive.requires_system_prompt_access and config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})

    use_multi_turn = bool(primitive.multi_turn_sequence)
    if use_multi_turn:
        # §10.7: delegate to render_multi_turn() so slot_requirements (when
        # set by escalation_planner) are validated per-turn.
        messages.extend(render_multi_turn(primitive, resolved_slots))
    else:
        messages.append(
            {
                "role": "user",
                "content": _apply_substitutions(primitive.payload_template, resolved_slots),
            }
        )

    return messages, use_multi_turn


# ---------- Public API ----------


def render(
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    customer_slot_overrides: dict[str, str] | None = None,
) -> RenderedAttack:
    """Render an AttackPrimitive against a DeploymentConfig into a chat-message list."""
    resolved_slots = _resolve_slots(primitive, config, customer_slot_overrides)
    messages, is_multi_turn = _build_messages(primitive, config, resolved_slots)
    return RenderedAttack(
        messages=messages,
        is_multi_turn=is_multi_turn,
        resolved_slots=resolved_slots,
        primitive_id=primitive.primitive_id,
        deployment_config_id=config.config_id,
    )
