"""Tests for the public attack-corpus exporter (scripts/corpus/export_public_corpus.py).

Asserts the redaction policy (VIRAL_LAUNCH_SPEC Decision #3 + RESPONSIBLE_RELEASE.md):
  * novel / synthesized / non-public payloads are redacted,
  * public-source payloads are kept verbatim,
  * the measured layer is ALWAYS present,
  * output is valid JSON / JSONL.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = REPO_ROOT / "scripts" / "corpus" / "export_public_corpus.py"
SAMPLE = REPO_ROOT / "scripts" / "corpus" / "sample_snapshot.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("export_public_corpus", EXPORTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()
REDACTED = mod.REDACTED_PAYLOAD


# --------------------------------------------------------------------------- #
# Inline snapshots — small, hand-built, exercise every path.
# --------------------------------------------------------------------------- #

CONFIG = {"config_id": "c1", "target_model": "openai/gpt-4o-mini", "name": "T"}


def _snapshot(primitive: dict, sources: list[dict], breaches: list[dict]) -> dict:
    return {
        "deployment_configs": [CONFIG],
        "attack_primitives": [primitive],
        "breach_results": breaches,
        "source_provenances": sources,
    }


def _prim(pid: str, **over) -> dict:
    base = {
        "primitive_id": pid,
        "family": "direct_instruction_override",
        "secondary_families": [],
        "vector": "user_turn",
        "title": "T",
        "short_description": "d",
        "payload_template": "REAL PAYLOAD TEXT {slot}",
        "multi_turn_sequence": None,
        "target_models_claimed": [],
        "claimed_success_rate": None,
        "reproducibility_score": 5,
        "synthesized": False,
        "derived_from_primitive_id": None,
        "discovered_at": "2026-04-01T00:00:00Z",
        "base_severity": "medium",
    }
    base.update(over)
    return base


def _src(pid: str, source_type: str, url: str, **over) -> dict:
    base = {
        "primitive_id": pid,
        "url": url,
        "source_type": source_type,
        "author": "a",
        "published_at": "2026-03-01T00:00:00Z",
        "bright_data_product": "web_unlocker",
    }
    base.update(over)
    return base


def _breach(pid: str, verdict: str) -> dict:
    return {
        "primitive_id": pid,
        "deployment_config_id": "c1",
        "verdict": verdict,
        "judge_confidence": 0.9,
        "ran_at": "2026-06-10T00:00:00+00:00",
    }


# --------------------------------------------------------------------------- #
# payload_is_public detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source_type,url,expected",
    [
        ("github", "https://github.com/elder-plinius/L1B3RT4S/blob/main/X.mkd", True),
        ("arxiv", "https://arxiv.org/abs/2605.18239", True),
        ("reddit", "https://www.reddit.com/r/ChatGPT/comments/x/y/", True),
        ("blog", "https://embracethered.com/blog/posts/2026/x/", True),
        ("x", "https://x.com/someone/status/123", True),
        # public type but private/unknown host -> not public
        ("blog", "https://internal.corp.example/secret", False),
        # private channel type -> not public even on a real host
        ("discord_archive", "https://discord.com/channels/0/1/2", False),
        ("other", "https://github.com/whatever", False),
    ],
)
def test_payload_is_public_detection(source_type, url, expected):
    p = _prim("p1")
    s = [_src("p1", source_type, url)]
    assert mod.payload_is_public(p, s) is expected


def test_synthesized_is_never_public_even_with_public_parent_source():
    p = _prim("p1", synthesized=True, derived_from_primitive_id="parent")
    s = [_src("p1", "github", "https://github.com/elder-plinius/L1B3RT4S/blob/main/X.mkd")]
    assert mod.payload_is_public(p, s) is False


# --------------------------------------------------------------------------- #
# build_attacks redaction behavior
# --------------------------------------------------------------------------- #


def test_public_source_payload_is_kept_verbatim():
    snap = _snapshot(
        _prim("p1", payload_template="KEEP ME"),
        [_src("p1", "github", "https://github.com/elder-plinius/L1B3RT4S/blob/main/X.mkd")],
        [_breach("p1", "full_breach")],
    )
    [a] = mod.build_attacks(snap)
    assert a["payload_is_public"] is True
    assert a["payload"] == "KEEP ME"


def test_synthesized_payload_is_redacted():
    snap = _snapshot(
        _prim("p1", synthesized=True, derived_from_primitive_id="parent", payload_template="SECRET"),
        [_src("p1", "github", "https://github.com/x/y")],
        [_breach("p1", "full_breach")],
    )
    [a] = mod.build_attacks(snap)
    assert a["payload_is_public"] is False
    assert a["payload"] == REDACTED
    assert "SECRET" not in json.dumps(a)


def test_private_source_payload_is_redacted():
    snap = _snapshot(
        _prim("p1", payload_template="PRIVATE PROMPT"),
        [_src("p1", "discord_archive", "https://discord.com/channels/0/1/2")],
        [_breach("p1", "partial_breach")],
    )
    [a] = mod.build_attacks(snap)
    assert a["payload_is_public"] is False
    assert a["payload"] == REDACTED
    assert "PRIVATE PROMPT" not in json.dumps(a)
    # private source URL must NOT leak into attribution
    assert all(s["url"] is None for s in a["sources"])


# --------------------------------------------------------------------------- #
# measured layer always present
# --------------------------------------------------------------------------- #


def test_measured_layer_always_present_even_when_redacted():
    snap = _snapshot(
        _prim("p1", synthesized=True, derived_from_primitive_id="parent"),
        [_src("p1", "discord_archive", "https://discord.com/x")],
        [_breach("p1", "full_breach"), _breach("p1", "refused")],
    )
    [a] = mod.build_attacks(snap)
    m = a["measured"]
    assert m["calibrated_judge"] is True
    assert m["total_trials"] == 2
    assert m["total_breaches"] == 1
    assert m["any_breach"] is True
    assert m["overall_breach_rate"] == 0.5
    assert m["models"][0]["model"] == "openai/gpt-4o-mini"
    assert m["models"][0]["breach_rate"] == 0.5


def test_breach_rate_counts_only_partial_and_full():
    pid = "p1"
    breaches = [
        _breach(pid, "full_breach"),
        _breach(pid, "partial_breach"),
        _breach(pid, "refused"),
        _breach(pid, "evaded"),
        _breach(pid, "error"),
    ]
    snap = _snapshot(
        _prim(pid),
        [_src(pid, "github", "https://github.com/x/y")],
        breaches,
    )
    [a] = mod.build_attacks(snap)
    assert a["measured"]["total_trials"] == 5
    assert a["measured"]["total_breaches"] == 2


def test_never_reproduced_has_empty_measured_no_crash():
    snap = _snapshot(
        _prim("p1"),
        [_src("p1", "arxiv", "https://arxiv.org/abs/1")],
        [],  # no breaches
    )
    [a] = mod.build_attacks(snap)
    assert a["measured"]["models"] == []
    assert a["measured"]["total_trials"] == 0
    assert a["measured"]["any_breach"] is False
    assert a["last_verified"] is None


def test_reproduce_one_liner_present():
    snap = _snapshot(_prim("pXYZ"), [_src("pXYZ", "github", "https://github.com/x/y")], [])
    [a] = mod.build_attacks(snap)
    assert a["reproduce"] == "rogue reproduce pXYZ"


# --------------------------------------------------------------------------- #
# output validity + determinism (on the real sample snapshot)
# --------------------------------------------------------------------------- #


def test_sample_snapshot_exists():
    assert SAMPLE.exists(), "run: uv run python scripts/corpus/build_sample_snapshot.py"


def test_export_writes_valid_json_and_jsonl(tmp_path):
    snap = mod._load_snapshot(SAMPLE)
    attacks = mod.build_attacks(snap)
    paths = mod.write_corpus(attacks, tmp_path, "2026-06-18T00:00:00+00:00")

    # JSONL: every line is a valid object, sorted by id, measured layer present.
    lines = paths["jsonl"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(attacks)
    ids = []
    for line in lines:
        obj = json.loads(line)
        ids.append(obj["id"])
        assert "measured" in obj
        assert "payload_is_public" in obj
        if not obj["payload_is_public"]:
            assert obj["payload"] == REDACTED
    assert ids == sorted(ids)

    # JSON: valid, counts consistent.
    doc = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert doc["n_attacks"] == len(attacks)
    assert doc["n_public"] + doc["n_redacted"] == doc["n_attacks"]
    assert doc["n_public"] >= 1 and doc["n_redacted"] >= 1  # sample exercises both

    assert paths["index"].read_text(encoding="utf-8").startswith("# ROGUE")


def test_export_is_deterministic(tmp_path):
    snap = mod._load_snapshot(SAMPLE)
    a1 = mod.write_corpus(mod.build_attacks(snap), tmp_path / "a", "2026-06-18T00:00:00+00:00")
    b1 = mod.write_corpus(mod.build_attacks(snap), tmp_path / "b", "2026-06-18T00:00:00+00:00")
    for key in ("jsonl", "json", "index"):
        assert a1[key].read_bytes() == b1[key].read_bytes()
