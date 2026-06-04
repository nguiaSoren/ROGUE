# ScanEngine — the one execution path (Team B)

> This is the single most important doc for the platform's core principle. Everything in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 reduces to one sentence: *there is exactly one place a scan executes.* That place is `rogue.scan.run_scan` (`src/rogue/scan.py:24`), which already exists and ships today. `ScanEngine` is the thin, ~30-line wrapper that lets the four surfaces — SDK, REST API, MCP, dashboard — converge on that one function without any of them reimplementing scan logic. If you find yourself writing a scan loop in this doc's code, stop: you are rebuilding the engine, and the architecture has failed (§2: "If two surfaces ever produce different results for the same target+pack, the architecture has failed").

## Where it lives

`src/rogue/platform/engine.py` — a new module, the only new file Team B adds for the engine layer. It implements the `ScanEngine` contract verbatim from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. It imports `rogue.scan`, `rogue.packs`, `rogue.benchmark`, `rogue.client`, and `rogue.reproduce.endpoint_scan`; it imports nothing that those modules don't already use. It is consumed exclusively by the worker ([`./worker.md`](./worker.md)) — never by a request handler, because a scan never runs in the request thread ([`./scan-service.md`](./scan-service.md), §4 `ScanService` docstring).

## The contract (do not redefine)

Reproduced exactly from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. This doc elaborates the implementation; it does not change the contract. If a change is needed, it changes in `ARCHITECTURE.md` first.

```python
class ScanEngine:
    async def run(self, target: TargetSpec, pack: str, config: ScanConfig,
                  *, progress: ProgressCallback | None = None) -> ScanReport: ...
    async def validate(self, target: TargetSpec) -> ValidationResult: ...
    async def benchmark(self, target: TargetSpec, dataset: str, *, max_goals: int) -> BenchmarkReport: ...
```

`TargetSpec` and `ScanSpec` are the canonical request shapes from §5. `ScanReport` is the existing dataclass at `src/rogue/report.py:75` (`target, n_tests, n_breaches, cost_usd, findings[]`). `ValidationResult` (`src/rogue/report.py:193`) and `BenchmarkReport` (`src/rogue/report.py:236`) are likewise the existing dataclasses. The engine returns the engine's own types unchanged — persistence and the `ScanRecord`/`score` synthesis are the worker's and Team F's job, not the engine's.

## `ScanEngine.run` — the ~30-line wrapper, line by line

The whole method is four steps and a return. Each step delegates to code that already exists; none of it is scan logic.

```python
async def run(self, target: TargetSpec, pack: str, config: ScanConfig,
              *, progress: ProgressCallback | None = None) -> ScanReport:
    # (1) TargetSpec -> DeploymentConfig
    dc = _deployment_config_from_target(target)

    # (2) load the bundled attack pack, then apply ScanConfig filters/caps
    primitives = filter_attacks(load_pack(pack), config.attacks)[: config.max_tests]

    # (3) wire a progress-instrumented panel/judge, call the EXISTING engine
    panel = _progress_panel(progress, len(primitives), adapter_extra=_adapter_extra(target))
    report = await run_scan(
        dc, primitives,
        n_trials=config.n_trials,
        budget=config.budget,
        panel=panel,                 # <- the only seam where progress is threaded
        judge_model=config.judge_model,
    )
    # (4) return the engine's ScanReport unchanged
    return report
```

Read that against `Client.scan` (`src/rogue/client.py:142-172`): it is *the same call*. The SDK does `filter_attacks(load_pack(pack), attacks)[:max_tests]` then `run_scan(self.config, primitives, n_trials=, budget=, adapter_extra=, judge=, judge_model=)`. `ScanEngine.run` differs in exactly two ways: it builds its `DeploymentConfig` from a `TargetSpec` instead of from constructor args, and it passes a progress-instrumented panel. Everything else is identical reuse. This is the de-duplication made concrete — the SDK and the engine are not two implementations, they are two callers of the same `run_scan`.

### Step 1 — `TargetSpec` → `DeploymentConfig`

`TargetSpec` (§5) is `{ endpoint, provider, model, api_key_ref, system_prompt }`. There are exactly two branches, and both already have canonical implementations:

- **`endpoint` set (custom OpenAI-compatible URL).** Use `make_endpoint_config(base_url, model, system_prompt=...)` (`src/rogue/reproduce/endpoint_scan.py:88`). It builds the ephemeral `DeploymentConfig` with `base_url` set, which is what routes `run_scan` through `CustomHTTPAdapter` (`src/rogue/scan.py:4-5` docstring: "a named provider, or `CustomHTTPAdapter` when `base_url` is set"). This is the platform's headline path — "point ROGUE at a customer's inference URL — no provider account, no bespoke integration" (`endpoint_scan.py:2-9`).
- **`provider` set (known provider).** Mirror `Client.__init__`'s provider branch (`src/rogue/client.py:67-89`): qualify the model as `provider/model` (or fall back to `_DEFAULT_MODELS`), leave `base_url=None`, and build a `DeploymentConfig` with `target_model=` set. We do not duplicate `_DEFAULT_MODELS`; the cleanest implementation is for `_deployment_config_from_target` to construct a `Client(...)` and lift its `.config` — the SDK already does exactly this normalization, including the `provider/model` prefixing and the default-model lookup. Reusing `Client` here means the provider-resolution rules can never drift between SDK and platform.

`api_key_ref` is a Vault/KMS *handle*, never a raw secret (§5; Team C, [`../tenancy/secrets.md`](../tenancy/secrets.md)). The engine resolves it to a live key only at the moment it builds `adapter_extra={"api_key": ...}` for the panel, and never logs or persists it. Resolution is a call into Team C's secrets layer; the engine receives the resolved key from the worker's call context, so the engine module itself never imports the KMS client.

