"""Analyze HF jailbreak datasets as a RESEARCH dataset, not a primitive dataset.

Answers the only question that decides whether importing is worth it:
    "Are these new techniques, or thousands of instances of techniques ROGUE
     already understands?"

Measures, for each accessible HF dataset:
  1. exact + near-dup structure count (MinHash/LSH, ~Jaccard>=0.42)
  2. attack-family marker shares (the 'DAN x N' hypothesis test)
  3. overlap with ROGUE's live corpus (text-embedding-3-small nearest-cosine)

NO INGEST. Read-only against the open web + the live corpus. Writes a JSON
report to data/hf_dataset_analysis.json. Embedding spend is bounded to one
representative per near-dup cluster (~$0.02 for in-the-wild).

Gated datasets (allenai/wildjailbreak, walledai/AdvBench) are pulled only if the
HF_TOKEN has canReadGatedRepos AND the account accepted their terms; otherwise
skipped with a logged reason.
"""

from __future__ import annotations

import collections
import io
import json
import os
import random
import re
import sys
import urllib.request

import numpy as np
import pyarrow.parquet as pq
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
TOK = os.environ["HF_TOKEN"]
H = {"User-Agent": "rogue-analysis/1.0", "Authorization": f"Bearer {TOK}"}
DS = "https://datasets-server.huggingface.co"

# (dataset, config-prefix filter, prompt column). config-prefix "" = all configs.
TARGETS = [
    ("TrustAIRLab/in-the-wild-jailbreak-prompts", "jailbreak_", "prompt"),
    ("JailbreakBench/JBB-Behaviors", "behaviors", "Goal"),  # harmful+benign; Goal col
    ("allenai/wildjailbreak", "", None),  # gated; column resolved at runtime
    ("walledai/AdvBench", "", None),  # gated
]


def _get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=timeout)


def parquet_files(ds):
    try:
        with _get(f"{DS}/parquet?dataset={ds}", 30) as r:
            return json.load(r)["parquet_files"]
    except urllib.error.HTTPError as e:  # noqa: F821
        return {"_err": e.code}


SAMPLE_CAP = 5000  # random-sample per dataset before clustering/embedding
REP_CAP = 1500  # cap embedded cluster-representatives (overlap estimate)


def pull(ds, cfg_prefix, col):
    """Return (prompts, note). Resolves prompt column if col is None.

    Reads parquet shards, stops early once enough rows for a representative
    sample are collected (so the ~262k wildjailbreak train split doesn't get
    fully downloaded), filters empty/short strings, then random-samples to
    SAMPLE_CAP. Skips benign baselines (in-the-wild 'regular_*', JBB 'benign').
    """
    files = parquet_files(ds)
    if isinstance(files, dict) and "_err" in files:
        return [], f"inaccessible (HTTP {files['_err']} — gated/token scope)"
    prompts = []
    for f in files:
        if cfg_prefix and not f["config"].startswith(cfg_prefix):
            continue
        if "regular_" in f["config"] or f["split"] == "benign":
            continue
        with _get(f["url"]) as r:
            df = pq.read_table(io.BytesIO(r.read())).to_pandas()
        use = col if col and col in df.columns else None
        if use is None:
            for cand in ("prompt", "adversarial", "Goal", "goal", "text", "vanilla"):
                if cand in df.columns:
                    use = cand
                    break
        if use is None:
            continue
        vals = [s for s in df[use].dropna().astype(str).tolist() if len(s.strip()) > 10]
        prompts += vals
        if len(prompts) >= SAMPLE_CAP * 6:  # enough shards for a sample
            break
    total = len(prompts)
    if total > SAMPLE_CAP:
        random.seed(1)
        prompts = random.sample(prompts, SAMPLE_CAP)
        return prompts, f"sampled {SAMPLE_CAP} of {total}+ prompts"
    return prompts, f"{total} prompts"


