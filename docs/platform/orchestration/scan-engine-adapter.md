# ScanEngine — the one execution path (Team B)

> This is the single most important doc for the platform's core principle. Everything in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 reduces to one sentence: *there is exactly one place a scan executes.* That place is `rogue.scan.run_scan` (`src/rogue/scan.py:24`), which already exists and ships today. `ScanEngine` is the wrapper that lets the four surfaces — SDK, REST API, MCP, dashboard — converge on that one function without any of them reimplementing scan logic. If you find yourself writing a scan loop in this doc's code, stop: you are rebuilding the engine, and the architecture has failed (§2: "If two surfaces ever produce different results for the same target+pack, the architecture has failed").

Status: **BUILT (local).** Shipped as `DefaultScanEngine` in `src/rogue/platform/engine.py`, against the `ScanEngine` ABC in `src/rogue/platform/interfaces.py`. **Two things grew beyond this doc's original "~30-line wrapper" framing:** (1) the contract takes a whole **`ScanSpec`** (which carries the target + mode/pack/attacks/limits), not `(target, pack, config)`; and (2) the engine dispatches on `ScanSpec.mode` across **three** paths — `pack` (curated JSON pack → `run_scan`), `repertoire` (live harvested corpus → `run_scan`), and `ladder` (full escalation arsenal via `rogue.reproduce.escalation_ladder`). All three still bottom out at the same primitives + panel/judge machinery, so the one-engine invariant holds, but the ladder path is meaningfully more than a thin wrapper. The "~30 lines / Step 1–4" walk-through below describes the `pack`-mode core; read it as one of three modes.

## Where it lives

`src/rogue/platform/engine.py` — a new module, the only new file Team B adds for the engine layer. It implements the `ScanEngine` contract verbatim from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. It imports `rogue.scan`, `rogue.packs`, `rogue.benchmark`, `rogue.client`, and `rogue.reproduce.endpoint_scan`; it imports nothing that those modules don't already use. It is consumed exclusively by the worker ([`./worker.md`](./worker.md)) — never by a request handler, because a scan never runs in the request thread ([`./scan-service.md`](./scan-service.md), §4 `ScanService` docstring).

## The contract (do not redefine)

Reproduced exactly from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. This doc elaborates the implementation; it does not change the contract. If a change is needed, it changes in `ARCHITECTURE.md` first.

```python
class ScanEngine(abc.ABC):
    async def run(self, spec: ScanSpec, *, progress: ProgressCallback | None = None) -> ScanReport: ...
    async def validate(self, spec: ScanSpec) -> ValidationResult: ...
    async def benchmark(self, spec: ScanSpec, *, dataset: str, max_goals: int) -> BenchmarkReport: ...
```

(The original doc showed `run(target, pack, config, …)`; the shipped contract folds all of that into the single `ScanSpec` argument. `ProgressCallback` is `Callable[[int, int, str | None], Awaitable[None]]` — `(n_completed, n_total, current_attack)`, **async**, three args.)

`TargetSpec` and `ScanSpec` are the canonical request shapes from §5. `ScanReport` is the existing dataclass at `src/rogue/report.py:75` (`target, n_tests, n_breaches, cost_usd, findings[]`). `ValidationResult` (`src/rogue/report.py:193`) and `BenchmarkReport` (`src/rogue/report.py:236`) are likewise the existing dataclasses. The engine returns the engine's own types unchanged — persistence and the `ScanRecord`/`score` synthesis are the worker's and Team F's job, not the engine's.

## `DefaultScanEngine.run` — pack-mode core, line by line

In `pack` mode the method is four steps and a return — close to the original ~30-line shape. Each step delegates to code that already exists; none of it is scan logic. (Method/helper names below reflect the shipped `engine.py`: `_build_config`, `_adapter_extra`; the progress-panel is built inline. `repertoire`/`ladder` modes branch earlier — `_load_repertoire` / `_run_ladder` — and are not shown here.)

```python
async def run(self, spec: ScanSpec, *, progress: ProgressCallback | None = None) -> ScanReport:
    config = self._build_config(spec)                         # (1) TargetSpec -> DeploymentConfig
    if spec.mode == "ladder":
        return await self._run_ladder(spec, config, progress) # (1b) full escalation arsenal
    primitives = (self._load_repertoire(spec) if spec.mode == "repertoire"
                  else filter_attacks(load_pack(spec.pack), spec.attacks)[: spec.max_tests])  # (2)
    panel = _progress_panel(progress, len(primitives), adapter_extra=self._adapter_extra(spec))  # (3)
    report = await run_scan(config, primitives, n_trials=spec.n_trials, budget=spec.budget,
                            panel=panel, judge_model=self._judge_model)
    return report                                             # (4) ScanReport unchanged
```

