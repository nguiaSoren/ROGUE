"""Agent execution harness — the runtime that gives a target model a real tool loop.

See ``docs/v2/agent_harness/DESIGN.md``. Phase 2 lands the tool backends + canary/context
foundation; the harness loop (Phase 3) and trace judge (Phase 4) build on top.
"""

from .canaries import CANARY_KINDS, is_neutral, mint_canary, new_run_secret
from .context import AgentRunContext, InjectionPayload

__all__ = [
    "AgentRunContext",
    "InjectionPayload",
    "mint_canary",
    "new_run_secret",
    "is_neutral",
    "CANARY_KINDS",
]
