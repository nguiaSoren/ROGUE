"""Executable enforcement of the Week-1 core layering rules (ARCHITECTURE.md §4).

Rules 1 and 2 are statically checkable, so we make them tests instead of trusting code
review forever:

  Rule 1 — no file under ``src/rogue/core/`` may import a provider SDK at module level.
  Rule 2 — no file under ``src/rogue/core/`` may import ANYTHING from ``rogue.adapters`` at
           module load — not the package, not a concrete adapter, not even the abstract
           ``rogue.adapters.base`` contract. ``core`` depends on ``adapters`` only lazily:
           ``registry.py`` (in-function + ``TYPE_CHECKING``) and ``conformance.py``
           (``TYPE_CHECKING`` type hints) both reference ``TargetAdapter`` without a module-load
           import, so both PASS. The rule is uniform — there is no allowed exception, which keeps
           the layering invariant a single sentence with no asterisks.

The check is AST-based (robust; not regex). A positive control proves the scanner itself
detects a forbidden import, so a broken scanner can't make the suite silently green.

Dependency-free: stdlib ``ast`` + ``pathlib`` only. No async.
"""

from __future__ import annotations

import ast
from pathlib import Path

# --------------------------------------------------------------------------------------------------
# Locate the core package relative to this test file (no install / sys.path assumptions).
# --------------------------------------------------------------------------------------------------
CORE_DIR = Path(__file__).resolve().parents[1] / "src" / "rogue" / "core"

# Root top-level modules that mean "a provider SDK leaked into core" (Rule 1).
# ``httpx`` is intentionally NOT here: it is transport-neutral and allowed anywhere.
FORBIDDEN_SDKS = frozenset(
    {
        "openai",
        "anthropic",
        "google",  # google-generativeai / google-genai
        "googleapiclient",
        "vertexai",
        "groq",
        "mistralai",
        "cohere",
        "boto3",  # AWS Bedrock
    }
)

# The adapter package that core must not import at module load (Rule 2) — uniformly, including
# the abstract `rogue.adapters.base` contract. core references adapters only lazily / TYPE_CHECKING.
ADAPTERS_MODULE = "rogue.adapters"


# --------------------------------------------------------------------------------------------------
# Scanner helpers (unit-testable in isolation).
# --------------------------------------------------------------------------------------------------
def _root_module(name: str) -> str:
    """First dotted component of a module path: ``google.generativeai`` -> ``google``."""
    return name.split(".", 1)[0]


def _provider_imports(tree: ast.AST, forbidden: frozenset[str] | set[str]) -> set[str]:
    """Every forbidden provider-SDK root module imported anywhere in ``tree``.

    Walks the whole AST (not just module top level) so an import smuggled inside a
    function body is still caught — a provider SDK has no business anywhere in core.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root_module(alias.name) in forbidden:
                    found.add(_root_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            # Absolute import only; relative (node.level > 0) can't reach a top-level SDK.
            if node.level == 0 and node.module and _root_module(node.module) in forbidden:
                found.add(_root_module(node.module))
    return found


def _module_level_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Import statements at module top level, EXCLUDING those inside a ``TYPE_CHECKING`` block.

    Imports nested in function/class bodies or under ``if TYPE_CHECKING:`` are not module-load
    imports and therefore don't violate the acyclic-graph rule.
    """
    out: list[ast.Import | ast.ImportFrom] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(node)
        elif isinstance(node, ast.If) and _is_type_checking_guard(node.test):
            # Skip the body of `if TYPE_CHECKING:` — those imports never run at load time.
            continue
    return out


