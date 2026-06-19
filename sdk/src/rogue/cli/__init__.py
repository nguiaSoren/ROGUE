"""The ``rogue`` command-line interface (Deliverable 9).

A thin argparse wrapper over the public SDK (:class:`rogue.Rogue`). Every command builds one
``Rogue`` instance from the global flags and calls the same methods a library user would.

    from rogue.cli.main import main
    raise SystemExit(main())
"""

from .main import main

__all__ = ["main"]
