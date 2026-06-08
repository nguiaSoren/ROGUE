"""BreachContext — the EXTRA per-rule context a non-harm rubric needs.

v2 build-02 §1.2. The harm judge scores against fields that already live on the
``AttackPrimitive`` (``title`` / ``family`` / ``vector`` / ``short_description``,
rendered by ``JudgeAgent._build_user_message``). A non-harm breach type needs two
additional pieces of context that the primitive does not carry:

* ``rule_text`` — the governance rule being tested (e.g. "never reveal another
  employee's compensation", "no refund over the $500 cap"). The rubric's
  consummation gate is defined *relative to this rule*.
* ``protected_target`` — what specifically must not be disclosed or executed
  (e.g. "another employee's compensation", "a refund authorization over $500").

This model carries ONLY those extra fields. The harm fields still come from the
``primitive`` — they are deliberately not duplicated here. For the
``capability_transfer`` (harm) case both fields are ``None``, which is the signal
to the judge integration to render no extra blocks, leaving the harm user-message
bytes unchanged (the byte-identical guarantee that protects caching + batch
parity, build-02 §1.2 / §5).
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["BreachContext"]


class BreachContext(BaseModel):
    """Per-rule context beyond the harm case (build-02 §1.2).

    Both fields default to ``None`` — an empty ``BreachContext()`` is the harm
    case, where no extra context is injected and behavior is unchanged.

    Attributes:
        rule_text: the governance rule being tested, or ``None`` for the harm
            case (where the "rule" is implicit — "don't transfer harmful
            capability"). Carried here, not on the primitive, because it is a
            property of the *deployment policy under test*, not of the attack.
        protected_target: what must not be disclosed/executed, or ``None`` for
            the harm case.
    """

    rule_text: str | None = None
    protected_target: str | None = None

    model_config = {"frozen": True}
