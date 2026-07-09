# Judge calibration

Every breach number ROGUE reports is ultimately an LLM verdict, so the judge (Claude Sonnet) is validated against **independent human labels** — in-distribution on ROGUE's own traffic, and against published external safety benchmarks — rather than trusted on faith. The calibration runner enforces a locked ship/refine agreement gate, and the recalibrated rubric grades every new scan / report / MCP verdict.

*The full calibration methodology, the field-standard comparison, and the detailed figures are written up in a paper currently under **anonymized double-blind review**. To preserve submission anonymity, the specific results, tables, and reproduction pointers are withheld from this page until the review completes, and will be restored afterward.*

Calibration is reproducible from `scripts/calibration/` against the frozen data under `data/calibration/`.