Read the `pack` path against `Client.scan` (`src/rogue/client.py`): it is *the same call*. The SDK does `filter_attacks(load_pack(pack), attacks)[:max_tests]` then `run_scan(self.config, primitives, …)`. `DefaultScanEngine.run` differs in: it builds its `DeploymentConfig` from a `ScanSpec.target` instead of constructor args, it passes a progress-instrumented panel, and it adds the `repertoire`/`ladder` mode branches. The SDK and the engine are two callers of the same `run_scan`.

The api_key seam: the engine reads `spec.target.api_key` directly into `adapter_extra` (`_adapter_extra`). On the hosted path the **worker** has already resolved the `api_key_ref` handle to the raw key just-in-time (see [./worker.md](./worker.md) §2-shipped) before calling `run`, so the engine itself never touches the secret store.

### Step 1 — `TargetSpec` → `DeploymentConfig`

`TargetSpec` (§5) is `{ endpoint, provider, model, api_key_ref, system_prompt }`. There are exactly two branches, and both already have canonical implementations:

- **`endpoint` set (custom OpenAI-compatible URL).** Use `make_endpoint_config(base_url, model, system_prompt=...)` (`src/rogue/reproduce/endpoint_scan.py:88`). It builds the ephemeral `DeploymentConfig` with `base_url` set, which is what routes `run_scan` through `CustomHTTPAdapter` (`src/rogue/scan.py:4-5` docstring: "a named provider, or `CustomHTTPAdapter` when `base_url` is set"). This is the platform's headline path — "point ROGUE at a customer's inference URL — no provider account, no bespoke integration" (`endpoint_scan.py:2-9`).
- **`provider` set (known provider).** The shipped `_build_config` mirrors `Client.__init__`'s normalization inline: qualify the model as `provider/model` (or fall back to `_default_model(provider)` — the engine's own default-model helper at `engine.py:373`), leave `base_url=None`, and construct a `DeploymentConfig(config_id="plat-scan-0001", customer_id="platform", target_model=…, system_prompt=…)`. (The original doc suggested lifting a `Client(...).config` to avoid duplicating defaults; the shipped engine instead carries its own small `_default_model` map — functionally equivalent, no `Client` round-trip.)

`api_key_ref` is a secret-store *handle* (`secref_…`), never a raw secret (§5; Team C, [`../tenancy/secrets.md`](../tenancy/secrets.md)). **The engine does not resolve it** — the worker resolves the handle to a live key just-in-time and passes a `spec` carrying the raw `api_key` into `run`; `_adapter_extra` then puts it on `adapter_extra={"api_key": …}`. So the engine module never imports the secret store and never logs/persists the key.

### Step 2 — load the pack

`load_pack(pack)` (`src/rogue/packs/__init__.py:41`) loads one of the bundled packs (`default` / `aggressive` / `compliance`) into `list[AttackPrimitive]`; `filter_attacks(..., config.attacks)` (`src/rogue/packs/__init__.py:52`) narrows to the requested families (with alias resolution, e.g. `dan` → `dan_persona`); `[: config.max_tests]` caps the sweep. Identical to `Client.scan` (`src/rogue/client.py:161`). An unknown pack name raises `FileNotFoundError` (`packs/__init__.py:44`) — the worker maps that to a `failed` `ScanRecord` with a clean error envelope (§5), it does not crash the worker.

### Step 3 — call the existing engine

`run_scan(config, primitives, *, n_trials, breach_threshold, budget, adapter_extra, panel, judge, judge_model)` (`src/rogue/scan.py:24`) is the loop: `render` → `TargetPanel.run_attack` → `JudgeAgent.judge` → aggregate (`scan.py:56-110`). The engine passes a progress-instrumented `panel` and lets `run_scan` build the judge from `judge_model`. Cost reported is target-call cost; judge cost is separate (`scan.py:39-40`) — Team F's `score`/cost synthesis accounts for that.

### Step 4 — return

