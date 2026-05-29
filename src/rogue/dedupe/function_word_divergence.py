"""Function-word Jensen-Shannon divergence — cheap secondary dedup check.

Position in the dedup pipeline (ROGUE_PLAN.md §3.1 LAYER 3, §A.22, §9.5):

    embedding cosine > 0.92  (primary, OpenAI text-embedding-3-small)
            │
            ▼ ── if no match ──►  treat as novel cluster
            │
            ▼ ── if match     ──►  cluster-merge candidate
            │
    function_word_divergence  (this module — secondary, cheap, no API call)
            │
            ▼ ── if < threshold ──►  confirm merge (likely structural duplicate)
            ▼ ── else            ──►  reject merge (false-positive on embedding)

Why function words? Embeddings cluster by topic; two attacks with the same
template structure but different ``{target_topic}`` slot fillers (e.g.
"…tell me about bombs" vs "…tell me about drugs") get pushed apart by the
substituted noun. Function words (``the``, ``of``, ``and``, ``to`` …) are
invariant under topic substitution, so their distribution is a structural
fingerprint that survives slot-filling.

Pure stdlib — no scipy/numpy/NLTK. The function-word list is the canonical
NLTK English-stopword list, hardcoded here so the module is import-safe
without any extra dependency.
"""

from __future__ import annotations

import math
from collections import Counter

__all__ = ["FUNCTION_WORDS", "function_word_divergence", "is_near_duplicate"]


# Canonical NLTK English stopword list (179 entries). Frozen at import time
# so other dedup modules can re-use it without paying for re-construction.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
        "you're", "you've", "you'll", "you'd", "your", "yours", "yourself",
        "yourselves", "he", "him", "his", "himself", "she", "she's", "her",
        "hers", "herself", "it", "it's", "its", "itself", "they", "them",
        "their", "theirs", "themselves", "what", "which", "who", "whom",
        "this", "that", "that'll", "these", "those", "am", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "having",
        "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if",
        "or", "because", "as", "until", "while", "of", "at", "by", "for",
        "with", "about", "against", "between", "into", "through", "during",
        "before", "after", "above", "below", "to", "from", "up", "down",
        "in", "out", "on", "off", "over", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why", "how",
        "all", "any", "both", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so",
        "than", "too", "very", "s", "t", "can", "will", "just", "don",
        "don't", "should", "should've", "now", "d", "ll", "m", "o", "re",
        "ve", "y", "ain", "aren", "aren't", "couldn", "couldn't", "didn",
        "didn't", "doesn", "doesn't", "hadn", "hadn't", "hasn", "hasn't",
        "haven", "haven't", "isn", "isn't", "ma", "mightn", "mightn't",
        "mustn", "mustn't", "needn", "needn't", "shan", "shan't", "shouldn",
        "shouldn't", "wasn", "wasn't", "weren", "weren't", "won", "won't",
        "wouldn", "wouldn't",
    }
)


# Characters to strip from each token (cheap punctuation removal — avoids
# pulling in a tokenizer dep). Single quotes are kept because contractions
# like ``don't`` / ``you're`` are first-class entries in FUNCTION_WORDS.
_STRIP_CHARS = ".,!?;:\"()[]{}—–-"


def _function_word_counts(text: str) -> Counter[str]:
    """Lowercase-tokenize ``text`` and return Counter over function words only."""
    counts: Counter[str] = Counter()
    for raw in text.lower().split():
        token = raw.strip(_STRIP_CHARS)
        if token and token in FUNCTION_WORDS:
            counts[token] += 1
    return counts


def function_word_divergence(a: str, b: str) -> float:
    """Return JS divergence in [0.0, 1.0] (base-2 log convention).

    0.0 = identical function-word distribution; 1.0 = maximally divergent.
    The 0.92-cosine embedding check is the primary; this is the secondary.
    Empty / function-word-free inputs return 1.0 (can't compare structures).
    """
    counts_a = _function_word_counts(a)
    counts_b = _function_word_counts(b)
    total_a = sum(counts_a.values())
    total_b = sum(counts_b.values())
    # If either side has no function-word tokens we can't form a meaningful
    # distribution — fall back to "maximally divergent" so the caller treats
    # the pair as not-a-duplicate rather than crashing on division by zero.
    if total_a == 0 or total_b == 0:
        return 1.0

    vocab = set(counts_a) | set(counts_b)
    # Build probability distributions p, q + their midpoint m over the union vocab.
    p = {w: counts_a.get(w, 0) / total_a for w in vocab}
    q = {w: counts_b.get(w, 0) / total_b for w in vocab}
    m = {w: 0.5 * (p[w] + q[w]) for w in vocab}

    # JS = 0.5 * KL(p||m) + 0.5 * KL(q||m). Base-2 log bounds the result in
    # [0, 1]. Skip zero-probability terms (0 * log = 0 by convention).
    def _kl(dist_p: dict[str, float], dist_m: dict[str, float]) -> float:
        return sum(
            dist_p[w] * math.log2(dist_p[w] / dist_m[w])
            for w in vocab
            if dist_p[w] > 0.0
        )

    js = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
    # Clamp to [0, 1] — guards against tiny floating-point drift past 1.0.
    return max(0.0, min(1.0, js))


def is_near_duplicate(a: str, b: str, threshold: float = 0.05) -> bool:
    """Return True iff ``function_word_divergence(a, b) < threshold``.

    Default threshold 0.05 is the cluster-merge trigger consumed by
    ``Deduplicator`` after the embedding-cosine primary check fires.
    """
    return function_word_divergence(a, b) < threshold
