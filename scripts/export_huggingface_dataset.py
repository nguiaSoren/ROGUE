"""Export the AttackPrimitive corpus to JSONL for HuggingFace dataset publication.

Used by: ROGUE_PLAN.md §11.3.5 (Public dataset publication on HuggingFace,
"first continuous-harvest LLM threat-intel dataset") + §10.7 augmentation
roadmap item "HuggingFace dataset split — separate harvested from derived
for honest provenance."

Three output files (all under `dist/`):

  1. **`rogue-attacks-{period}.jsonl`** — canonical primitives harvested
     from the open web. Filter: ``canonical = TRUE AND synthesized = FALSE``.
     These are what ROGUE found in the wild.

  2. **`rogue-attacks-derived-{period}.jsonl`** — canonical primitives
     synthesized by ROGUE's augmentation layer (escalation_planner +
     syntactic_mutation). Filter: ``canonical = TRUE AND synthesized =
     TRUE``. Each row carries ``derived_from_primitive_id`` pointing back
     at the harvested parent so the research community can audit the
     chain. §10.7 split for honest provenance.

  3. **`quarantined-attacks-{period}.jsonl`** — non-canonical primitives
     (failed dedup or quarantined under the §3.5 budget-conditional gate).
     Filter: ``canonical = FALSE``. Included for research-community
     honesty about the actual state of the public discourse (techniques
     described without concrete payloads, low-confidence extractions, etc.).

Plus a generated **dataset card** at `dist/README.md` — the markdown file
HuggingFace renders as the dataset's home page. Template derived from
ROGUE_PLAN.md §A.29 with the §10.7 derived-file row added.

Each JSONL row is one ``AttackPrimitive.model_dump_json()`` per the Pydantic
wire format. The ORM-only ``payload_embedding`` column is stripped
automatically (it's not on the Pydantic schema), per §11.3.5's "not
redistribution-safe, regenerable in 30s" stance. SourceProvenance is
inlined (nested objects, not joins) so each line is fully self-describing.

Run from the repo root::

    # Default: write three JSONL files + README to dist/ for current YYYY-MM
    uv run python scripts/export_huggingface_dataset.py

    # Override period tag (e.g. "2026-05") or output dir:
    uv run python scripts/export_huggingface_dataset.py --period-tag 2026-05 --output-dir dist/

    # Upload to HuggingFace (Day-4 polish; requires HF_TOKEN env var):
    uv run python scripts/export_huggingface_dataset.py --upload --hf-repo soren/rogue-attacks-2026-05

Env vars: ``DATABASE_URL`` (defaults to dev DB), ``HF_TOKEN`` (only if
``--upload`` is set).

Spec: ROGUE_PLAN.md §11.3.5 + §10.7 dataset-split checklist item + §A.29.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.schemas import (  # noqa: E402
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
)

logger = logging.getLogger("rogue.scripts.export_huggingface_dataset")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
DEFAULT_OUTPUT_DIR = Path("dist")


# ----- Data classes -----


@dataclass
class FileStats:
    filename: str
    n_rows: int = 0
    families: set[str] = field(default_factory=set)
    source_urls: set[str] = field(default_factory=set)
    size_bytes: int = 0

    def summary(self) -> str:
        size_mb = self.size_bytes / (1024 * 1024)
        return (
            f"{self.filename:<45} {self.n_rows:>5} rows  "
            f"{len(self.families):>2} families  "
            f"{len(self.source_urls):>4} unique sources  "
            f"{size_mb:>6.2f} MB"
        )


@dataclass
class ExportStats:
    harvested: FileStats
    derived: FileStats
    quarantined: FileStats
    derived_parent_count: int = 0  # distinct parent primitives represented

    def total_rows(self) -> int:
        return (
            self.harvested.n_rows + self.derived.n_rows + self.quarantined.n_rows
        )


# ----- Helpers -----


def _orm_to_pydantic(orm: AttackPrimitiveORM) -> AttackPrimitive:
    """Project an ORM row into the Pydantic wire shape. Same projection
    used by `scripts/synthesize_escalations.py` and friends — kept inline
    here so the export script is self-contained.

    ``payload_embedding`` is on the ORM only (off the wire); not included
    in the projection ⇒ never appears in the exported JSON. That's the
    §11.3.5 "regenerable in 30s, not redistribution-safe" requirement
    satisfied by construction.
    """
    return AttackPrimitive.model_validate(
        {
            "primitive_id": orm.primitive_id,
            "cluster_id": orm.cluster_id,
            "canonical": orm.canonical,
            "family": (
                AttackFamily(orm.family) if isinstance(orm.family, str) else orm.family
            ),
            "secondary_families": [
                AttackFamily(f) if isinstance(f, str) else f
                for f in (orm.secondary_families or [])
            ],
            "vector": (
                AttackVector(orm.vector) if isinstance(orm.vector, str) else orm.vector
            ),
            "title": orm.title,
            "short_description": orm.short_description,
            "payload_template": orm.payload_template,
            "payload_slots": orm.payload_slots or {},
            "multi_turn_sequence": orm.multi_turn_sequence,
            "slot_requirements": orm.slot_requirements,
            "synthesized": orm.synthesized,
            "derived_from_primitive_id": orm.derived_from_primitive_id,
            "target_models_claimed": orm.target_models_claimed or [],
            "claimed_success_rate": orm.claimed_success_rate,
            "claimed_first_seen": orm.claimed_first_seen,
            "reproducibility_score": orm.reproducibility_score,
            "requires_multi_turn": orm.requires_multi_turn,
            "requires_system_prompt_access": orm.requires_system_prompt_access,
            "requires_tools": orm.requires_tools or [],
            "requires_multimodal": orm.requires_multimodal,
            "discovered_at": orm.discovered_at,
            "base_severity": (
                Severity(orm.base_severity)
                if isinstance(orm.base_severity, str)
                else orm.base_severity
            ),
            "severity_rationale": orm.severity_rationale,
            "notes": orm.notes,
            # Provenance: nested objects (SourceProvenance), inlined per
            # §11.3.5 so each JSONL line is fully self-describing.
            "sources": [
                {
                    "url": s.url,
                    "source_type": s.source_type,
                    "author": s.author,
                    "published_at": s.published_at,
                    "fetched_at": s.fetched_at,
                    "archive_hash": s.archive_hash,
                    "bright_data_product": s.bright_data_product,
                }
                for s in (orm.sources or [])
            ]
            or [
                # Replay placeholder for synthesized rows that don't have
                # a real harvested source (escalation/mutation children).
                {
                    "url": f"https://rogue.internal/replay/{orm.primitive_id}",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": orm.discovered_at,
                    "archive_hash": "synth-placeholder",
                    "bright_data_product": "fixture",
                },
            ],
        },
    )


def _bucket_for(primitive: AttackPrimitive) -> str:
    """Decide which JSONL file this primitive belongs in.

    Returns one of: ``"harvested"`` / ``"derived"`` / ``"quarantined"``.
    Pure function — no DB access — so it's easy to unit-test the
    splitting policy.
    """
    if not primitive.canonical:
        return "quarantined"
    if primitive.synthesized:
        return "derived"
    return "harvested"


def _write_jsonl(
    primitives: list[AttackPrimitive], path: Path,
) -> FileStats:
    """Write one Pydantic AttackPrimitive per line to ``path``. Returns
    file-level stats for the summary print."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = FileStats(filename=path.name)
    with path.open("w", encoding="utf-8") as f:
        for p in primitives:
            # `model_dump_json` produces a compact one-line JSON. Pydantic
            # handles datetime → ISO-8601 string automatically.
            line = p.model_dump_json()
            f.write(line)
            f.write("\n")
            stats.n_rows += 1
            stats.families.add(p.family.value)
            for s in p.sources:
                stats.source_urls.add(s.url)
    stats.size_bytes = path.stat().st_size
    return stats