def _is_type_checking_guard(test: ast.expr) -> bool:
    """True for ``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` test expressions."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _adapter_targets(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    """Fully-qualified ``rogue.adapters[...]`` targets ``node`` imports at module load.

    Normalizes both the absolute dotted form (``import rogue.adapters.foo`` /
    ``from rogue.adapters.foo import X``) and the project-relative form used inside
    ``src/rogue/core/`` (``from ..adapters.foo import X`` / ``from .. import adapters``) to the
    same canonical ``rogue.adapters[.sub]`` strings, so the caller can apply the Rule-2 policy
    (and its ``adapters.base`` exception) uniformly. Returns ``[]`` when ``node`` touches no
    adapter module.
    """
    leaf = package.rsplit(".", 1)[-1]  # "adapters"
    out: list[str] = []

    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == package or alias.name.startswith(package + "."):
                out.append(alias.name)
        return out

    # ImportFrom -------------------------------------------------------------------------------
    if node.level == 0:
        mod = node.module or ""
        if mod == package or mod.startswith(package + "."):
            out.append(mod)
        return out

    # Relative import from within rogue.core (level 2 == the `rogue` package root):
    #   `from ..adapters.base import X`  -> module == "adapters.base"
    #   `from ..adapters import X`       -> module == "adapters"
    #   `from .. import adapters`        -> module is None, alias "adapters"
    if node.level == 2:
        mod = node.module
        if mod == leaf or (mod or "").startswith(leaf + "."):
            # rebase "adapters[.sub]" onto the full "rogue.adapters[.sub]"
            out.append(package + mod[len(leaf):])  # type: ignore[union-attr]
        elif mod is None and any(alias.name == leaf for alias in node.names):
            out.append(package)
    return out


def _imports_forbidden_adapter(node: ast.Import | ast.ImportFrom) -> bool:
    """Rule 2: ``node`` imports anything from ``rogue.adapters`` at module load (no exceptions)."""
    return bool(_adapter_targets(node, ADAPTERS_MODULE))


def _core_py_files() -> list[Path]:
    files = sorted(CORE_DIR.rglob("*.py"))
    # Exclude caches just in case rglob surfaces them; never empty in a healthy checkout.
    return [p for p in files if "__pycache__" not in p.parts]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --------------------------------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------------------------------
def test_core_dir_exists_and_has_files():
    """Guard: the scanner must actually have something to scan (catches a bad path)."""
    assert CORE_DIR.is_dir(), f"core dir not found at {CORE_DIR}"
    files = _core_py_files()
    assert files, f"no *.py files found under {CORE_DIR}"


def test_no_provider_sdk_imported_in_core():
    """Rule 1: no provider SDK is imported anywhere under src/rogue/core/."""
    offenders: dict[str, set[str]] = {}
    for path in _core_py_files():
        leaked = _provider_imports(_parse(path), FORBIDDEN_SDKS)
        if leaked:
            offenders[str(path.relative_to(CORE_DIR.parents[2]))] = leaked
    assert not offenders, f"provider SDK imports leaked into core: {offenders}"


def test_core_does_not_import_adapters_at_module_load():
    """Rule 2: no core module imports rogue.adapters at module top level (non-TYPE_CHECKING).

    Both registry.py (lazy in-function import + TYPE_CHECKING) and conformance.py (TYPE_CHECKING
    type hints) reference ``TargetAdapter`` without a module-load import, so both PASS. Any
    module-load import from ``rogue.adapters`` — package, concrete adapter, or ``base`` — FAILS.
    """
    offenders: list[str] = []
    for path in _core_py_files():
        tree = _parse(path)
        for node in _module_level_imports(tree):
            if _imports_forbidden_adapter(node):
                offenders.append(str(path.relative_to(CORE_DIR.parents[2])))
                break
    assert not offenders, (
        f"core modules import from {ADAPTERS_MODULE!r} at module load "
        f"(must be lazy / TYPE_CHECKING — uniform rule, no exceptions): {offenders}"
    )


# --- positive controls: prove the scanner actually works ------------------------------------------
def test_scanner_detects_forbidden_import_positive_control():
    """If the scanner is broken, every Rule-1 test passes vacuously. Prevent that."""
    snippet = "import openai\nfrom anthropic import Anthropic\nimport httpx\n"
    found = _provider_imports(ast.parse(snippet), FORBIDDEN_SDKS)
    assert "openai" in found
    assert "anthropic" in found
    assert "httpx" not in found  # transport-neutral, allowed


def test_scanner_detects_dotted_provider_import():
    """Dotted provider imports (google.generativeai) must resolve to the root module."""
    found = _provider_imports(ast.parse("import google.generativeai as genai\n"), FORBIDDEN_SDKS)
    assert "google" in found


def test_scanner_ignores_type_checking_and_nested_adapter_imports():
    """The Rule-2 module-level filter must skip TYPE_CHECKING blocks and function-body imports."""
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from rogue.adapters import MockAdapter\n"  # concrete + package init: would FAIL at module level
        "def make():\n"
        "    from rogue.adapters import registry\n"
        "    return registry\n"
    )
    tree = ast.parse(src)
    flagged = any(_imports_forbidden_adapter(n) for n in _module_level_imports(tree))
    assert not flagged, "TYPE_CHECKING / nested adapter imports must not be flagged as module-level"


def test_scanner_flags_module_level_adapters_base_import():
    """Uniform Rule 2: even the abstract ``rogue.adapters.base`` is forbidden at module load."""
    abs_tree = ast.parse("from rogue.adapters.base import TargetAdapter, AdapterConfig\n")
    rel_tree = ast.parse("from ..adapters.base import TargetAdapter\n")
    assert any(_imports_forbidden_adapter(n) for n in _module_level_imports(abs_tree))
    assert any(_imports_forbidden_adapter(n) for n in _module_level_imports(rel_tree))


def test_scanner_flags_real_module_level_adapter_package_import():
    """It MUST flag a genuine module-load import of the adapters package / a concrete adapter."""
    pkg_abs = ast.parse("import rogue.adapters\n")
    pkg_from = ast.parse("from rogue.adapters import MockAdapter\n")
    pkg_rel = ast.parse("from .. import adapters\n")
    concrete = ast.parse("from rogue.adapters.mock import MockAdapter\n")
    concrete_rel = ast.parse("from ..adapters.openai import OpenAIAdapter\n")
    for tree in (pkg_abs, pkg_from, pkg_rel, concrete, concrete_rel):
        assert any(_imports_forbidden_adapter(n) for n in _module_level_imports(tree))


# --- public surface -------------------------------------------------------------------------------
def test_core_imports_cleanly_and_exposes_public_names():
    """rogue.core imports without dragging in adapters/SDKs, and exports the documented names."""
    import rogue.core as core

    expected = {
        "CanonicalMessage",
        "MessageRole",
        "from_legacy_messages",
        "to_legacy_messages",
        "ContentBlock",
        "TextBlock",
        "ImageBlock",
        "AudioBlock",
        "ToolCallBlock",
        "ToolResultBlock",
        "Attachment",
        "sniff_mime",
        "InvocationResult",
        "UsageMetrics",
        "StopReason",
        "TargetCapabilities",
        "AdapterRegistry",
        "registry",
        "AdapterError",
        "AuthenticationError",
        "RateLimitError",
        "TimeoutError",
        "ProviderError",
        "ValidationError",
        "ContentPolicyError",
        "from_http_status",
        "is_retryable",
    }
    missing = expected - set(core.__all__)
    assert not missing, f"rogue.core.__all__ missing documented names: {missing}"
    for name in expected:
        assert hasattr(core, name), f"rogue.core does not expose {name!r}"
