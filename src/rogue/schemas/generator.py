"""PayloadGenerator — an attack whose payload is BUILT procedurally, not a static template.

Some techniques are procedures, not strings: many-shot jailbreaking (assemble N shots to a token
budget), shot-repetition, token-budget padding — attacks defined by a *dimension you scale*, not a
fixed payload. A generator captures that: a registry ``kind`` + ``params``, optionally with a
``sweep`` over one param so a reproduction yields an ASR *curve* (ASR vs context length / shot count)
instead of a single point. Resolved by ``rogue.reproduce.generators`` at reproduce time.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class PayloadGenerator(BaseModel):
    """A procedural attack: ``kind`` names a registered builder; ``params`` configure it.

    When ``sweep_param`` is set, the reproduction runs once per value in ``sweep_values`` (overriding
    ``params[sweep_param]`` each time) and reports the ASR curve — this is how ROGUE reproduces the
    *study* (e.g. ASR vs context length), not just one attack instance.
    """

    kind: str = Field(..., min_length=1, max_length=40, description="registry key, e.g. 'many_shot'")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="generator-specific config, e.g. {target_tokens, n_shots, instruction_style, shot_source}",
    )
    sweep_param: str | None = Field(
        default=None,
        description="name of the param to sweep (e.g. 'target_tokens' or 'n_shots'); None = single build",
    )
    sweep_values: list[int] = Field(
        default_factory=list,
        description="values to sweep sweep_param across (ascending); ignored when sweep_param is None",
    )

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _sweep_coherent(self) -> "PayloadGenerator":
        if self.sweep_param is not None and not self.sweep_values:
            raise ValueError("sweep_param set but sweep_values is empty")
        if self.sweep_param is None and self.sweep_values:
            raise ValueError("sweep_values given but no sweep_param to apply them to")
        return self

    def is_sweep(self) -> bool:
        return self.sweep_param is not None and bool(self.sweep_values)