# Dataset card (HuggingFace renders this as `README.md`). Template derived
# from §A.29 with the §10.7 derived-file row added + the canonical/derived
# split language clarified.
_DATASET_README_TEMPLATE = """---
license: mit
language: [en]
tags: [llm-security, jailbreak, prompt-injection, red-team, threat-intelligence]
pretty_name: ROGUE Attacks {period}
size_categories: [n<1K]
extra_gated_heading: "Request access to ROGUE Attacks"
extra_gated_prompt: >-
  This dataset contains real LLM jailbreak and prompt-injection attack
  primitives harvested from the open web. Access is granted for DEFENSIVE
  security research only (red-teaming your own deployments, building
  guardrails, academic study). By requesting access you agree to the terms
  below. Your submitted details are recorded so the maintainer knows who
  holds the data.
extra_gated_fields:
  Name: text
  Affiliation / Organization: text
  Email: text
  Intended use: text
  I will use this dataset only for defensive security research: checkbox
  I will not redistribute the raw attack payloads: checkbox
extra_gated_button_content: "Request access"
---

# ROGUE Attacks {period}

Continuous-harvest dataset of LLM attack primitives discovered across
Reddit, X, arXiv, GitHub, security blogs, MITRE ATLAS, and OWASP LLM Top
10. Each primitive is a portable, slot-templated attack pattern with
reproducibility score, severity, source provenance (URL + Bright Data
product used), and family classification.

License: MIT. Built by ROGUE, a Bright Data × lablab.ai hackathon
submission (May 2026). Powered by Bright Data.

## Schema — three JSON Lines files

Three files in this dataset, split for **honest provenance**
(§10.7 ROGUE plan):

- **`rogue-attacks-{period}.jsonl`** — `{n_harvested}` canonical primitives
  HARVESTED from the open web. Each row is one ROGUE `AttackPrimitive`
  Pydantic dump with `SourceProvenance` inlined. These are the primitives
  ROGUE actively reproduces against deployment configs.

- **`rogue-attacks-derived-{period}.jsonl`** — `{n_derived}` canonical
  primitives SYNTHESIZED by ROGUE's augmentation layer (multi-turn
  Crescendo-style escalation + AutoDAN-reframed surface mutation). Each
  row carries `derived_from_primitive_id` pointing back at its harvested
  parent so the research community can audit the synthesis chain.
  `synthesized = true` on every row in this file.

- **`quarantined-attacks-{period}.jsonl`** — `{n_quarantined}` non-canonical
  primitives. These failed dedup or were quarantined under the §3.5
  budget-conditional gate (low `reproducibility_score` harvested while
  daily Bright Data spend exceeded $25). Conceptually valid (technique
  descriptions, low-confidence extractions, attacks described without
  concrete payloads) but not actively reproduced. Included for
  research-community honesty about the actual state of the public
  discourse.

Each line in all three files mirrors the ROGUE `AttackPrimitive` schema.
The `payload_embedding` column (1536-d OpenAI `text-embedding-3-small`)
is intentionally stripped — it's regenerable in 30s and not safe for
redistribution.

## Usage

```python
import json

with open("rogue-attacks-{period}.jsonl") as f:
    primitives = [json.loads(line) for line in f]

# Pretty-print the first attack
import pprint
pprint.pp(primitives[0])

# Filter to a specific family
indirect = [p for p in primitives if p["family"] == "indirect_prompt_injection"]
```

The 15-family taxonomy + 7-vector taxonomy are documented in the ROGUE
README (linked below). Severity is computed as
`family_weight × vector_weight × any_breach_rate`.

## Provenance

Generated by `scripts/export_huggingface_dataset.py` on {generated_at}.
Dataset corresponds to the `attack_primitives` table snapshot at that
timestamp. Total: `{n_total}` primitives across all three files.

## Citation

```bibtex
@misc{{rogue_attacks_{period_underscore},
  author = {{Obounou Nguia, Soren}},
  title  = {{ROGUE Attacks {period}: A Continuous-Harvest Dataset of LLM Attack Primitives}},
  year   = 2026,
  url    = {{https://huggingface.co/datasets/<handle>/rogue-attacks-{period}}}
}}
```
"""


