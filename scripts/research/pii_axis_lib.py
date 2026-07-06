"""Shared helpers for the Axis B (PII-leakage) research runs.

Adapter construction + a cost meter, the ai4privacy→ROGUE-attribute label map, and value-overlap
scoring. Used by pii_calibration.py, pii_provenance_eval.py, pii_emission_run.py.

Not shipped as product code — a research-layer harness (like the other scripts/research/* runs).
Real paid LLM calls go through the same rogue.adapters registry the product uses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from rogue.adapters import AdapterConfig, registry  # noqa: E402
from rogue.core.message import CanonicalMessage  # noqa: E402


_FEATHERLESS_BASE = "https://api.featherless.ai/v1"


def build_adapter(model: str):
    """Build a target adapter. A ``featherless:`` prefix routes to Featherless's OpenAI-compatible
    endpoint via the CustomHTTP adapter; otherwise the provider is the id's first segment."""
    if model.startswith("featherless:"):
        wire = model.split(":", 1)[1]
        return registry.create("custom", AdapterConfig(
            model=wire, base_url=_FEATHERLESS_BASE, api_key=os.environ.get("FEATHERLESS_API_KEY")))
    provider = model.split("/", 1)[0]
    return registry.create(provider, AdapterConfig(model=model))


def fisher_exact_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher's exact test p-value for a 2×2 table [[a,b],[c,d]] — P(row-1 leak ≥ a).

    Use to test whether a model's leak count (a of a+b) exceeds a baseline (c of c+d), e.g. an OSS
    model vs OpenAI's 0/36 (Paper A: attach a significance test, not a bare percentage).
    """
    from math import comb

    n, row1, col1 = a + b + c + d, a + b, a + c
    denom = comb(n, col1)
    kmax = min(row1, col1)
    return sum(comb(row1, k) * comb(a + c + b + d - row1, col1 - k) for k in range(a, kmax + 1)) / denom


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for a rate k/n — defensible for small n and rates near 0/1 (Paper A)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class Meter:
    """Accumulates real spend across wrapped invoke calls."""

    calls: int = 0
    cost_usd: float = 0.0
    tok_in: int = 0
    tok_out: int = 0

    def wrap(self, adapter: Any):
        inner = adapter.invoke

        async def _counted(messages, **kw):
            r = await inner(messages, **kw)
            u = r.usage
            self.calls += 1
            self.cost_usd += u.estimated_cost_usd or 0.0
            self.tok_in += u.input_tokens
            self.tok_out += u.output_tokens
            return r

        return _counted

    def summary(self) -> dict:
        return {"calls": self.calls, "cost_usd": round(self.cost_usd, 6), "tok_in": self.tok_in, "tok_out": self.tok_out}


async def ask(invoke, user: str, *, system: str | None = None, temperature: float = 0.0) -> str:
    msgs = []
    if system:
        msgs.append(CanonicalMessage.system(system))
    msgs.append(CanonicalMessage.user(user))
    r = await invoke(msgs, temperature=temperature)
    return r.text


# ---- ai4privacy label → ROGUE PRI attribute (None = out of scope for our detector) ----
LABEL_MAP: dict[str, str] = {
    "FIRSTNAME": "full_name", "LASTNAME": "full_name", "MIDDLENAME": "full_name",
    "EMAIL": "email",
    "PHONENUMBER": "phone",
    "CREDITCARDNUMBER": "credit_card",
    "IPV4": "ip_address", "IPV6": "ip_address", "IP": "ip_address",
    "DOB": "date_of_birth",
    "SSN": "ssn",
    "NATIONALITY": "nationality",
    "GENDER": "gender", "SEX": "gender",
    "STREET": "address", "BUILDINGNUMBER": "address", "CITY": "address",
    "STATE": "address", "ZIPCODE": "address", "COUNTY": "address", "SECONDARYADDRESS": "address",
}


def map_label(label: str) -> str | None:
    return LABEL_MAP.get(label)


def value_overlap(a: str, b: str) -> bool:
    """Case-insensitive containment either direction (handles 'Jane' vs 'Jane Doe')."""
    a2, b2 = a.strip().lower(), b.strip().lower()
    if not a2 or not b2:
        return False
    return a2 in b2 or b2 in a2


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    by_attr: dict = field(default_factory=dict)

    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    def f1(self) -> float:
        p, r = self.precision(), self.recall()
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision(), 4),
            "recall": round(self.recall(), 4),
            "f1": round(self.f1(), 4),
        }
