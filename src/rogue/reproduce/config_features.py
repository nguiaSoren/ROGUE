"""Config feature vector — the per-config context for the scheduler's hierarchical prior.

The break-bandit reorders strategies by breach telemetry, but a *new* config has no history, and its
own history (when it has one) is thin. Config features let a config borrow evidence from configs *like
it*: "this is a large, long-context model → prioritise the strategies that beat other large,
long-context models." Derived from the model id + ModelSpec (no new data). These are CORRELATIONAL
priors that guide exploration order — the actual reproduction still measures the truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rogue.adapters import model_specs

# name tokens → size class (checked in order; first match wins). Heuristic + price/context fallback.
_SMALL = re.compile(r"nano|mini|small|tiny|haiku|gemma|phi|\b[1-9]b\b|\b1[0-5]b\b", re.I)
_LARGE = re.compile(r"opus|\b(7[0-9]|8[0-9]|9[0-9]|[1-9][0-9]{2})b\b|405b|large|ultra|405", re.I)


def _size_class(model: str, spec) -> str:
    name = model.lower()
    if _LARGE.search(name):
        return "large"
    if _SMALL.search(name):
        return "small"
    # price fallback: input $/M is a rough capability/size proxy when the name is opaque
    in_price = getattr(spec, "input_price_per_m", None) if spec else None
    if in_price is not None:
        if in_price >= 3.0:
            return "large"
        if in_price <= 0.5:
            return "small"
    return "medium"


def _context_bucket(spec) -> str:
    ctx = getattr(spec, "max_context_tokens", None) if spec else None
    if not ctx:
        return "unknown"
    if ctx <= 16_000:
        return "short"
    if ctx <= 65_000:
        return "medium"
    if ctx <= 200_000:
        return "long"
    return "xlong"


@dataclass(frozen=True)
class ConfigFeatures:
    """A small, comparable descriptor of a deployment's target. ``sibling_key`` is what the
    hierarchical prior groups on — configs sharing it pool their breach evidence."""

    size_class: str          # small | medium | large
    context_bucket: str      # short | medium | long | xlong | unknown
    vendor: str              # openai | anthropic | mistral | qwen | ...
    supports_tools: bool
    multimodal: bool

    @property
    def sibling_key(self) -> str:
        """The grouping key for evidence-pooling: size × context reach (the axes the papers link to ASR)."""
        return f"{self.size_class}:{self.context_bucket}"


def derive_config_features(target_model: str, *, base_url: str | None = None) -> ConfigFeatures:
    spec = model_specs.get_spec(target_model) if hasattr(model_specs, "get_spec") else None
    try:
        vendor = model_specs.extract_vendor(target_model)
    except Exception:  # noqa: BLE001
        vendor = "unknown"
    tools = bool(getattr(spec, "supports_tools", False)) or bool(base_url)
    mm = bool(getattr(spec, "supports_image", False) or getattr(spec, "supports_audio", False))
    return ConfigFeatures(
        size_class=_size_class(target_model, spec),
        context_bucket=_context_bucket(spec),
        vendor=vendor,
        supports_tools=tools,
        multimodal=mm,
    )