def minhash_clusters(texts, K=128, bands=32, rows=4, seed=42):
    random.seed(seed)
    P = (1 << 61) - 1
    A = np.array([random.randrange(1, P) for _ in range(K)], dtype=object)
    B = np.array([random.randrange(0, P) for _ in range(K)], dtype=object)

    def shingles(t):
        w = t.split()
        if len(w) < 3:
            return {hash(t) & 0xFFFFFFFFFFFFFFFF}
        return {hash(" ".join(w[i : i + 3])) & 0xFFFFFFFFFFFFFFFF for i in range(len(w) - 2)}

    sig = np.empty((len(texts), K), dtype=np.uint64)
    for i, t in enumerate(texts):
        sh = list(shingles(t))
        mins = [min((int(a) * x + int(b)) % P for x in sh) for a, b in zip(A, B)]
        sig[i] = np.array(mins, dtype=np.uint64)
    parent = list(range(len(texts)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for bi in range(bands):
        buckets = collections.defaultdict(list)
        for i in range(len(texts)):
            key = (bi,) + tuple(int(x) for x in sig[i, bi * rows : (bi + 1) * rows])
            buckets[key].append(i)
        for idxs in buckets.values():
            r0 = find(idxs[0])
            for j in idxs[1:]:
                parent[find(j)] = r0
    clusters = collections.defaultdict(list)
    for i in range(len(texts)):
        clusters[find(i)].append(i)
    return list(clusters.values())


MARKERS = {
    "DAN/do-anything-now": r"\bdan\b|do anything now",
    "developer mode": r"developer mode",
    "jailbroken/jailbreak": r"jailbroken|jailbreak",
    "AIM": r"\baim\b|always intelligent",
    "persona-adopt": r"you are (?:now )?|act as|pretend (?:to be|you)|roleplay",
    "named-persona": r"\bstan\b|\bdude\b|\bmongo\b|\bkevin\b|\bbetterdan\b",
}


def embed_batch(texts, model="text-embedding-3-small"):
    from openai import OpenAI

    client = OpenAI()
    out = []
    for i in range(0, len(texts), 96):
        chunk = [t[:24000] for t in texts[i : i + 96]]  # ~6k tokens cap
        resp = client.embeddings.create(model=model, input=chunk)
        out += [d.embedding for d in resp.data]
    return np.array(out, dtype=np.float64)


def corpus_vectors():
    e = create_engine(os.environ["DATABASE_URL"])
    with e.connect() as c:
        rows = c.execute(
            text(
                "SELECT family::text, payload_embedding::text FROM attack_primitives "
                "WHERE payload_embedding IS NOT NULL"
            )
        ).all()
    fams = [r[0] for r in rows]
    vecs = np.array([json.loads(r[1]) for r in rows], dtype=np.float64)
    return fams, vecs


def main():
    fams_corpus, V = corpus_vectors()
    Vn = V / np.linalg.norm(V, axis=1, keepdims=True)
    print(f"ROGUE corpus: {len(V)} embedded primitives across {len(set(fams_corpus))} families\n")

    report = {"corpus_size": len(V), "datasets": {}}
    for ds, cfg, col in TARGETS:
        prompts, note = pull(ds, cfg, col)
        print(f"### {ds}  -> {note}")
        if not prompts:
            report["datasets"][ds] = {"status": note}
            print()
            continue
        normed = [re.sub(r"\s+", " ", p.lower().strip()) for p in prompts]
        exact = len(set(normed))
        clusters = minhash_clusters(normed)
        rep_idx = [c[0] for c in clusters]  # one representative per structure
        if len(rep_idx) > REP_CAP:  # bound embedding spend on the overlap estimate
            random.seed(2)
            rep_idx = random.sample(rep_idx, REP_CAP)
        reps = [prompts[i] for i in rep_idx]
        marker = {
            k: round(100 * sum(bool(re.search(p, n)) for n in normed) / len(normed), 1)
            for k, p in MARKERS.items()
        }
        # overlap with corpus
        E = embed_batch(reps)
        En = E / np.linalg.norm(E, axis=1, keepdims=True)
        nearest = (En @ Vn.T).max(axis=1)  # best cosine to any existing primitive
        nearest_idx = (En @ Vn.T).argmax(axis=1)
        buckets = {
            ">=0.90 (dup of existing)": int((nearest >= 0.90).sum()),
            "0.80-0.90 (same technique)": int(((nearest >= 0.80) & (nearest < 0.90)).sum()),
            "0.60-0.80 (known family)": int(((nearest >= 0.60) & (nearest < 0.80)).sum()),
            "<0.60 (novel candidate)": int((nearest < 0.60).sum()),
        }
        novel_idx = [i for i in range(len(reps)) if nearest[i] < 0.60]
        d = {
            "status": note,
            "prompts": len(prompts),
            "exact_unique": exact,
            "exact_dup_pct": round(100 * (1 - exact / len(prompts)), 1),
            "distinct_structures": len(clusters),
            "structure_collapse_pct": round(100 * len(clusters) / len(prompts), 1),
            "marker_pct": marker,
            "overlap_with_corpus": buckets,
            "novel_candidate_structures": len(novel_idx),
            "novel_examples": [reps[i][:160] for i in novel_idx[:8]],
            "nearest_family_of_novel": collections.Counter(
                fams_corpus[nearest_idx[i]] for i in novel_idx
            ).most_common(8),
        }
        report["datasets"][ds] = d
        print(f"  exact-unique {exact}/{len(prompts)} ({d['exact_dup_pct']}% dup)")
        print(f"  distinct structures: {len(clusters)} ({d['structure_collapse_pct']}%)")
        print(f"  overlap vs ROGUE corpus: {buckets}")
        print(f"  novel(<0.60) structures: {len(novel_idx)}")
        print(f"  nearest-family of novel: {d['nearest_family_of_novel']}\n")

    os.makedirs("data", exist_ok=True)
    with open("data/hf_dataset_analysis.json", "w") as f:
        json.dump(report, f, indent=2)
    print("wrote data/hf_dataset_analysis.json")


if __name__ == "__main__":
    sys.exit(main())
