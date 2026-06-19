"""Tier-A pilot: does attack-payload geometry cluster by TECHNIQUE (family),
or by confounds (judge_verdict / target_model)?

Companion to docs/research/payload_embedding_technique_signal.md.

Corpus : data/calibration/sample_50*.full.json  (45 unique payloads, 13 families)
Embedders : hash (SHA-256 null control) | MiniLM (local) | OpenAI text-embedding-3-small (prod)
Metrics : per embedder x labelling -> LOO 1-NN accuracy (vs majority baseline) + cosine silhouette

Read-only. No DB. OpenAI cost ~ a fraction of a cent (45 short strings).

Run:
    uv run --with sentence-transformers --with scikit-learn \
        python scripts/calibration/tier_a_embedding_pilot.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from sklearn.metrics import silhouette_score

ROOT = Path(__file__).resolve().parents[2]

# ---- load + dedup corpus ----
seen: dict = {}
for p in ["data/calibration/sample_50.full.json", "data/calibration/sample_50_v3.full.json"]:
    for r in json.load(open(ROOT / p))["rows"]:
        key = (r.get("primitive_id"), r.get("rendered_payload_excerpt", "")[:120])
        seen[key] = r
rows = list(seen.values())
texts = [r["rendered_payload_excerpt"] for r in rows]
labelings = {
    "family":       [r.get("family") for r in rows],
    "verdict":      [r.get("judge_verdict") for r in rows],
    "target_model": [r.get("target_model") for r in rows],
}
n = len(rows)
print(f"n payloads = {n}")
for name, labs in labelings.items():
    c = collections.Counter(labs)
    print(f"  {name:12s}: {len(c)} classes, majority={max(c.values())}/{n}={max(c.values())/n:.2f}")
print()


def hash_embed(texts):
    out = []
    for t in texts:
        d = hashlib.sha256(t.encode()).digest()
        raw, ci = [], 0
        while len(raw) < 256:
            cd = hashlib.sha256(d + ci.to_bytes(4, "big")).digest()
            raw += [(b / 127.5) - 1.0 for b in cd]
            ci += 1
        out.append(raw[:256])
    return np.array(out)


def minilm_embed(texts):
    from sentence_transformers import SentenceTransformer

    m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return np.array(m.encode(texts, normalize_embeddings=False))


def openai_embed(texts):
    from dotenv import dotenv_values

    os.environ["OPENAI_API_KEY"] = dotenv_values(ROOT / ".env")["OPENAI_API_KEY"]
    from openai import OpenAI

    resp = OpenAI().embeddings.create(model="text-embedding-3-small", input=texts)
    return np.array([d.embedding for d in resp.data])


def l2norm(X):
    return X / np.clip(np.linalg.norm(X, axis=1, keepdims=True), 1e-12, None)


def loo_1nn_acc(X, labels):
    """Leave-one-out 1-NN accuracy under cosine (X assumed L2-normalised)."""
    S = X @ X.T
    np.fill_diagonal(S, -np.inf)
    nn = S.argmax(axis=1)
    labels = np.array(labels, dtype=object)
    return float((labels[nn] == labels).mean())


def majority_baseline(labels):
    c = collections.Counter(labels)
    return max(c.values()) / len(labels)


EMBEDDERS = [("hash(null-control)", hash_embed), ("minilm", minilm_embed), ("openai-3-small", openai_embed)]

print(f"{'embedder':20s} {'labeling':12s} {'1NN-acc':>8s} {'maj-base':>8s} {'lift':>7s} {'silh':>7s}")
print("-" * 70)
for ename, efn in EMBEDDERS:
    X = l2norm(efn(texts))
    for lname, labs in labelings.items():
        acc = loo_1nn_acc(X, labs)
        base = majority_baseline(labs)
        try:
            sil = silhouette_score(X, labs, metric="cosine")
        except Exception:
            sil = float("nan")
        print(f"{ename:20s} {lname:12s} {acc:8.3f} {base:8.3f} {acc-base:+7.3f} {sil:7.3f}")
    print()
