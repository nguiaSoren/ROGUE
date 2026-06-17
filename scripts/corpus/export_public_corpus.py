"""Export ROGUE's MEASURED attack corpus into a public, shareable artifact.

This is ROGUE's differentiator vs raw jailbreak dumps (Pliny / L1B3RT4S, ~20k
stars): every attack here carries a *measured* reproduction layer — does it
actually breach, which models, at what rate, judged by a calibrated judge —
plus freshness (first-seen / last-verified) and a clean structured taxonomy.

Content policy (VIRAL_LAUNCH_SPEC Decision #3 + RESPONSIBLE_RELEASE.md):
  * The actual PROMPT TEXT is included ONLY when the attack's source is already
    public elsewhere (a Pliny / L1B3RT4S / public-GitHub / arXiv / public-tweet /
    public-blog disclosure). See ``payload_is_public`` below for the exact rule.
  * Anything ROGUE synthesized, or whose source is not demonstrably public, has
    its ``payload`` redacted to a placeholder. The RAW scraped corpus is NEVER
    published — only this derived, measured layer.
  * The MEASURED layer (family, vector, per-model breach verdicts + rates,
    trials, calibrated-judge flag, first_seen / last_verified, source
    attribution) is ALWAYS included, redacted or not.

Inputs (one of):
  --snapshot <path.json[.gz]>   offline fixture — a dict of
                                {deployment_configs, attack_primitives,
                                 breach_results, source_provenances}
                                (the shape ``scripts/ops/export_demo_snapshot.py``
                                produces, plus a ``source_provenances`` table).
  $DATABASE_URL                 read-only live/Neon read (no --snapshot given).

Outputs (deterministic, idempotent — same input → byte-identical output):
  corpus/attacks.jsonl   one JSON object per attack, sorted by id
  corpus/attacks.json    {generated_at, n_attacks, n_public, n_redacted, attacks:[...]}
  corpus/INDEX.md        human-readable table

Run:
  uv run python scripts/corpus/export_public_corpus.py --snapshot scripts/corpus/sample_snapshot.json
  uv run python scripts/corpus/export_public_corpus.py            # reads $DATABASE_URL
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "corpus"

REDACTED_PAYLOAD = "[redacted — novel/synthesized; see ROGUE]"

# Verdicts the calibrated judge can emit (rogue.schemas.breach_result.JudgeVerdict).
# A "breach" is a partial or full breach; refusals/evasions/errors are not.
BREACH_VERDICTS = {"partial_breach", "full_breach"}
NON_BREACH_VERDICTS = {"refused", "evaded", "error"}

# Attack-family slug -> human display label. Mirrors rogue.report._TECHNIQUE_DISPLAY
# (kept in sync there; duplicated here so the exporter has no heavy import).
TECHNIQUE_DISPLAY: dict[str, str] = {
    "direct_instruction_override": "Direct Instruction Override",
    "role_hijack": "Role Hijack",
    "dan_persona": "DAN / Persona Jailbreak",
    "policy_roleplay": "Policy-Evasion Roleplay",
    "refusal_suppression": "Refusal Suppression",
    "multi_turn_gradient": "Crescendo",
    "chain_of_thought_hijack": "Chain-of-Thought Hijack",
    "system_prompt_leak": "System-Prompt Leak",
    "training_data_extraction": "Training-Data Extraction",
    "indirect_prompt_injection": "Indirect Prompt Injection",
    "tool_use_hijack": "Tool-Use Hijack",
    "obfuscation_encoding": "Obfuscation / Encoding",
    "language_switching": "Language Switching",
    "multimodal_injection": "Multimodal Injection",
    "multi_turn_persona_chain": "Multi-Turn Persona Chain",
}


# --------------------------------------------------------------------------- #
# "Already public elsewhere" detection
# --------------------------------------------------------------------------- #

# Source *types* (rogue.schemas.source_provenance.SourceType) that, by their
# nature, are public disclosures. discord_archive / other / fixture are NOT —
# they are private channels or our own scaffolding, so payloads from them stay
# redacted unless a later, stronger signal proves otherwise.
PUBLIC_SOURCE_TYPES = {
    "reddit",
    "x",
    "arxiv",
    "github",
    "huggingface",
    "blog",
    "mitre",
    "owasp",
    "vendor_safety_blog",
    "community_archive",
}

# Public hosts we recognize — a URL on one of these is open-web reachable. Match
# is on the registrable suffix (host == h or endswith "." + h), so subdomains
# (e.g. embracethered's pages, gist.github.com) are covered. Pliny's L1B3RT4S
# lives on github.com; this list deliberately includes the big public surfaces.
PUBLIC_HOSTS = {
    "github.com",
    "githubusercontent.com",
    "gist.github.com",
    "arxiv.org",
    "reddit.com",
    "redd.it",
    "twitter.com",
    "x.com",
    "nitter.net",
    "huggingface.co",
    "medium.com",
    "substack.com",
    "embracethered.com",
    "sentinelone.com",
    "owasp.org",
    "mitre.org",
    "atlas.mitre.org",
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return ""


def _is_public_host(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUBLIC_HOSTS)


def payload_is_public(primitive: dict, sources: Iterable[dict]) -> bool:
    """Decide whether an attack's prompt text is ALREADY public elsewhere.

    Returns True iff the attack is NOT a ROGUE synthesis AND at least one of its
    sources is a public-disclosure type pointing at a recognized public host.
    Everything else is treated as novel/non-public → payload redacted.

    This is conservative on purpose: a payload is kept ONLY when we can point at
    where it already lives in the open, honoring RESPONSIBLE_RELEASE.md (the raw
    scraped corpus is never published; only what is independently public stays
    in clear text).
    """
    # ROGUE-synthesized primitives (§10.7 augmentation chain) are by definition
    # not "already public elsewhere", regardless of their parent's sources.
    if primitive.get("synthesized"):
        return False
    for s in sources:
        stype = (s.get("source_type") or "").lower()
        url = s.get("url") or ""
        if stype in PUBLIC_SOURCE_TYPES and _is_public_host(url):
            return True
    return False


# --------------------------------------------------------------------------- #
# Snapshot / DB loading
# --------------------------------------------------------------------------- #


def _load_snapshot(path: Path) -> dict[str, list[dict]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("deployment_configs", "attack_primitives", "breach_results"):
        data.setdefault(key, [])
    data.setdefault("source_provenances", [])
    return data


def _load_from_db(database_url: str) -> dict[str, list[dict]]:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    tables = {
        "deployment_configs": "SELECT config_id, target_model, name FROM deployment_configs",
        "attack_primitives": (
            "SELECT primitive_id, family, secondary_families, vector, title, "
            "short_description, payload_template, multi_turn_sequence, "
            "target_models_claimed, claimed_success_rate, reproducibility_score, "
            "synthesized, derived_from_primitive_id, discovered_at, base_severity "
            "FROM attack_primitives"
        ),
        "breach_results": (
            "SELECT primitive_id, deployment_config_id, verdict, judge_confidence, "
            "ran_at FROM breach_results"
        ),
        "source_provenances": (
            "SELECT primitive_id, url, source_type, author, published_at, "
            "bright_data_product FROM source_provenances"
        ),
    }
    out: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for name, sql in tables.items():
            out[name] = [dict(r) for r in conn.execute(text(sql)).mappings().all()]
    return out


# --------------------------------------------------------------------------- #
# Measured layer
# --------------------------------------------------------------------------- #


def _iso(value: Any) -> Optional[str]:
    """Normalize a timestamp (datetime or ISO string) to an ISO-8601 string."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_measured_layer(
    breaches: list[dict], config_by_id: dict[str, dict]
) -> dict[str, Any]:
    """Aggregate raw breach rows into per-model measured results + freshness.

    Per model (target_model string): trials, breaches, breach_rate, verdict
    counts, calibrated_judge flag, and last_verified (max ran_at). Trials that
    errored are still counted as trials but never as breaches.
    """
    per_model: dict[str, dict[str, Any]] = {}
    last_verified_dt: Optional[datetime] = None

    for b in breaches:
        cfg = config_by_id.get(b.get("deployment_config_id"))
        model = (cfg or {}).get("target_model") or b.get("deployment_config_id") or "unknown"
        verdict = (b.get("verdict") or "").lower()

        m = per_model.setdefault(
            model,
            {
                "model": model,
                "trials": 0,
                "breaches": 0,
                "verdict_counts": defaultdict(int),
            },
        )
        m["trials"] += 1
        m["verdict_counts"][verdict] += 1
        if verdict in BREACH_VERDICTS:
            m["breaches"] += 1

        ran = _to_dt(b.get("ran_at"))
        if ran is not None and (last_verified_dt is None or ran > last_verified_dt):
            last_verified_dt = ran

    models = []
    total_trials = 0
    total_breaches = 0
    for model in sorted(per_model):
        m = per_model[model]
        trials = m["trials"]
        breaches = m["breaches"]
        total_trials += trials
        total_breaches += breaches
        models.append(
            {
                "model": model,
                "trials": trials,
                "breaches": breaches,
                "breach_rate": round(breaches / trials, 4) if trials else 0.0,
                "verdict_counts": dict(sorted(m["verdict_counts"].items())),
            }
        )

    return {
        "models": models,
        "total_trials": total_trials,
        "total_breaches": total_breaches,
        "any_breach": total_breaches > 0,
        "overall_breach_rate": (
            round(total_breaches / total_trials, 4) if total_trials else 0.0
        ),
        # ROGUE always reproduces with its calibrated v3 judge in the matrix; the
        # measured rows here come from that pipeline.
        "calibrated_judge": True,
        "last_verified": _iso(last_verified_dt),
    }