def _build_dataset_readme(*, period: str, stats: ExportStats) -> str:
    """Render the dataset README markdown with this run's row counts inlined."""
    return _DATASET_README_TEMPLATE.format(
        period=period,
        period_underscore=period.replace("-", "_"),
        n_harvested=stats.harvested.n_rows,
        n_derived=stats.derived.n_rows,
        n_quarantined=stats.quarantined.n_rows,
        n_total=stats.total_rows(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ----- Main export -----


def export_dataset(
    *,
    database_url: str,
    output_dir: Path,
    period_tag: str,
) -> ExportStats:
    """Read attack_primitives, bucket, write 3 JSONL files + README.

    Returns ExportStats — caller prints the summary + optionally uploads.
    """
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    buckets: dict[str, list[AttackPrimitive]] = {
        "harvested": [],
        "derived": [],
        "quarantined": [],
    }
    try:
        with SessionLocal() as session:
            orms = list(
                session.execute(
                    select(AttackPrimitiveORM).order_by(
                        AttackPrimitiveORM.discovered_at,
                    ),
                ).scalars(),
            )
            for orm in orms:
                try:
                    p = _orm_to_pydantic(orm)
                except Exception as exc:
                    logger.warning(
                        "skipping primitive %s — Pydantic projection failed: %s",
                        orm.primitive_id, exc,
                    )
                    continue
                buckets[_bucket_for(p)].append(p)
    finally:
        engine.dispose()

    harvested_path = output_dir / f"rogue-attacks-{period_tag}.jsonl"
    derived_path = output_dir / f"rogue-attacks-derived-{period_tag}.jsonl"
    quarantined_path = output_dir / f"quarantined-attacks-{period_tag}.jsonl"
    readme_path = output_dir / "README.md"

    stats = ExportStats(
        harvested=_write_jsonl(buckets["harvested"], harvested_path),
        derived=_write_jsonl(buckets["derived"], derived_path),
        quarantined=_write_jsonl(buckets["quarantined"], quarantined_path),
        derived_parent_count=len(
            {
                p.derived_from_primitive_id
                for p in buckets["derived"]
                if p.derived_from_primitive_id is not None
            },
        ),
    )

    readme_path.write_text(
        _build_dataset_readme(period=period_tag, stats=stats),
        encoding="utf-8",
    )

    return stats


def upload_to_huggingface(
    *,
    output_dir: Path,
    period_tag: str,
    hf_repo: str,
    hf_token: str | None = None,
) -> None:
    """Optional Day-4 polish: push the dataset to a HuggingFace repo.

    Requires ``huggingface_hub`` installed and either ``HF_TOKEN`` env
    var or the explicit ``hf_token`` arg. Repo must already exist (run
    ``huggingface-cli repo create rogue-attacks-{period} --type dataset``
    once before the first upload).

    Uploads all 4 files: 3 JSONLs + README.md. ``HfApi.upload_file`` is
    idempotent — re-running just overwrites the prior upload.
    """
    try:
        from huggingface_hub import HfApi  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub not installed — `pip install huggingface-hub` "
            "before using --upload",
        ) from exc

    api = HfApi(token=hf_token or os.environ.get("HF_TOKEN"))
    for fname in (
        f"rogue-attacks-{period_tag}.jsonl",
        f"rogue-attacks-derived-{period_tag}.jsonl",
        f"quarantined-attacks-{period_tag}.jsonl",
        "README.md",
    ):
        local = output_dir / fname
        if not local.exists():
            logger.warning("skip upload: %s not found", local)
            continue
        api.upload_file(
            path_or_fileobj=str(local),
            path_in_repo=fname,
            repo_id=hf_repo,
            repo_type="dataset",
        )
        logger.info("uploaded %s → %s", fname, hf_repo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "§11.3.5 HuggingFace dataset export — writes 3 JSONL files "
            "(harvested / derived / quarantined) + README dataset card."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--period-tag",
        default=datetime.now(timezone.utc).strftime("%Y-%m"),
        help="YYYY-MM tag in filenames + README. Default: current month UTC.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help=(
            "After writing files, upload to HuggingFace. Requires "
            "--hf-repo + HF_TOKEN env var."
        ),
    )
    parser.add_argument(
        "--hf-repo",
        default=None,
        help="HuggingFace repo path (e.g. 'soren/rogue-attacks-2026-05').",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    stats = export_dataset(
        database_url=args.database_url,
        output_dir=args.output_dir,
        period_tag=args.period_tag,
    )

    print()
    print("=" * 80)
    print(f"§11.3.5 HUGGINGFACE DATASET EXPORT — period={args.period_tag}")
    print("=" * 80)
    print(stats.harvested.summary())
    print(stats.derived.summary())
    print(stats.quarantined.summary())
    print("-" * 80)
    print(f"  total rows: {stats.total_rows()}")
    print(f"  derived rows trace back to {stats.derived_parent_count} distinct parents")
    print(f"  README.md: {args.output_dir / 'README.md'}")
    print()

    if args.upload:
        if not args.hf_repo:
            raise RuntimeError("--upload requires --hf-repo")
        upload_to_huggingface(
            output_dir=args.output_dir,
            period_tag=args.period_tag,
            hf_repo=args.hf_repo,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
