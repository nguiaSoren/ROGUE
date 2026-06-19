# ROGUE core — the provider-neutral substrate (Week 1)

> **The one invariant:** *No provider-specific types live above the `adapters/` layer.* If you remember nothing else from this document, remember that sentence. Every rule below is a corollary of it, and the layering test (`tests/test_core_layering.py`) makes the load-bearing parts of it executable.

## 1. Purpose

Week 1 produces the provider-neutral substrate — and nothing else. There are zero business features in this layer: no scan engine, no harvest, no judge, no benchmark, no threat brief. That is deliberate. This is the layer with the maximum leverage and the longest blast radius: every future adapter, every SDK we wrap, every API route, every scan, every benchmark run, and every customer deployment config will sit on top of it. If the substrate is right, adding OpenAI, Anthropic, Gemini, xAI, Bedrock, or a customer's bespoke endpoint is a one-line registration with zero changes above the boundary. If the substrate is wrong, every one of those touches the core and the abstraction was never real. So Week 1 buys leverage by spending it carefully: a small, frozen vocabulary that the entire rest of the system speaks, and a single seam (`TargetAdapter`) that is the only place a provider's name, SDK, wire format, or failure mode is ever allowed to appear.

Concretely, `rogue.core` defines the language ROGUE thinks in — `CanonicalMessage`, the `ContentBlock` family, `InvocationResult`, `UsageMetrics`, `StopReason`, `TargetCapabilities`, the `AdapterError` hierarchy, and the `AdapterRegistry` — and `rogue.adapters` defines the one translation seam where that language is converted to and from a specific provider. Everything ROGUE builds afterwards talks to the core types and asks the registry for an adapter; it never imports `openai`, never inspects an Anthropic response object, never branches on `if provider == "gemini"`.

## 2. The layers

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  business logic / scan engine / harvest / judge / benchmark / API / MCP    │
  │  — speaks ONLY CanonicalMessage + InvocationResult; asks the registry for  │
  │    an adapter by name; routes on capabilities, never on provider names     │
  └───────────────────────────────────┬────────────────────────────────────────┘
                                       │  builds list[CanonicalMessage],
                                       │  reads InvocationResult
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  rogue.core   (this layer — provider-neutral, frozen Week 1)               │
  │    CanonicalMessage · MessageRole                                          │
  │    ContentBlock · TextBlock · ImageBlock · AudioBlock                      │
  │                 · ToolCallBlock · ToolResultBlock · Attachment             │
  │    InvocationResult · UsageMetrics · StopReason                            │
  │    TargetCapabilities                                                       │
  │    AdapterRegistry / registry                                              │
  │    errors: AdapterError ▸ Authentication/RateLimit/Timeout/Provider/       │
  │            Validation/ContentPolicy · from_http_status · is_retryable      │
  │                                                                            │
  │    imports NO provider SDK. imports NOTHING from adapters at module load   │
  │    (registry.py: lazy in-function + TYPE_CHECKING; conformance.py:          │
  │    TYPE_CHECKING type hints). Uniform rule, no exceptions.                  │
  └───────────────────────────────────┬────────────────────────────────────────┘
                                       │  TargetAdapter.invoke(messages) ->
                                       │  InvocationResult   (the ONLY seam)
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  rogue.adapters   (the ONLY place provider SDKs are imported)              │
  │    TargetAdapter (abstract base) · AdapterConfig                           │
  │    MockAdapter (reference / conformance fixture) — registered "mock"       │
  │    [Week 2 ✓] OpenAIAdapter · AnthropicAdapter · OpenRouterAdapter ·       │
  │              GeminiAdapter · CustomHTTPAdapter · GroqAdapter · MockAdapter  │
  │    each translates CanonicalMessage <-> provider wire format and maps      │
  │    provider failures -> rogue.core.errors types                            │
  └───────────────────────────────────┬────────────────────────────────────────┘
                                       │  provider SDK calls (HTTP)
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  providers   OpenAI · Anthropic · Gemini · xAI · Groq · Bedrock · ...      │
  └──────────────────────────────────────────────────────────────────────────┘