def _first_seen(primitive: dict, sources: list[dict]) -> Optional[str]:
    """Earliest credible date this attack existed: min over source published_at
    and the primitive's claimed_first_seen, falling back to discovered_at."""
    candidates: list[datetime] = []
    for key in ("claimed_first_seen", "discovered_at"):
        dt = _to_dt(primitive.get(key))
        if dt:
            candidates.append(dt)
    for s in sources:
        dt = _to_dt(s.get("published_at"))
        if dt:
            candidates.append(dt)
    if not candidates:
        return None
    return _iso(min(candidates))


def _source_attribution(sources: list[dict], keep_payload: bool) -> list[dict]:
    """Source name + url. URL is included only when the source is public (so we
    never point at a private/scaffold fetch); type + author always travel."""
    out = []
    for s in sources:
        stype = (s.get("source_type") or "").lower()
        url = s.get("url") or ""
        public = stype in PUBLIC_SOURCE_TYPES and _is_public_host(url)
        out.append(
            {
                "source_type": stype,
                "author": s.get("author"),
                "url": url if public else None,
                "published_at": _iso(s.get("published_at")),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def build_attacks(snapshot: dict[str, list[dict]]) -> list[dict]:
    """Transform a snapshot/DB read into the redacted, measured public records."""
    config_by_id = {c["config_id"]: c for c in snapshot["deployment_configs"]}

    breaches_by_pid: dict[str, list[dict]] = defaultdict(list)
    for b in snapshot["breach_results"]:
        breaches_by_pid[b["primitive_id"]].append(b)

    sources_by_pid: dict[str, list[dict]] = defaultdict(list)
    for s in snapshot["source_provenances"]:
        sources_by_pid[s["primitive_id"]].append(s)

    attacks: list[dict] = []
    for p in snapshot["attack_primitives"]:
        pid = p["primitive_id"]
        sources = sources_by_pid.get(pid, [])
        keep_payload = payload_is_public(p, sources)

        family = (p.get("family") or "").lower()
        secondary = [str(f).lower() for f in (p.get("secondary_families") or [])]

        record = {
            "id": pid,
            # ----- structured taxonomy -----
            "family": family,
            "family_label": TECHNIQUE_DISPLAY.get(family, family.replace("_", " ").title()),
            "secondary_families": secondary,
            "vector": (p.get("vector") or "").lower(),
            "title": p.get("title"),
            "synthesized": bool(p.get("synthesized")),
            "base_severity": (p.get("base_severity") or "").lower(),
            "reproducibility_score": p.get("reproducibility_score"),
            # ----- the payload (redaction-gated) -----
            "payload_is_public": keep_payload,
            "payload": p.get("payload_template") if keep_payload else REDACTED_PAYLOAD,
            # ----- freshness -----
            "first_seen": _first_seen(p, sources),
            # ----- source attribution -----
            "sources": _source_attribution(sources, keep_payload),
            # ----- MEASURED reproduction (always present) -----
            "measured": _build_measured_layer(breaches_by_pid.get(pid, []), config_by_id),
            # ----- reproduce one-liner -----
            "reproduce": f"rogue reproduce {pid}",
        }
        record["last_verified"] = record["measured"]["last_verified"]
        attacks.append(record)

    attacks.sort(key=lambda a: a["id"])
    return attacks


def _render_index_md(attacks: list[dict], generated_at: str) -> str:
    n_public = sum(1 for a in attacks if a["payload_is_public"])
    lines = [
        "# ROGUE public attack corpus — INDEX",
        "",
        "> Auto-generated by `scripts/corpus/export_public_corpus.py`. Do not edit by hand.",
        "",
        f"- Generated: `{generated_at}`",
        f"- Attacks: **{len(attacks)}** "
        f"({n_public} with public prompt text, {len(attacks) - n_public} redacted)",
        "- Every row carries a MEASURED reproduction layer (calibrated judge). "
        "Prompt text is shown only where the attack is already public elsewhere; "
        "novel/synthesized payloads are redacted. See `SCHEMA.md` + `../RESPONSIBLE_RELEASE.md`.",
        "",
        "| ID | Technique | Families | Vector | Sev | Top measured result | First seen | Last verified | Payload | Source |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in attacks:
        m = a["measured"]
        # Best (highest-rate) measured per-model result.
        top = ""
        if m["models"]:
            best = max(m["models"], key=lambda x: (x["breach_rate"], x["trials"]))
            top = (
                f"breaches `{best['model']}` at {best['breach_rate'] * 100:.0f}% "
                f"({best['breaches']}/{best['trials']})"
            )
        else:
            top = "_not yet reproduced_"
        fams = ", ".join([a["family_label"]] + [TECHNIQUE_DISPLAY.get(f, f) for f in a["secondary_families"]])
        src = "—"
        public_srcs = [s for s in a["sources"] if s.get("url")]
        if public_srcs:
            s0 = public_srcs[0]
            label = s0.get("author") or s0.get("source_type") or "source"
            src = f"[{label}]({s0['url']})"
        elif a["sources"]:
            src = a["sources"][0].get("source_type") or "—"
        payload_cell = "public" if a["payload_is_public"] else "redacted"
        lines.append(
            "| `{id}` | {title} | {fams} | {vector} | {sev} | {top} | {fs} | {lv} | {pl} | {src} |".format(
                id=a["id"],
                title=(a["title"] or "").replace("|", "\\|"),
                fams=fams.replace("|", "\\|"),
                vector=a["vector"],
                sev=a["base_severity"],
                top=top,
                fs=(a["first_seen"] or "—")[:10],
                lv=(a["last_verified"] or "—")[:10],
                pl=payload_cell,
                src=src.replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_corpus(attacks: list[dict], out_dir: Path, generated_at: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n_public = sum(1 for a in attacks if a["payload_is_public"])

    jsonl_path = out_dir / "attacks.jsonl"
    jsonl_path.write_text(
        "".join(
            json.dumps(a, ensure_ascii=False, sort_keys=True) + "\n" for a in attacks
        ),
        encoding="utf-8",
    )

    json_path = out_dir / "attacks.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "n_attacks": len(attacks),
                "n_public": n_public,
                "n_redacted": len(attacks) - n_public,
                "attacks": attacks,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    index_path = out_dir / "INDEX.md"
    index_path.write_text(_render_index_md(attacks, generated_at), encoding="utf-8")

    return {"jsonl": jsonl_path, "json": json_path, "index": index_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Offline snapshot fixture (.json or .json.gz). If omitted, reads $DATABASE_URL.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=CORPUS_DIR,
        help="Output directory (default: <repo>/corpus).",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override the generated_at timestamp (for deterministic/test runs).",
    )
    args = parser.parse_args()

    if args.snapshot is not None:
        snapshot = _load_snapshot(args.snapshot)
        src_label = str(args.snapshot)
    else:
        db = os.environ.get("DATABASE_URL")
        if not db:
            parser.error("no --snapshot given and $DATABASE_URL is unset")
        snapshot = _load_from_db(db)
        src_label = "$DATABASE_URL"

    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    attacks = build_attacks(snapshot)
    paths = write_corpus(attacks, args.out_dir, generated_at)

    n_public = sum(1 for a in attacks if a["payload_is_public"])
    print(f"source: {src_label}")
    print(f"attacks: {len(attacks)}  public-payload: {n_public}  redacted: {len(attacks) - n_public}")
    for label, path in paths.items():
        print(f"  {label:6} -> {path}")


if __name__ == "__main__":
    main()
