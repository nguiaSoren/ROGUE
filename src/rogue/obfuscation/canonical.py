"""Canonicalize text before embedding so obfuscated near-duplicates collapse.

The harvest dedup path (``rogue.dedupe.embeddings.Deduplicator``) clusters
AttackPrimitives by cosine similarity of their ``payload_template``
embedding. Raw-text embedding treats ``1gn0r3 pr3v10us`` and ``ignore
previous`` as distinct points, so the same technique re-enters the corpus
once per obfuscation skin. ``canonicalize`` folds those surface skins back to
a stable plain form, so the *technique* — not its spelling — is what
clusters.

It is the inverse of ``rogue.obfuscation.operators`` and shares its tables.
Deliberately **conservative and lossless-of-meaning**: it only undoes pure
surface obfuscation (Unicode-compatibility variants, homoglyphs, invisibles,
leetspeak, case/whitespace). It does NOT decode base64/rot13/hex blobs by
default — those can be legitimate payload content, and decoding them risks
collapsing genuinely-different attacks. Pass ``decode_transport=True`` to
opt into best-effort transport decoding when you know the corpus is noisy
with encode-wrapped variants.

Use it as the ``canonicalize_fn`` argument to ``Deduplicator`` /
``SyntacticMutator.dedup_against_parent`` — embed ``canonicalize(text)``
rather than ``text``.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata

from rogue.obfuscation.tables import (
    COMBINING_MARK_RANGES,
    DIRECTION_CONTROL_CHARS,
    HOMOGLYPH_DECODE,
    LEET_DECODE,
    ZERO_WIDTH_CHARS,
)

__all__ = ["canonicalize"]

_INVISIBLE = set(ZERO_WIDTH_CHARS) | set(DIRECTION_CONTROL_CHARS)

# Sequences leet-folding must not touch — mirrors Defender's PROTECTED_SEQUENCE.
# Corrupting a base64 blob or a \xHH / \uHHHH escape would break later
# transport decoding and change meaning. A standalone token of 20+ base64
# chars is treated as an encoded blob, not leetspeak.
_PROTECTED = re.compile(r"\\x[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}|\$\(|[A-Za-z0-9+/]{20,}={0,2}")

# A token containing at least one ASCII letter is eligible for leet folding;
# pure-digit tokens ("100", "2024") are left alone so we don't corrupt numbers.
_TOKEN = re.compile(r"[@$0-9A-Za-z!]+")

# Standalone base64 blob: 20+ base64 chars with optional padding, not flanked
# by more base64 chars. Avoid a trailing \b — it would exclude the `=` padding
# and leave an unpadded (undecodable) blob.
_BASE64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")


def _strip_invisible_and_combining(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _INVISIBLE:
            continue
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in COMBINING_MARK_RANGES):
            continue
        out.append(ch)
    return "".join(out)


def _fold_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_DECODE.get(ch, ch) for ch in text)


def _fold_leet_token(token: str) -> str:
    # Only fold tokens that carry a letter — keeps "2024" intact while turning
    # "1gn0r3" / "@dm1n" / "$y$tem" into "ignore" / "admin" / "system".
    if not any(c.isalpha() for c in token):
        return token
    return "".join(LEET_DECODE.get(c, c) for c in token)


def _fold_leet(text: str) -> str:
    # Walk the protected sequences and only leet-fold the plain gaps between
    # them, so base64 blobs and \xHH escapes survive verbatim.
    out: list[str] = []
    last = 0
    for m in _PROTECTED.finditer(text):
        gap = text[last : m.start()]
        out.append(_TOKEN.sub(lambda t: _fold_leet_token(t.group(0)), gap))
        out.append(m.group(0))
        last = m.end()
    tail = text[last:]
    out.append(_TOKEN.sub(lambda t: _fold_leet_token(t.group(0)), tail))
    return "".join(out)


def _maybe_decode_transport(text: str) -> str:
    """Best-effort decode of rot13 and standalone base64 blobs.

    Only applied when ``decode_transport=True``. A base64 blob is replaced by
    its decoded text *only* when the decode round-trips to mostly-printable
    ASCII — otherwise the blob is left as-is (it was probably real data, not
    an encode-wrapped instruction).
    """
    # rot13 is a pure letter rotation; applying it canonicalizes both a rot13
    # payload and its plaintext to the same fold point is NOT desired, so we
    # only rot13 when the text looks rot13-ish is hard to detect — skip by
    # default and leave rot13 to the operator-label path. We decode base64
    # blobs, which is the high-value, low-risk case.
    def _sub(m: re.Match[str]) -> str:
        blob = m.group(0)
        padded = blob + "=" * (-len(blob.rstrip("=")) % 4) if "=" not in blob else blob
        try:
            raw = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            return blob
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            return blob
        printable = sum(c.isprintable() or c.isspace() for c in decoded)
        if decoded and printable / len(decoded) >= 0.9:
            return decoded
        return blob

    return _BASE64_BLOB.sub(_sub, text)


def canonicalize(text: str, *, decode_transport: bool = False) -> str:
    """Fold surface obfuscation to a stable plain form for dedup embedding.

    Pipeline (each step is meaning-preserving for the underlying technique):

      1. NFKC — fullwidth ``ＳＹＳＴＥＭ`` and math-alphanumerics ``𝓲𝓰𝓷𝓸𝓻𝓮``
         collapse to ASCII.
      2. Strip invisible (zero-width / BOM / word-joiner), direction-override,
         and combining (Zalgo) characters.
      3. Fold Cyrillic homoglyphs to their ASCII twins.
      4. Reverse leetspeak token-by-token, protecting base64/escape blobs.
      5. (opt-in) best-effort decode of base64 transport blobs.

    Deliberately folds ONLY what the embedding model is blind to — obfuscation
    skins. It does NOT lowercase or normalize whitespace: ``text-embedding-3``
    is already robust to case and spacing, so folding them would buy nothing in
    dedup quality while changing nearly every payload's embedding. Keeping this
    out makes ``canonicalize`` a true identity on already-clean prose, so
    canonical seeds harvested before this existed keep matching new arrivals
    and only genuinely-obfuscated rows ever need re-embedding.
    """
    if not text:
        return text

    # NFKD (decompose) — not NFKC: decomposition splits precomposed accented
    # letters (í → i + combining acute) so the combining-mark strip below can
    # remove the diacritic. NFKC would recompose them and the strip would miss.
    # Fullwidth/math-alphanumeric compatibility variants still fold to ASCII.
    out = unicodedata.normalize("NFKD", text)
    out = _strip_invisible_and_combining(out)
    out = _fold_homoglyphs(out)
    out = _fold_leet(out)
    if decode_transport:
        out = _maybe_decode_transport(out)
    return out
