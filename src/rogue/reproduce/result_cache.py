"""Content-hash verdict cache — skip re-firing an identical rendered request (Audit-5 rec #3).

ROGUE's mission is *continuous* re-measurement (daily briefs, ~$35/full reproduce). When a scan
re-fires a request byte-identical to one already fired — same messages, same target, same system
prompt, same sampling knobs — the paid target call is pure waste. This module is a read-through cache
keyed on the FULL rendered request that lets :meth:`TargetPanel.run_attack` return the stored
:class:`~rogue.reproduce.target_panel.ModelResponse` samples instead of spending money again.

Design (mirrors the ``persona_wrap`` sha256 wrap-cache style):

* **Content-addressed.** The key is ``sha256`` over every field that changes what is fired —
  messages + media transforms + target_model + system + base_url + max_output_tokens +
  reasoning_effort + temperature + n_trials + seed_reply + provider pin. Adding a field only ever
  *shrinks* the hit set, so the cache can never return a stale verdict for a request that differs in
  any keying field (the caller's hard invariant).
* **Opt-in / safe.** Default OFF. ``ResultCache.from_env()`` returns ``None`` unless
  ``ROGUE_VERDICT_CACHE`` is truthy, so a panel constructed without an explicit cache is
  byte-identical to today. Never caches a run that had ANY errored trial (a transient rate-limit /
  provider error must not poison future runs).
* **Bounded.** An in-process ``OrderedDict`` LRU (``max_entries``) is the fast path; an optional
  on-disk directory gives cross-process reuse (the value for a repeated/crashed-then-rerun scan).

The stored unit is the ``list[ModelResponse]`` that ``run_attack`` returns (the "samples"); the judge
still grades them downstream, so a cache hit reproduces the exact same verdict counts it would have.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rogue.reproduce.instantiator import RenderedAttack
    from rogue.reproduce.target_panel import ModelResponse
    from rogue.schemas import DeploymentConfig

__all__ = ["ResultCache", "DEFAULT_CACHE_DIR", "CACHE_FLAG_ENV"]

_log = logging.getLogger(__name__)

# On-disk store location when the env flag turns the cache on (parallels persona_wrap's cache dir).
DEFAULT_CACHE_DIR = Path("data/verdict_cache")
CACHE_FLAG_ENV = "ROGUE_VERDICT_CACHE"
_CACHE_DIR_ENV = "ROGUE_VERDICT_CACHE_DIR"

# Bump if the key composition or stored-value shape changes so old entries can never false-hit.
_KEY_VERSION = "v1"

_TRUE = {"1", "on", "true", "yes"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ResultCache:
    """A content-addressed, read-through cache of ``run_attack`` result lists.

    In-process LRU (bounded by ``max_entries``) with optional write-through to ``cache_dir`` for
    cross-process reuse. Construct directly in tests (in-memory by default); use
    :meth:`from_env` in production so the cache stays OFF unless the operator opts in.
    """

    def __init__(self, *, cache_dir: Path | None = None, max_entries: int = 4096) -> None:
        self._mem: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._max = max(1, int(max_entries))
        self._dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        # Cheap observability — surfaced by callers/tests to prove hits actually skipped a fire.
        self.hits = 0
        self.misses = 0

    # ----- Construction -----

    @classmethod
    def from_env(cls) -> ResultCache | None:
        """Return a cache iff ``ROGUE_VERDICT_CACHE`` is truthy, else ``None`` (byte-identical default).

        On → an on-disk store at ``ROGUE_VERDICT_CACHE_DIR`` (or :data:`DEFAULT_CACHE_DIR`) so the
        savings persist across processes / a crashed-then-rerun scan.
        """
        if os.environ.get(CACHE_FLAG_ENV, "").strip().lower() not in _TRUE:
            return None
        raw = os.environ.get(_CACHE_DIR_ENV)
        return cls(cache_dir=Path(raw) if raw else DEFAULT_CACHE_DIR)

    # ----- Key composition -----

    @staticmethod
    def key_for(
        rendered: RenderedAttack,
        config: DeploymentConfig,
        *,
        temperature: float,
        n_trials: int,
        seed_reply: str | None,
        max_output_tokens: int | None,
        reasoning_effort: str | None,
        provider_pin: Any | None = None,
    ) -> str:
        """sha256 over EVERY field that changes what gets fired. More fields ⇒ safer (never a false hit).

        Media payloads are hashed (not embedded) so the key stays small; ``provider_pin`` is folded in
        because a pinned backend is a different physical target and must not share a cache entry.
        """
        media: dict[str, str] = {}
        if getattr(rendered, "image_b64", None) is not None:
            media["image"] = _sha(rendered.image_b64)
            media["image_media_type"] = rendered.image_media_type
        if getattr(rendered, "audio_b64", None) is not None:
            media["audio"] = _sha(rendered.audio_b64)
            media["audio_format"] = rendered.audio_format

        payload = {
            "_v": _KEY_VERSION,
            "target_model": config.target_model,
            "base_url": config.base_url or "",
            "system": config.system_prompt or "",
            "messages": rendered.messages,
            "persona_used": getattr(rendered, "persona_used", None),
            "media": media,
            "seed_reply": seed_reply or "",
            "max_output_tokens": max_output_tokens,
            "reasoning_effort": reasoning_effort or "",
            "temperature": temperature,
            "n_trials": n_trials,
            "provider_pin": provider_pin,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return _sha(blob)

    # ----- Read-through API -----

    def get(self, key: str) -> list[ModelResponse] | None:
        """Return the cached responses for ``key`` (in-memory first, then disk), or ``None`` on a miss."""
        raw = self._mem.get(key)
        if raw is not None:
            self._mem.move_to_end(key)  # LRU touch
        elif self._dir is not None:
            raw = self._load_disk(key)
            if raw is not None:
                self._remember(key, raw)  # promote into the in-process LRU
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return self._deserialize(raw)

    def put(self, key: str, responses: list[ModelResponse]) -> None:
        """Store ``responses`` under ``key``. No-op if any trial errored (never cache a transient fail)."""
        if not responses or any(r.error is not None for r in responses):
            return
        raw = [r.model_dump(mode="json") for r in responses]
        self._remember(key, raw)
        if self._dir is not None:
            self._write_disk(key, raw)

    # ----- Internals -----

    def _remember(self, key: str, raw: list[dict[str, Any]]) -> None:
        self._mem[key] = raw
        self._mem.move_to_end(key)
        while len(self._mem) > self._max:
            self._mem.popitem(last=False)  # evict least-recently-used

    @staticmethod
    def _deserialize(raw: list[dict[str, Any]]) -> list[ModelResponse]:
        from rogue.reproduce.target_panel import ModelResponse  # noqa: PLC0415 — break import cycle

        return [ModelResponse.model_validate(d) for d in raw]

    def _disk_path(self, key: str) -> Path:
        assert self._dir is not None
        return self._dir / f"{key}.json"

    def _load_disk(self, key: str) -> list[dict[str, Any]] | None:
        path = self._disk_path(key)
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # a corrupt/half-written entry is a miss, never a crash
            _log.debug("verdict cache disk read failed for %s: %s", key, exc)
            return None
        return data if isinstance(data, list) else None

    def _write_disk(self, key: str, raw: list[dict[str, Any]]) -> None:
        path = self._disk_path(key)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(raw), encoding="utf-8")
            tmp.replace(path)  # atomic: a reader never sees a half-written file
        except OSError as exc:  # a cache write failure must never break the scan
            _log.debug("verdict cache disk write failed for %s: %s", key, exc)