```

The arrows point downward: each layer depends only on the layer directly below it, and the dependency is always expressed in core types. Two directionality facts are load-bearing and are enforced by the layering test. First, **core never imports a provider SDK** — not `openai`, `anthropic`, `google`/`googleapiclient`/`vertexai`, `groq`, `mistralai`, `cohere`, or `boto3`. (`httpx` is allowed in core; it is transport-neutral, not a provider.) Second, **core never imports anything from `rogue.adapters` at module load — not the package, not a concrete adapter, not even the abstract `rogue.adapters.base` contract.** The cycle to avoid is precise: `adapters/__init__.py` imports the registry to register built-ins, so if the registry imported the adapters package back, that would be a load-time cycle. core sidesteps it by reaching `TargetAdapter` only lazily: `registry.py` imports it inside `_target_adapter_cls()` (called only at `register()` time) plus a `TYPE_CHECKING` block for type hints, and `core/conformance.py` references it purely through `TYPE_CHECKING` type hints (it is duck-typed against the adapter's interface at runtime, so it needs no runtime import). The rule is therefore uniform with no exceptions, which keeps the invariant a single sentence and the enforcement test a single predicate. The net effect: you can `import rogue.core` without dragging in the adapters package, any concrete adapter, or any provider SDK.

## 3. How a message travels (the exit-criterion answer)

This is the question Week 1 exists to answer: *can a message go from ROGUE to OpenAI, to Anthropic, and to Gemini without changing ROGUE code?* Yes — and the only line that differs across the three is the provider name handed to `registry.create(...)`.

```
  ROGUE business code (identical for all three providers)
  ──────────────────────────────────────────────────────
    messages = [
        CanonicalMessage.system("You are a helpful assistant."),
        CanonicalMessage.user("Summarize this."),
    ]                                          # list[CanonicalMessage] — provider-neutral

    adapter = registry.create(provider, config)   # <-- the ONLY provider-dependent step
    result  = await adapter.invoke(messages)       # InvocationResult — provider-neutral
    print(result.text, result.usage, result.stop_reason)

                                   │
            provider = "openai"    │   provider = "anthropic"   │   provider = "gemini"
                                   ▼                            ▼                       ▼
  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
  │ OpenAIAdapter        │  │ AnthropicAdapter     │  │ GeminiAdapter        │
  │ canonical ->         │  │ canonical ->         │  │ canonical ->         │
  │  {role, content:[…]} │  │  {role, content:[…]} │  │  {parts:[…]}         │
  │ call openai sdk      │  │ call anthropic sdk   │  │ call google sdk      │
  │ response ->          │  │ response ->          │  │ response ->          │
  │  InvocationResult    │  │  InvocationResult    │  │  InvocationResult    │
  └──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
             └─────────────────────────┴─────────────────────────┘
                                   │
                                   ▼
                         InvocationResult  (same shape, every provider)
                           .content : list[ContentBlock]
                           .text    : str
                           .usage   : UsageMetrics
                           .stop_reason : StopReason
                           .raw_response : dict   (provider's untouched output, preserved)
```

The business code above is byte-for-byte identical in all three columns. `messages` is built once from canonical types; `result` is read with the same accessors regardless of who answered. **The single provider-dependent step is `registry.create(provider, config)`** — swap the string, get a different adapter, and every other line stays put. That is the whole point of the layer, and it is the Week-1 exit criterion made concrete. (Week 2 ✓: `mock`, `openai`, `anthropic`, `openrouter`, `gemini`, `custom`, `groq` are all registered — each a one-line `registry.register(...)` in `adapters/__init__.py` — and `reproduce/target_panel.py` now dispatches through them with its public `ModelResponse` / `run_attack` contract unchanged.)

## 4. The five architecture rules

These are phrased against the real symbols in this package. Rules 1 and 2 are statically enforced by `tests/test_core_layering.py`; the rest are design contracts every reviewer holds the line on.

1. **Provider SDK imports live only inside `adapters/`.** No file under `rogue/core/` may import `openai`, `anthropic`, `google`/`googleapiclient`/`vertexai`, `groq`, `mistralai`, `cohere`, or `boto3`. The provider SDK is summoned exactly once, inside the adapter that wraps it. (`httpx` is fine anywhere — it is transport, not a provider.) *Enforced by the layering test.*

2. **No provider response objects cross the boundary — only `CanonicalMessage` and `InvocationResult` do.** An OpenAI `ChatCompletion`, an Anthropic `Message`, a Gemini `GenerateContentResponse` never travel upward. The adapter normalizes the provider's reply into an `InvocationResult` (preserving the original in `raw_response` for audit/debug — we normalize, we never discard) before it returns. *Enforced, in its structural form, by the no-cross-layer-import half of the layering test.*

3. **ROGUE talks only to `CanonicalMessage` and `InvocationResult`.** Above the boundary, a request is a `list[CanonicalMessage]` and a response is an `InvocationResult`. Business code uses the ergonomic constructors (`CanonicalMessage.system/user/assistant`, `InvocationResult.text`, `.tool_calls`, `.is_refusal`) and never reaches for a provider field by name.

4. **Capabilities drive routing, not provider names.** The correct dispatch test is `if caps.supports_audio:`, never `if provider == "gemini":`. `TargetCapabilities` is the single source of truth for what a target can do, and it exposes the routing helpers `supports_block(block)`, `supports_message(message)`, `unsupported_blocks(messages)`, and `can_handle(messages)` so the engine can ask "can this target accept this payload?" without ever naming a vendor. It also carries the real numeric constraints (`max_context_tokens`, `max_output_tokens`, `max_temperature`, with `clamp_temperature(...)`) so clamps stop being per-provider special cases.

5. **Every adapter passes the same conformance suite.** A real adapter and the `MockAdapter` are interchangeable from above: if OpenAI and Anthropic both pass conformance, ROGUE cannot tell which one it is talking to. The suite lives in `rogue.core.conformance` — a single, provider-agnostic checker (`assert_adapter_conformance` / `assert_conformant`) that asserts the four-method I/O contract using only canonical types. It is duck-typed against the adapter interface (the `TargetAdapter` reference is a `TYPE_CHECKING`-only type hint), so it imports no adapter and no provider SDK at runtime — the same yardstick for the mock and for every real adapter. The `MockAdapter` is its first passing subject.

## 5. The `TargetAdapter` contract

`TargetAdapter` (in `rogue/adapters/base.py`) is the only seam ROGUE crosses to reach a model. Four required, all-async, canonical-types-only methods — no method takes or returns a provider object:

```python
class TargetAdapter(abc.ABC):
    def __init__(self, config: AdapterConfig): ...

    @property
    def model(self) -> str: ...        # config.model
    @property
    def provider(self) -> str: ...     # "openai/gpt-5" -> "openai", else <Class>Adapter -> name

    @abc.abstractmethod
    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        **kwargs,
    ) -> InvocationResult: ...
    # translate canonical -> provider wire, call provider, translate back;
    # provider failures are raised as rogue.core.errors types.

    @abc.abstractmethod
    async def capabilities(self) -> TargetCapabilities: ...   # what the target supports (drives routing)

    @abc.abstractmethod
    async def healthcheck(self) -> bool: ...                  # reachable + creds valid; no raise on clean down

    @abc.abstractmethod
    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics: ...                                    # estimate WITHOUT calling the model