`run_scan` returns a `ScanReport` (`scan.py:104-110`). The engine returns it unchanged. No transformation, no persistence — the worker persists it and Team F renders it.

## The progress callback (shipped)

`ProgressCallback` is `Callable[[int, int, str | None], Awaitable[None]]` — `(n_completed, n_total, current_attack)`, **async**, three args (`src/rogue/platform/interfaces.py`). The worker passes a closure that writes `progress = int(100 * n_completed / n_total)`, `n_completed`, `n_tests`, and `top_attack=current_attack` to the `scan_runs` row each call (see [./worker.md](./worker.md) §2-shipped).

**Shipped reality — Option A (panel wrapper) was NOT used.** The original design (below) proposed a `_ProgressPanel` decorator so the proven `run_scan` loop stayed byte-for-byte unchanged. What actually shipped is different: in `pack`/`repertoire` mode `DefaultScanEngine.run` **re-implements the primitive loop inline** (`engine.py` ~lines 280–337: build/render each primitive, call `panel.run_attack` + `JudgeAgent.judge`, assemble `Finding`s, and `await progress(n_completed, n_total, technique_label(prim.family.value))` after each), rather than calling `rogue.scan.run_scan` with an injected progress panel. The `ladder` mode similarly drives `run_escalation_ladder_one` directly and fires `progress(progressed["n"], n_total, winning_strategy)`.

This is a real divergence from the "do not reimplement the scan loop" scope guard below: the engine shares the *primitives* (the same `TargetPanel`, `JudgeAgent`, `render`, `Finding`/`ScanReport` types) but not the literal `run_scan` function body. The one-engine invariant is preserved at the component level (same panel/judge/render path ⇒ same results), but the loop is duplicated. ⚑ Worth a deliberate decision: either fold the engine back onto `run_scan` (restoring Option A), or accept the duplicated loop and update the scope guard to say "share the panel/judge primitives" rather than "call `run_scan` verbatim." Today it is the latter, undocumented.

The original two-options analysis is retained below for context:

> **Option A — wrap the panel.** `run_scan` calls `panel.run_attack(...)` once per primitive; a `_ProgressPanel` decorator fires the callback on return, with zero change to `run_scan`. **Option B — an `on_progress` param on `run_scan`**, fired at the end of each loop iteration. Both keep the proven loop intact. *(Neither is what shipped; the engine grew its own loop instead — see above.)*

## `validate` and `benchmark` — same reuse discipline

- **`ScanEngine.validate(target)`** → the `Client.validate` path. Build the `DeploymentConfig`/adapter the same way Step 1 does, then run the cheap pre-flight at `src/rogue/client.py:103-138` (`_validate_async`): capabilities probe + one tiny `"Reply with the single word OK."` call, classifying reachable / authenticated / model_responds / supports_image / supports_audio. The engine's `validate` is the async core of that method; it returns the existing `ValidationResult` (`report.py:193`). No new probing logic.
- **`ScanEngine.benchmark(target, dataset, *, max_goals)`** → `run_benchmark(config, *, dataset, max_goals, adapter_extra, judge_model, panel, judge)` (`src/rogue/benchmark.py:90`). Note `run_benchmark` itself just builds synthetic goal primitives and calls `run_scan` (`benchmark.py:108-119`) — so even the benchmark path converges on the one engine. The engine returns the existing `BenchmarkReport` (`report.py:236`). Team E owns datasets/scoring ([`../benchmark/api-and-datasets.md`](../benchmark/api-and-datasets.md)); the engine only invokes.

## The crucial picture — four surfaces, one engine

Every surface is a thin client that ends at the same `run_scan`. The middle column is the de-duplication: the "four engines" anti-pattern collapses to one.

```
  SURFACE                         CONVERGENCE                         ONE ENGINE
  ---------------------------     -----------------------------       --------------------------
  SDK    Client.scan()       ┐
         client.py:142        │
                              │
  API    POST /v1/scans      ┤
         scans-endpoints.md   ├─► ScanService.create_scan ─► queue ─► ScanWorker
                              │   (scan-service.md, §4)      (job-     (worker.md)
  MCP    start_scan tool     ┤                                queue.md)    │
         integrations/mcp.md  │                                            ▼
                              │                              ScanEngine.run(target, pack,
  DASH   "Run scan" button   ┘                                config, progress)
         dashboard/...                                          engine.py  (THIS DOC)
                                                                   │
                                                                   ▼
                                                  rogue.scan.run_scan(config, primitives,
                                                    panel=, judge=, judge_model=)
                                                          src/rogue/scan.py:24   ← EXISTS
                                                                   │
                                       render ─► TargetPanel.run_attack ─► JudgeAgent.judge ─► aggregate
```