### Step 2 — load the pack

`load_pack(pack)` (`src/rogue/packs/__init__.py:41`) loads one of the bundled packs (`default` / `aggressive` / `compliance`) into `list[AttackPrimitive]`; `filter_attacks(..., config.attacks)` (`src/rogue/packs/__init__.py:52`) narrows to the requested families (with alias resolution, e.g. `dan` → `dan_persona`); `[: config.max_tests]` caps the sweep. Identical to `Client.scan` (`src/rogue/client.py:161`). An unknown pack name raises `FileNotFoundError` (`packs/__init__.py:44`) — the worker maps that to a `failed` `ScanRecord` with a clean error envelope (§5), it does not crash the worker.

### Step 3 — call the existing engine

`run_scan(config, primitives, *, n_trials, breach_threshold, budget, adapter_extra, panel, judge, judge_model)` (`src/rogue/scan.py:24`) is the loop: `render` → `TargetPanel.run_attack` → `JudgeAgent.judge` → aggregate (`scan.py:56-110`). The engine passes a progress-instrumented `panel` and lets `run_scan` build the judge from `judge_model`. Cost reported is target-call cost; judge cost is separate (`scan.py:39-40`) — Team F's `score`/cost synthesis accounts for that.

### Step 4 — return

`run_scan` returns a `ScanReport` (`scan.py:104-110`). The engine returns it unchanged. No transformation, no persistence — the worker persists it and Team F renders it.

## The progress callback — the one minimal additive change to `run_scan`

Today `run_scan` has **no** progress hook: it loops over primitives (`scan.py:57`) and only the final `ScanReport` is observable. The worker, though, must update `ScanRecord.progress (0-100)` and `n_completed` (§5) so the dashboard's live-scan UX ([`./scan-service.md`](./scan-service.md), [`../dashboard/live-scan-ux.md`](../dashboard/live-scan-ux.md)) can show a moving bar. We need per-primitive granularity, and we want it without touching the scan loop's logic.

Two options were considered.

**Option A — wrap the panel (preferred; zero change to `run_scan`).** `run_scan` calls `panel.run_attack(rendered, config, n_trials=...)` once per primitive (`scan.py:61`). `TargetPanel.run_attack` is at `src/rogue/reproduce/target_panel.py:170`. Wrap the real panel in a thin decorator whose `run_attack` calls through, then fires the progress callback on return:

```python
class _ProgressPanel:
    def __init__(self, inner, total, on_progress):
        self._inner, self._total, self._cb, self._done = inner, total, on_progress, 0
    async def run_attack(self, rendered, config, **kw):
        responses = await self._inner.run_attack(rendered, config, **kw)
        self._done += 1
        if self._cb:
            self._cb(self._done, self._total)   # n_completed, n_tests
        return responses
    async def aclose(self):
        await self._inner.aclose()
```

`run_scan` already accepts an injected `panel` (`scan.py:33,47-49`) and honors `owns_panel`/`aclose()` (`scan.py:47,98-100`), so the wrapper drops in with **no change to `run_scan` at all**. `ProgressCallback` is `Callable[[int, int], None]` (`(n_completed, n_tests)`); the worker derives `progress = round(100 * n_completed / n_tests)`. This is the recommended design: the engine stays a wrapper, the proven loop is untouched, and the seam is exactly the panel injection the engine already uses.

**Option B — an `on_progress` param on `run_scan` (rejected as the default).** Add an optional `on_progress: Callable[[int, int], None] | None = None` and fire it at the end of each loop iteration (after the `findings.append` at `scan.py:97`). Strictly additive and defaulting to `None` keeps the existing 19-test suite green and every current caller unchanged. It is marginally more direct, but it edits the engine's hot path for an observability concern that Option A satisfies from outside. Choose Option B only if a future need arises for sub-primitive progress (per-trial) that the panel wrapper can't express. For Week-1, ship Option A.

Either way the rule holds: the callback is *additive and optional*, the scan logic is byte-for-byte the same, and `progress=None` (the SDK path) is exactly today's behavior.

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

For hosted, multi-tenant scanning this gap must close, but **not** by the engine — the engine stays ephemeral-config-only. The gap is Team C's:

- A persisted target needs `base_url` (and `provider`, `model`, `system_prompt`, `api_key_ref`) stored on a tenant-scoped row so a `TargetSpec` can be reconstructed for a re-run, an audit, or a trend. Today there is nowhere to put `base_url`.
- This is a Team C migration (0022+), specified in [`../tenancy/data-model.md`](../tenancy/data-model.md): a `targets` (or columns on `deployment_configs`) addition carrying `base_url` + the `api_key_ref` handle, org/project-scoped. The engine then receives a fully-formed `TargetSpec` from the worker and never touches the table.

The boundary: the engine consumes a `TargetSpec` and builds an **ephemeral** `DeploymentConfig` exactly as the SDK does — it does not read or write the DB. Persisting the target (so the `base_url` survives the request) is data-model work owned by Team C. Flagging it here because the engine is where the ephemeral-vs-persisted seam is most visible, and a reader of this doc must not "fix" it by adding DB writes to the engine.

## What this doc must not do (scope guard)

- **Do not reimplement the scan loop.** If `engine.py` grows a `for prim in primitives` loop, it has duplicated `scan.py` — delete it and call `run_scan`.
- **Do not change the `ScanEngine`/`ScanService` contract.** Those live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4. Change them there first.
- **Do not run a scan in the request thread, persist anything, or compute `score`.** Queue/worker is [`./scan-service.md`](./scan-service.md) + [`./worker.md`](./worker.md); `score` is Team F; persistence/secrets are Team C.
- **Do not add a second progress mechanism.** One `ProgressCallback`, threaded through the panel wrapper, period.