```

`AdapterConfig` carries everything one adapter needs to reach one target — `model`, `api_key`, `base_url`, `timeout_s`, `max_retries`, and an `extra: dict` for provider-specific knobs. Credentials live in the config and never leave the adapter layer. The base also provides `aclose()` and async-context-manager support so adapters that hold SDK clients can release them deterministically (`async with registry.create(...) as adapter:`).

## 6. Adding a provider

One line, zero core changes:

```python
# rogue/adapters/xai.py
from ..core import registry
from .base import TargetAdapter

class XAIAdapter(TargetAdapter):
    async def invoke(self, messages, *, temperature=0.7, max_output_tokens=None, **kwargs): ...
    async def capabilities(self): ...
    async def healthcheck(self): ...
    async def estimate_cost(self, messages, *, max_output_tokens=None): ...

registry.register("xai", XAIAdapter)      # <-- the entire integration surface, above the SDK
```

(Or the decorator form: `@registry.decorator("xai")` on the class.) After that, `registry.create("xai", config)` returns an `XAIAdapter` and every line of business code that already worked against `"mock"` works against `"xai"` unchanged. Built-ins register themselves in `rogue/adapters/__init__.py` — that file is the canonical example: `registry.register("mock", MockAdapter, overwrite=True)`.

## 7. Internal → canonical mapping (the Week-2 migration target)

The core types are not greenfield abstractions; each one is the consolidation of something ROGUE already does in a scattered, provider-leaky way today. **Week 2 (shipped) migrated the reproduction layer onto them:** the provider adapters live in `adapters/{openai_compat,openai,openrouter,custom,anthropic,gemini}.py`, the scattered pricing/capability tables are consolidated in `adapters/model_specs.py`, the retry predicate + provider-exception→`AdapterError` mapping live in `adapters/_provider_errors.py`, and `target_panel.py` is now a thin dispatch layer over the registry. The mapping was mechanical:

| Today (provider-leaky)                                                                                                                                              | Canonical (this layer)                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ModelResponse` in `reproduce/target_panel.py` — flat `content: str`, `latency_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `error: str \| None`                     | `InvocationResult` — `content: list[ContentBlock]` (with `.text`), `latency_ms`, `usage: UsageMetrics` (`input_tokens`/`output_tokens`/`total_tokens`/`estimated_cost_usd`), structured errors |
| `RenderedAttack.messages: list[dict[str, str]]` (text-only `{role, content}`) **plus** out-of-band `image_b64` / `image_media_type` / `audio_b64` / `audio_format`  | `list[CanonicalMessage]` whose `content` is a list of `TextBlock` / `ImageBlock` / `AudioBlock` — multimodal payloads become first-class blocks instead of side-channel base64 strings  |
| `_IMAGE_CAPABLE_MODELS` / `_AUDIO_CAPABLE_MODELS` frozensets + `supports_image(model)` / `supports_audio(model)` functions; the Anthropic temperature clamp; the hardcoded `max_tokens=4096` | one `TargetCapabilities` per target — `supports_image` / `supports_audio` flags, `max_temperature` (via `clamp_temperature`), `max_output_tokens`, `max_context_tokens`               |
| flat `error: str` with informal prefixes (`rate_limit_exhausted:`, `content_policy_or_bad_request:`, `http_status_<n>:`)                                            | the `AdapterError` hierarchy — `AuthenticationError` / `RateLimitError` / `TimeoutError` / `ProviderError` / `ValidationError` / `ContentPolicyError`, with `retryable` and `from_http_status(...)` |

The legacy bridges are already built so the migration is low-risk: `CanonicalMessage.from_legacy_dict` / `to_legacy_dict` and the module-level `from_legacy_messages` / `to_legacy_messages` round-trip the existing `{role, content:str}` dicts, and `Attachment.from_base64(...)` plus `ImageBlock.from_attachment(...)` / `AudioBlock.from_attachment(...)` lift today's out-of-band base64 payloads into blocks.

One genuinely new concept: **ROGUE has no stop-reason today.** `ModelResponse` drops the target's finish reason on the floor (only the judge reads Anthropic's, separately). `StopReason` is new — a normalized `complete` / `length` / `tool_call` / `safety` / `error`, with `StopReason.from_provider(...)` mapping the OpenAI and Anthropic finish-reason vocabularies onto it. `InvocationResult.is_refusal` keys off `StopReason.SAFETY`, which is exactly the red-team-relevant signal (a target defending) that the flat `error` string buried.

## 8. Week-1 exit criteria

Week 1 is done when three reviews pass. They now hold against the code in this package.

- **Architecture Review — "no provider type leaks above `adapters/`."** Statically true: `tests/test_core_layering.py` walks every `*.py` under `rogue/core/` and asserts none imports a provider SDK (Rule 1) and none imports anything from `rogue.adapters` at module load (Rule 2, uniform — package, concrete adapter, or `base` alike). Both `registry.py` (lazy in-function import + `TYPE_CHECKING`) and `conformance.py` (`TYPE_CHECKING` type hints only) reference `TargetAdapter` without a module-load import, so both pass. The test is dependency-free (stdlib `ast` + `pathlib`) and includes positive controls that prove the scanner actually detects a forbidden provider SDK import and a forbidden module-load adapters import.

- **Registry Review — "add a provider = one line, zero core changes."** `registry.register("name", Adapter)` (or `@registry.decorator("name")`) is the entire integration surface above the SDK; `registry.create("name", config)` returns the adapter; `rogue/adapters/__init__.py` registers the built-in `"mock"` in exactly one line. No core file changes to add a provider — `registry.py` never names one.

- **Conformance Review — "every adapter is interchangeable from above."** The `TargetAdapter` contract is four canonical-types-only async methods, and the `MockAdapter` implements all four with no network, no randomness, and no clock — deterministic, and steerable via `AdapterConfig.extra` to exercise every capability variation and every error path. It is the reference subject for the conformance suite (Rule 5): if a real adapter passes the same suite the mock passes, ROGUE cannot tell the two apart, which is the definition of the abstraction holding.