| Surface | Entry point | How it reaches the engine | Reimplements scan logic? |
|---|---|---|---|
| **SDK** | `Client.scan()` (`client.py:142`) | Calls `run_scan` directly, in-process (synchronous `asyncio.run`). Does **not** go through the worker — the SDK is the one local, non-hosted caller. | No — same `run_scan` |
| **REST API** | `POST /v1/scans` ([`../api/scans-endpoints.md`](../api/scans-endpoints.md)) | `ScanService.create_scan` enqueues a job; `ScanWorker` calls `ScanEngine.run`. Never in the request thread (§4). | No |
| **MCP** | `start_scan` tool ([`../integrations/mcp.md`](../integrations/mcp.md)) | Same `ScanService.create_scan` as the API — the MCP tool is a façade over the API contract, not a second path. | No |
| **Dashboard** | "Run scan" action ([`../dashboard/live-scan-ux.md`](../dashboard/live-scan-ux.md)) | Calls the REST API → `ScanService` → worker → `ScanEngine.run`. | No |

The hosted surfaces (API, MCP, dashboard) share one path top to bottom: `ScanService` → queue → worker → `ScanEngine.run` → `run_scan`. The SDK is the lone in-process caller — it skips the queue/worker but still bottoms out at the same `run_scan`, so results are identical. That identity is the success metric (§2, §8): same target + pack ⇒ same result, regardless of surface.

## The `base_url` ORM gap — ephemeral today, what hosted persistence needs

`DeploymentConfig` on the **Pydantic/wire side** has `base_url` (`src/rogue/schemas/deployment_config.py:53`), and the whole custom-endpoint scan rides on it (`endpoint_scan.py:96-105` sets it; `scan.py:103` and `client.py:88` read it). But the **ORM side** has no `base_url` column — a grep of `src/rogue/db/models.py` finds none. So today a custom-endpoint `DeploymentConfig` is purely **ephemeral**: `make_endpoint_config` mints an in-memory object with `config_id="adhoc-endpoint-scan"`, `customer_id="adhoc"` (`endpoint_scan.py:96-105`), it is fed to `run_scan`, and it is never persisted. The SDK and the current single-tenant API never store the target's `base_url`.

**Shipped resolution.** The hosted path closed this gap without a dedicated `targets` table or a `base_url` ORM column: the full `ScanSpec` (target's `endpoint`/`base_url`, `provider`, `model`, `system_prompt`, and the `api_key_ref` handle) is persisted as the **`scan_jobs.payload` JSON** and a redacted snapshot as the **`scan_runs.target` JSON** column (`src/rogue/platform/models.py`). The worker rehydrates the `ScanSpec` from `payload` (`ScanSpec.model_validate(...)`) and hands the engine a fully-formed `TargetSpec` — so `base_url` survives the request as JSON, not as a typed column. The engine still builds an **ephemeral** `DeploymentConfig` and never reads/writes the DB. (The original "Team C migration adds a `targets` table / `base_url` column" plan was not taken; the JSON-payload approach shipped instead.)

The boundary: the engine consumes a `TargetSpec` and builds an **ephemeral** `DeploymentConfig` exactly as the SDK does — it does not read or write the DB. Persisting the target (so the `base_url` survives the request) is data-model work owned by Team C. Flagging it here because the engine is where the ephemeral-vs-persisted seam is most visible, and a reader of this doc must not "fix" it by adding DB writes to the engine.

## What this doc must not do (scope guard)

- **Do not reimplement the scan loop.** If `engine.py` grows a `for prim in primitives` loop, it has duplicated `scan.py` — delete it and call `run_scan`.
- **Do not change the `ScanEngine`/`ScanService` contract.** Those live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. Change them there first.
- **Do not run a scan in the request thread, persist anything, or compute `score`.** Queue/worker is [`./scan-service.md`](./scan-service.md) + [`./worker.md`](./worker.md); `score` is Team F; persistence/secrets are Team C.
- **Do not add a second progress mechanism.** One `ProgressCallback`, threaded through the panel wrapper, period.
