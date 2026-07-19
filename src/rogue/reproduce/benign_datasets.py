"""Benign look-alike datasets — the *denominators* of the over-refusal / FRR board.

The robustness board attacks models with harmful goals; the safeguard board fires the
opposite: prompts that LOOK adversarial (or sit near a policy boundary) but are entirely
benign and SHOULD be answered. The FRR is how often a model wrongly refuses them. This
module is the loader for those benign sets — the exact companion to ``benchmark.datasets``
(the harmful denominators), living on the eval side.

Two sets are wired to start (small, public, standard):

  * **XSTest** (Röttger et al. 2023) — 250 hand-written safe prompts built to look unsafe
    (homonyms like "how do I *kill* a Python process", figurative "*blow away* my audience",
    safe targets "kill a *mosquito*"). The canonical over-refusal probe.
  * **JBB benign split** (JailbreakBench/JBB-Behaviors:benign) — 100 benign behaviors that
    mirror the harmful JBB goals, so the FRR shares JBB's construction with the breach side.

Both ship as a **vendored subset** under ``data/safeguard/benign/*.jsonl`` so the eval's
$0 dry-run + unit tests exercise the full path with no network. The FULL benchmarks load
via :func:`freeze_full` — a one-time HF datasets-server pull, GATED (needs the paid/again-$0
sweep to be worth running) and never fired automatically, mirroring ``benchmark.datasets``.

Adding **OR-Bench** (or SORRY-Bench's benign twin) later is a one-line registry entry in
:data:`BENIGN_SOURCES` + a vendored fixture — no refactor of the eval or the board.

Spec: audit-4 GAP 1 (idea 6 + idea 9-benign).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rogue.reproduce.over_refusal_eval import BenignItem

__all__ = [
    "BENIGN_SOURCES",
    "BenignSource",
    "available_sources",
    "load_benign",
    "load_benign_panel",
    "load_jbb_benign",
    "load_xstest",
]

_VENDOR_DIR = Path(__file__).resolve().parents[3] / "data" / "safeguard" / "benign"


@dataclass(frozen=True)
class BenignSource:
    """A registered benign benchmark: how to load its vendored subset + where the full
    set is pulled from. Adding OR-Bench = one more entry here + a vendored ``*.jsonl``."""

    key: str
    label: str
    vendored_file: str  # basename under data/safeguard/benign/
    # HF datasets-server coordinates for the one-time full freeze (GATED, not run here):
    hf_dataset: str
    hf_config: str
    hf_split: str
    prompt_col: str
    category_col: str = ""


# The registry. OR-Bench / SORRY-Bench-benign drop in here without touching the eval.
BENIGN_SOURCES: dict[str, BenignSource] = {
    "xstest": BenignSource(
        key="xstest",
        label="XSTest (safe subset)",
        vendored_file="xstest_safe.jsonl",
        hf_dataset="natolambert/xstest-v2-copy",
        hf_config="prompts",
        hf_split="train",  # filtered to type startswith 'safe' at freeze time
        prompt_col="prompt",
        category_col="type",
    ),
    "jbb_benign": BenignSource(
        key="jbb_benign",
        label="JBB-Behaviors (benign split)",
        vendored_file="jbb_benign.jsonl",
        hf_dataset="JailbreakBench/JBB-Behaviors",
        hf_config="behaviors",
        hf_split="benign",
        prompt_col="Goal",
        category_col="Category",
    ),
}


def available_sources() -> list[str]:
    """Registered benign-set keys (``["jbb_benign", "xstest"]`` today)."""
    return sorted(BENIGN_SOURCES)


def _load_vendored(source: BenignSource) -> list[BenignItem]:
    path = _VENDOR_DIR / source.vendored_file
    if not path.is_file():
        raise FileNotFoundError(
            f"vendored benign subset for {source.key!r} not found at {path}. "
            f"It should ship in the repo; the full set loads via freeze_full({source.key!r})."
        )
    items: list[BenignItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        prompt = str(row.get("prompt", "")).strip()
        if not prompt:
            continue
        items.append(
            BenignItem(
                prompt=prompt,
                source=str(row.get("source", source.key)),
                category=str(row.get("category", "")),
            )
        )
    return items


def load_benign(key: str) -> list[BenignItem]:
    """Load the vendored subset for one registered benign set.

    Offline + free — reads ``data/safeguard/benign/<file>.jsonl``. The FULL benchmark is a
    gated one-time :func:`freeze_full`. Raises ``KeyError`` on an unknown set with the list
    of known keys.
    """
    if key not in BENIGN_SOURCES:
        raise KeyError(f"unknown benign set {key!r}; known: {available_sources()}")
    return _load_vendored(BENIGN_SOURCES[key])


def load_xstest() -> list[BenignItem]:
    """XSTest safe look-alikes (vendored subset)."""
    return load_benign("xstest")


def load_jbb_benign() -> list[BenignItem]:
    """JBB benign split (vendored subset)."""
    return load_benign("jbb_benign")


def load_benign_panel(keys: list[str] | None = None) -> list[BenignItem]:
    """Load + concatenate several benign sets into one panel (default: all registered).

    The FRR board fires this whole panel at each model; ``score_model``'s ``by_set`` breaks
    the rate back out per source, so mixing sets here loses no per-benchmark resolution.
    """
    keys = keys if keys is not None else available_sources()
    out: list[BenignItem] = []
    for k in keys:
        out.extend(load_benign(k))
    return out


# --------------------------------------------------------------------------- #
# One-time FULL freeze (GATED — network pull, not run by the eval/tests)
# --------------------------------------------------------------------------- #
def freeze_full(key: str, *, out_dir: Path | None = None) -> dict:
    """Pull the FULL benign benchmark from the HF datasets-server and overwrite the vendored
    JSONL with the complete set. One-time, GATED — reuses ``benchmark.datasets._rows`` so the
    freeze mechanics (auth, retry, paging) match the harmful side. NOT invoked by the eval or
    the sweep's dry-run; a maintainer runs it once when the full denominators are wanted.

    Returns a small manifest ``{key, n, source}``. For XSTest, rows are filtered to the safe
    ``type`` values (``type`` startswith ``safe``); the unsafe XSTest prompts are the breach
    side's concern, not the FRR board's.
    """
    if key not in BENIGN_SOURCES:
        raise KeyError(f"unknown benign set {key!r}; known: {available_sources()}")
    src = BENIGN_SOURCES[key]
    # Local import so the module stays free of the benchmark package + network at import time.
    from benchmark.datasets import _rows  # type: ignore[attr-defined]

    rows = _rows(src.hf_dataset, src.hf_config, src.hf_split)
    records: list[dict] = []
    for r in rows:
        prompt = str(r.get(src.prompt_col, "")).strip()
        if not prompt:
            continue
        category = str(r.get(src.category_col, "")) if src.category_col else ""
        if key == "xstest" and not category.lower().startswith("safe"):
            continue  # keep only the SAFE XSTest prompts for the FRR denominator
        records.append({"prompt": prompt, "category": category, "source": key})

    out_dir = out_dir or _VENDOR_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)
    (out_dir / src.vendored_file).write_text(body, encoding="utf-8")
    return {"key": key, "n": len(records), "source": f"{src.hf_dataset}:{src.hf_config}/{src.hf_split}"}
