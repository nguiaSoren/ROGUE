"""``rogue.memory`` — Surface 3, the *assured substrate* for shared agent memory.

Framing discipline (spec ``docs/v2/surface3_memory_spec.md`` §1, build plan
``docs/v2/build/08_surface3_memory.md`` §0): **the pool is plumbing; the
assurance is the product.** This package exists so there is a shared skill pool
to *measure and attest*, NOT to make coding faster or to sell retrieval quality
/ authoring UX.

The API surface is therefore restricted to **ingest / promote / verify / scope**
only. There is deliberately **no** "inject the best skill" / "make this task
faster" entry point — that would re-frame the substrate as a productivity tool
and is out of scope by construction (spec §1; risk register §11 "framing drift").

This module (Sections B + G) owns:

- ``pool.SkillPool`` — ingest candidates (embed + dedup-cluster against active
  skills in the same cohort, REUSING ``rogue.dedupe.embeddings.Deduplicator``)
  and ``retrieve`` active skills for a cohort (the carrier for the verification
  rollouts and the lazy-gate retrieval-pressure counter — *not* pitched as
  retrieval).
- ``cohorts`` — cohort / trust-boundary resolution over ``org_id`` (REUSING
  ``rogue.platform.tenancy``) and the **trust-boundary isolation** enforcement
  (Section G, built out): a skill is retrievable/promotable ONLY within its
  ``cohort_id`` / ``trust_domain``; cross-trust-domain access is DENIED.

Importing this package opens NO database connection and requires NO credentials
(the embedder and the session/store are injected, same convention as
``Deduplicator``).
"""

from __future__ import annotations

__all__: list[str] = []
