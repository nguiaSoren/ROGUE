"""ROGUE platform layer — turns the scan engine into a multi-tenant service (SDK / API / MCP / dashboard
over one backend). Design: docs/platform/ARCHITECTURE.md.

Exposed lazily so `import rogue.platform` stays cheap and free of import cycles; concrete services
(ScanService, ScanEngine, ReportService, the queue/store, the worker) load on first access.
"""

from __future__ import annotations

from .interfaces import (
    JobQueue,
    LeasedJob,
    ProgressCallback,
    ReportService,
    ScanEngine,
    ScanService,
    ScanStore,
)
from .schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec

__all__ = [
    "ScanStatus",
    "TargetSpec",
    "ScanSpec",
    "ScanRecord",
    "ScanStore",
    "JobQueue",
    "ScanEngine",
    "ScanService",
    "ReportService",
    "ProgressCallback",
    "LeasedJob",
]
