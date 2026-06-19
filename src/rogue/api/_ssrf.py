"""SSRF guard for the public scan endpoint.

The public ``POST /api/public-scan`` accepts a visitor-supplied ``endpoint`` URL and fires HTTP
requests at it from our server. That is a textbook Server-Side Request Forgery surface: a visitor
could point us at ``http://169.254.169.254/...`` (cloud metadata), ``http://127.0.0.1:.../`` (our own
loopback services), or an internal ``10.x`` host and use ROGUE as a proxy into our private network.

This module is the single gate. :func:`validate_public_endpoint` parses the URL, enforces an
http/https scheme, resolves the hostname (``getaddrinfo``) and rejects unless EVERY resolved address
is a globally-routable public unicast address. It raises :class:`SsrfBlocked` (a plain ``ValueError``
subclass carrying a generic, key-free message) on any violation so the route can map it to a 400.

Defence-in-depth notes:
  * We block by category (loopback / private / link-local / unique-local / reserved / multicast /
    unspecified) via :mod:`ipaddress`, AND explicitly enumerate the cloud-metadata addresses
    (169.254.169.254, fd00:ec2::254, 100.100.100.200) since some live in ranges (e.g. carrier-grade
    NAT 100.64/10) that ``is_private`` does not flag.
  * IPv6 transition encodings of a blocked IPv4 address are unwrapped before classification:
    IPv4-mapped (``::ffff:a.b.c.d``), 6to4 (``2002::/16``), and the NAT64 well-known prefix
    (``64:ff9b::/96``). Without this, ``::ffff:169.254.169.254`` would slip past a naive IPv6 check.
  * We resolve and check ALL A/AAAA records, not just the first — a host with one public and one
    private record is rejected.
  * The OpenAI SDK / httpx client the scan uses does NOT follow redirects by default, so a 3xx from
    the (validated) endpoint into a blocked IP is surfaced as a request error rather than chased. The
    route relies on that default and does not re-enable redirects. See the route docstring.

DNS rebinding (a record that resolves public at check time and private at request time) is the one
class this pre-flight cannot fully close on its own; the strict per-IP, all-records check plus the
short wall-clock budget on the route narrows the window. A connect-time socket guard would close it
fully and is noted as the follow-up.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# Cloud-metadata / well-known internal service IPs that must ALWAYS be blocked, including ones that
# are not flagged by ipaddress category checks (100.100.100.200 lives in carrier-grade-NAT space).
_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure / OpenStack IMDS
        "100.100.100.200",  # Alibaba Cloud metadata
        "fd00:ec2::254",  # AWS IMDS over IPv6
    }
)

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Generic, key-free messages. NEVER interpolate the URL or any credential into these.
_MSG_SCHEME = "endpoint scheme must be http or https"
_MSG_NO_HOST = "endpoint URL has no host"
_MSG_UNRESOLVABLE = "endpoint host could not be resolved"
_MSG_NOT_PUBLIC = "endpoint host is not a public address"


class SsrfBlocked(ValueError):
    """Raised when an endpoint URL fails the SSRF policy. Message is always generic + key-free."""


def _unwrap_to_v4(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """Unwrap an IPv6 transition form to its embedded IPv4 address, else return ``ip`` unchanged.

    Covers IPv4-mapped (``::ffff:a.b.c.d``), 6to4 (``2002::/16``), and the NAT64 well-known prefix
    (``64:ff9b::/96``) so an attacker cannot tunnel a blocked IPv4 target through an IPv6 literal.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        sixtofour = getattr(ip, "sixtofour", None)
        if sixtofour is not None:
            return sixtofour
        # NAT64 well-known prefix 64:ff9b::/96 — low 32 bits are the embedded IPv4 address.
        if ip in ipaddress.IPv6Network("64:ff9b::/96"):
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def _ip_is_blocked(raw: str) -> bool:
    """True iff ``raw`` (a literal IP string from getaddrinfo) is NOT a safe public unicast address."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        # Unparseable address from the resolver — fail closed.
        return True

    # Unwrap IPv6 transition forms so an embedded blocked IPv4 is classified as that IPv4.
    ip = _unwrap_to_v4(ip)

    # Explicit metadata/well-known list first (covers ranges category checks miss).
    if str(ip) in _METADATA_IPS or raw in _METADATA_IPS:
        return True

    # Category checks. Any TRUE → blocked. ``is_global`` is the positive gate; the rest are belt-and
    # -suspenders for ranges/implementations where is_global alone is too permissive.
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True

    # Final positive assertion: only globally-routable addresses pass.
    return not ip.is_global


def validate_public_endpoint(endpoint: str) -> str:
    """Validate a visitor-supplied endpoint URL against the SSRF policy.

    Returns the endpoint unchanged on success. Raises :class:`SsrfBlocked` (generic, key-free
    message) on any violation: non-http(s) scheme, missing host, unresolvable host, or ANY resolved
    address that is not a globally-routable public unicast IP.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise SsrfBlocked(_MSG_NO_HOST)

    parts = urlsplit(endpoint.strip())

    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SsrfBlocked(_MSG_SCHEME)

    host = parts.hostname  # already strips brackets from IPv6 literals + userinfo/port
    if not host:
        raise SsrfBlocked(_MSG_NO_HOST)

    # A bare IP literal in the host is checked directly (no DNS); a hostname is resolved to every
    # A/AAAA record and ALL must pass.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if _ip_is_blocked(host):
            raise SsrfBlocked(_MSG_NOT_PUBLIC)
        return endpoint

    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        raise SsrfBlocked(_MSG_UNRESOLVABLE) from None

    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise SsrfBlocked(_MSG_UNRESOLVABLE)

    for addr in resolved:
        if _ip_is_blocked(addr):
            raise SsrfBlocked(_MSG_NOT_PUBLIC)

    return endpoint


__all__ = ["SsrfBlocked", "validate_public_endpoint"]
