"""Back-compat shim — the escalation-ladder + synthesis core moved into the package.

It now lives at ``rogue.reproduce.escalation_ladder`` so the deployed platform worker can import it
(``scripts/`` isn't on the worker's ``PYTHONPATH``, and ``src/rogue`` importing ``scripts`` was a
backwards layering dependency). Everything is re-exported here so existing callers
(``from scripts.reproduce.synthesize_escalations import …`` in benchmark_run / reproduce_once / the tests / the
other synth scripts) keep working unchanged, and ``python scripts/reproduce/synthesize_escalations.py`` still
runs the synthesis CLI.
"""

from rogue.reproduce.escalation_ladder import (  # noqa: F401  (re-export the moved public + used-private API)
    DEFAULT_BREACH_RATE_THRESHOLD,
    DEFAULT_CONCURRENCY,
    DEFAULT_LIMIT,
    DEFAULT_N_TURNS,
    ESCALATION_LADDER,
    EscalationContext,
    LadderResult,
    LadderStats,
    SynthesisStats,
    _orm_to_pydantic_primitive,
    build_escalation_context,
    main,
    run_escalation_ladder,
    run_escalation_ladder_one,
    run_synthesis,
)

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
