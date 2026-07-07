"""The content axis Q11 deliberately left out — a compact, serve-able embedding-affinity feature.

Q11's survival predictor is *embedding-free by construction*: it scores an attack from its structural
surface (family/vector/requirements/provenance) crossed with the target config. Q7 asks the orthogonal
question — **does the semantic content of the payload itself predict whether it beats this target,
above and beyond its metadata?** ROGUE's own prior probe (``payload_embedding_technique_signal.md``,
silhouette ≈ 0) says raw payload embeddings do *not* cluster by technique, and Galinkin (2412.01547)
shows embeddings carry strong signal but for *detection*, not per-target success. So whether the
embedding earns its place here is an **empirical** question — and ``train.py`` answers it with an
explicit structural-only-vs-augmented ablation rather than assuming a win.

Rather than feed a raw 1536-d vector into a head trained on ~1.8k rows (which would overfit and, per
the silhouette result, likely learn noise), we distil the embedding to a **breach-affinity** signal:
"does this payload look like the payloads that have breached *targets like this one* before?" At train
time we compute, per config **sibling class** (size × context-reach — the same grouping the
hierarchical prior uses) and globally, the centroid of breaching payload embeddings and of
non-breaching ones. The serve-time feature is the cosine gap to those two centroids — a couple of
scalars, storable in the model artifact, computable from just the payload's own embedding. This is a
memory feature (Galinkin's embedding signal) reframed onto ROGUE's *target-success* label, which is the
combination no surveyed paper reaches.

Leakage is handled upstream: centroids are fit on the **train** split only, and the back-test scores
**held-out primitives** (group-split by primitive), so a test row's own embedding never entered the
centroid it is scored against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EMB_DIM = 1536  # text-embedding-3-small

# Feature layout emitted by ``features``:
#   [0] affinity_local   — cos(emb, breach_centroid[sib]) − cos(emb, safe_centroid[sib]), sib centroids
#                          when that sibling class has support, else the global gap (so the slot is
#                          always populated with the best available evidence).
#   [1] affinity_global  — the same gap against the global breach/safe centroids (a stable backbone the
#                          head can lean on when a sibling class is thin or novel).
#   [2] has_embedding    — 1.0 when a real embedding was supplied, 0.0 when it was missing (the head can
#                          learn to discount the two affinity slots, which are 0.0, in that case).
AFFINITY_DIM = 3

# A sibling class needs at least this many breaching AND non-breaching pairs before its own centroids
# are trusted; below it, the local slot falls back to the global centroids.
DEFAULT_MIN_CLASS_SUPPORT = 3


def _unit(v: list[float]) -> list[float] | None:
    """L2-normalise; ``None`` for a zero/degenerate vector so it contributes nothing to a centroid.

    Coerces to Python ``float`` — pgvector hands embeddings back as numpy ``float32``, which would
    otherwise poison the centroid lists and break JSON serialisation of the artifact."""
    v = [float(x) for x in v]
    mag = math.sqrt(sum(x * x for x in v))
    if mag == 0.0:
        return None
    return [x / mag for x in v]


def _cos_to_centroid(unit_emb: list[float], centroid: list[float]) -> float:
    """Cosine between a unit embedding and a centroid (a mean of unit vectors, not itself unit)."""
    dot = 0.0
    cmag = 0.0
    for e, c in zip(unit_emb, centroid):
        dot += e * c
        cmag += c * c
    cmag = math.sqrt(cmag)
    return dot / cmag if cmag > 0.0 else 0.0


@dataclass
class EmbeddingAffinity:
    """Fitted breach/safe centroids + the serve-time feature they produce.

    Centroids are means of **unit-normalised** payload embeddings, kept as plain lists so the whole
    thing round-trips through the model JSON. Only sibling classes with enough support are stored; every
    other class (and any novel one) falls back to the global centroids, so the artifact stays small.
    """

    global_breach: list[float] | None
    global_safe: list[float] | None
    breach_centroids: dict[str, list[float]] = field(default_factory=dict)  # sibling_key -> centroid
    safe_centroids: dict[str, list[float]] = field(default_factory=dict)
    dim: int = EMB_DIM

    @property
    def informative(self) -> bool:
        """True once we have a global breach *and* safe centroid — else affinity is uninformative and
        ``features`` returns zeros (the head then rides on the structural block alone)."""
        return self.global_breach is not None and self.global_safe is not None

    @classmethod
    def fit(
        cls,
        embeddings: list[list[float] | None],
        sibling_keys: list[str],
        labels: list[float],
        *,
        min_class_support: int = DEFAULT_MIN_CLASS_SUPPORT,
        dim: int = EMB_DIM,
    ) -> "EmbeddingAffinity":
        """Fit centroids from (embedding, sibling_key, label) rows. Rows with no embedding are skipped.

        ``label`` is 1.0 for a breaching pair, 0.0 otherwise (the same pair-level breach label the head
        trains on). A centroid is the mean of the unit embeddings in its (class, outcome) cell.
        """
        # accumulators: key -> [sum_vector, count]; "*" is the global cell.
        breach_sum: dict[str, list[float]] = {}
        breach_n: dict[str, int] = {}
        safe_sum: dict[str, list[float]] = {}
        safe_n: dict[str, int] = {}

        def _add(bucket_sum, bucket_n, key, uvec):
            acc = bucket_sum.get(key)
            if acc is None:
                bucket_sum[key] = list(uvec)
                bucket_n[key] = 1
            else:
                for i, x in enumerate(uvec):
                    acc[i] += x
                bucket_n[key] += 1

        for emb, sib, lab in zip(embeddings, sibling_keys, labels):
            if emb is None:
                continue
            uvec = _unit(list(emb))
            if uvec is None:
                continue
            if lab >= 0.5:
                _add(breach_sum, breach_n, sib, uvec)
                _add(breach_sum, breach_n, "*", uvec)
            else:
                _add(safe_sum, safe_n, sib, uvec)
                _add(safe_sum, safe_n, "*", uvec)

        def _mean(bucket_sum, bucket_n, key):
            n = bucket_n.get(key, 0)
            if n == 0:
                return None
            return [x / n for x in bucket_sum[key]]

        global_breach = _mean(breach_sum, breach_n, "*")
        global_safe = _mean(safe_sum, safe_n, "*")

        breach_centroids: dict[str, list[float]] = {}
        safe_centroids: dict[str, list[float]] = {}
        for sib in set(breach_n) | set(safe_n):
            if sib == "*":
                continue
            if breach_n.get(sib, 0) >= min_class_support and safe_n.get(sib, 0) >= min_class_support:
                breach_centroids[sib] = _mean(breach_sum, breach_n, sib)
                safe_centroids[sib] = _mean(safe_sum, safe_n, sib)

        return cls(
            global_breach=global_breach,
            global_safe=global_safe,
            breach_centroids=breach_centroids,
            safe_centroids=safe_centroids,
            dim=dim,
        )

    def features(self, embedding: list[float] | None, sibling_key: str) -> list[float]:
        """The ``AFFINITY_DIM`` serve-time features for one (embedding, target sibling class)."""
        if embedding is None or not self.informative:
            return [0.0] * AFFINITY_DIM
        uvec = _unit(list(embedding))
        if uvec is None:
            return [0.0, 0.0, 1.0]  # a real-but-degenerate embedding: flag present, no usable direction

        g_gap = _cos_to_centroid(uvec, self.global_breach) - _cos_to_centroid(uvec, self.global_safe)

        b = self.breach_centroids.get(sibling_key)
        s = self.safe_centroids.get(sibling_key)
        if b is not None and s is not None:
            local_gap = _cos_to_centroid(uvec, b) - _cos_to_centroid(uvec, s)
        else:
            local_gap = g_gap  # thin/novel sibling class → lean on the global signal
        return [local_gap, g_gap, 1.0]

    # ---- persistence (folded into the PrefirePredictor artifact) ---------------------------------
    def to_dict(self) -> dict:
        return {
            "dim": self.dim,
            "global_breach": self.global_breach,
            "global_safe": self.global_safe,
            "breach_centroids": self.breach_centroids,
            "safe_centroids": self.safe_centroids,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EmbeddingAffinity":
        return cls(
            global_breach=d.get("global_breach"),
            global_safe=d.get("global_safe"),
            breach_centroids=d.get("breach_centroids", {}),
            safe_centroids=d.get("safe_centroids", {}),
            dim=d.get("dim", EMB_DIM),
        )


__all__ = ["EmbeddingAffinity", "AFFINITY_DIM", "EMB_DIM", "DEFAULT_MIN_CLASS_SUPPORT"]
