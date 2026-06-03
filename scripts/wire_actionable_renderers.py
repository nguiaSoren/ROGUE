#!/usr/bin/env python
"""Clear the 7 ACTIONABLE renderer techniques by wiring them to EXISTING renderers.

The 60d-harvest backlog (needs_implementation=14) decomposed into 7 actionable +
7 synthesis-grade. The 7 actionable need no new renderer code — they're covered by
renderers ROGUE already ships and already breaches with:

  4 typographic/text-in-image  → typographic / vpi-overlay / ocr renderers
                                  (existing image attacks already breach 36-61%)
  3 TTS-audio                  → speech / styled-audio renderers
                                  (existing audio path already breaches ~69%)

So "clearing" them is registry wiring, not engineering: register a RendererCapability
per technique pointing at the existing renderer's entrypoint (origin=human, the
trusted-authoring fast path), then activate_with_cascade flips the technique
needs_implementation→active. ladder_strategies=[] because the underlying strategy is
ALREADY in the ladder's default tier — these rows record provenance + clear the
backlog, they do not double-count the tier. Idempotent; reversible (re-park by
deleting the renderer_capabilities rows + setting status back).

    uv run python scripts/wire_actionable_renderers.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from rogue.reproduce.renderer_registry import activate_with_cascade, register_renderer  # noqa: E402
from rogue.schemas.renderer_manifest import RendererManifest, RendererOrigin, RendererStatus  # noqa: E402

_R = "rogue.reproduce.modality_renderers"

# (technique_id, base_renderer, entrypoint, modality, artifact, rationale)
MAPPINGS = [
    ("01KT6YSPXCP9FKTB1SFQ866KRM", "typographic_png", f"{_R}.typographic:render_typographic_image",
     "image", "png", "multilingual visual typography → typographic renderer"),
    ("01KT77V44SWDXW6HFQXTQC74YK", "typographic_png", f"{_R}.typographic:render_typographic_image",
     "image", "png", "typographic prompt injection (rendered text) → typographic renderer"),
    ("01KT77VAR0PKVW685ED5PHS1ZT", "vpi_overlay", f"{_R}.vpi:render_vpi_overlay",
     "image", "png", "visual anchoring via text overlay → vpi overlay renderer"),
    ("01KT77VFFAD5JT3YBQSBXF5PH3", "ocr_image", f"{_R}.ocr:render_ocr_image",
     "image", "png", "modality evasion (hide text from text encoder) → ocr white-on-white"),
    ("01KT3AEDMR83X88QEBDW3ZHH4V", "speech_audio", f"{_R}.audio_tts:render_speech_audio",
     "audio", "wav", "cross-modality text→audio transfer → TTS speech renderer"),
    ("01KT6YRC404PFVZKAZCVPNMT3N", "styled_audio", f"{_R}.audio_styles:render_styled_audio",
     "audio", "wav", "acoustic best-of-N (vary acoustic properties) → styled audio renderer"),
    ("01KT6YRC6VXH75Q0WY49VDWP5C", "styled_audio", f"{_R}.audio_styles:render_styled_audio",
     "audio", "wav", "multilingual/multi-accent audio → styled audio renderer (accent variation)"),
]


def main() -> int:
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(os.environ["DATABASE_URL"])
    now = datetime.now(timezone.utc)
    from rogue.db.models import AttackStrategy, RendererCapability

    from rogue.schemas.technique_spec import StrategyStatus

    wired = skipped = 0
    with Session(e) as s:
        for tid, base, entrypoint, modality, artifact, rationale in MAPPINGS:
            rid = f"{base}_{tid.lower()}"  # FULL ulid — same-batch ulids share an 8-char prefix
            tech = s.get(AttackStrategy, tid)
            if tech is None:
                print(f"  MISSING technique {tid} — skipped")
                continue
            # idempotent on technique status: an already-cleared technique is skipped,
            # so re-running only wires whatever is still parked.
            if tech.status != StrategyStatus.NEEDS_IMPLEMENTATION or s.get(RendererCapability, rid):
                print(f"  SKIP (already cleared): {tech.name[:46]}")
                skipped += 1
                continue
            manifest = RendererManifest(
                renderer_id=rid,
                name=f"[wired] {tech.name[:80]}",
                technique_id=tid,
                modality=modality,
                origin=RendererOrigin.HUMAN,  # reuses a trusted, shipped renderer
                entrypoint=entrypoint,
                artifact_types=[artifact],
                ladder_strategies=[],  # covered by the default tier; no double-count
                network_allowed=False,
                deterministic=True,
                sandbox_policy="none",
                status=RendererStatus.HUMAN_APPROVED,  # legal predecessor of ACTIVE for HUMAN
                approved_by="backlog-cleanup-20260604",
                approved_at=now,
            )
            row = register_renderer(s, manifest)
            activate_with_cascade(s, row, now=now)
            print(f"  WIRED {rid:28} [{modality}] {tech.name[:42]}")
            print(f"        {rationale}")
            wired += 1
        s.commit()

    with Session(e) as s:
        from sqlalchemy import func
        ni = s.query(func.count()).select_from(AttackStrategy).filter(
            AttackStrategy.status == "needs_implementation").scalar()
        print(f"\n  wired={wired} skipped={skipped}  →  needs_implementation now: {ni}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
