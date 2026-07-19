"""Central NUL-safe Postgres writes.

PostgreSQL ``text`` fields cannot contain NUL (0x00) bytes. A model response occasionally
contains one (some OSS models emit it), and a single such value fails the WHOLE
``executemany`` batch — crashing a reproduce cell after partial progress. reproduce_once
has several uncoordinated write paths (``persist_breach_rows``, ORM ``session.add`` flushes,
``neon_sync``'s bulk copy), so patching them one-by-one is whack-a-mole.

The correct fix is one place: a psycopg ``str`` Dumper that strips NUL at the DRIVER level,
registered on the global adapters map so EVERY connection (any path, any engine) sanitizes
its string writes. Importing this module registers it. 2026-07-10 paid-session hardening.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _strip(obj: str) -> str:
    return obj.replace("\x00", "") if "\x00" in obj else obj


def register() -> bool:
    """Register NUL-stripping str dumpers on psycopg's global adapters map. Idempotent;
    returns True on success. Never raises — a missing psycopg internal must not break imports."""
    try:
        import psycopg
        from psycopg.types.string import StrBinaryDumper, StrDumper

        class _NulSafeStrDumper(StrDumper):
            def dump(self, obj):  # type: ignore[override]
                return super().dump(_strip(obj))

        class _NulSafeStrBinaryDumper(StrBinaryDumper):
            def dump(self, obj):  # type: ignore[override]
                return super().dump(_strip(obj))

        psycopg.adapters.register_dumper(str, _NulSafeStrDumper)
        psycopg.adapters.register_dumper(str, _NulSafeStrBinaryDumper)
        return True
    except Exception as exc:  # noqa: BLE001 — hardening, never fatal
        _log.warning("nul_safe: could not register NUL-stripping dumper: %s", exc)
        return False


_REGISTERED = False  # DISABLED 2026-07-10: global str dumper broke enum (judge_verdict) inserts — needs a per-column approach
