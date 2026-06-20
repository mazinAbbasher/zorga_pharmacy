"""Minimal, dependency-free RSA signing/verification (PKCS#1 v1.5, SHA-256).

The *shipped application* only ever calls :func:`verify` with the embedded
public key, so it needs no third-party crypto library and no native build —
this keeps the PyInstaller bundle small and avoids hook surprises.

The *developer tools* (key generation and license signing) also live here, so
the same, audited code path is used on both sides.

This is intentionally small. It implements the standard RSASSA-PKCS1-v1_5
scheme, which is sound for signature verification. The threat model is
"prevent casual copying of the program to another laptop"; a sophisticated
attacker who unpacks the bundle could still patch the check out (see
LICENSING.md).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets

# DER-encoded DigestInfo prefix for SHA-256 (RFC 8017 §9.2, Note 1).
_SHA256_DIGESTINFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _emsa_pkcs1_v15(message: bytes, em_len: int) -> bytes:
    """EMSA-PKCS1-v1_5 encoding of *message* into *em_len* bytes."""
    digest = hashlib.sha256(message).digest()
    t = _SHA256_DIGESTINFO_PREFIX + digest
    if em_len < len(t) + 11:
        raise ValueError("intended encoded message length too short")
    ps = b"\xff" * (em_len - len(t) - 3)
    return b"\x00\x01" + ps + b"\x00" + t


def _byte_len(n: int) -> int:
    return (n.bit_length() + 7) // 8


def sign(private_key: dict, message: bytes) -> bytes:
    """Sign *message*; ``private_key`` is ``{"n": int, "e": int, "d": int}``."""
    n, d = private_key["n"], private_key["d"]
    k = _byte_len(n)
    em = _emsa_pkcs1_v15(message, k)
    m = int.from_bytes(em, "big")
    s = pow(m, d, n)
    return s.to_bytes(k, "big")


def verify(public_key: tuple[int, int], message: bytes, signature: bytes) -> bool:
    """Return True iff *signature* over *message* is valid for ``(n, e)``."""
    n, e = public_key
    if n <= 0 or e <= 0:
        return False  # fail closed when no key has been provisioned
    k = _byte_len(n)
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    m = pow(s, e, n)
    try:
        em = m.to_bytes(k, "big")
        expected = _emsa_pkcs1_v15(message, k)
    except (OverflowError, ValueError):
        return False
    return hmac.compare_digest(em, expected)


# --------------------------------------------------------------------------
# Key generation (developer side only — never called by the shipped app).
# --------------------------------------------------------------------------
def _is_probable_prime(n: int, rounds: int = 40) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def generate_keypair(bits: int = 2048) -> dict:
    """Generate an RSA keypair. Returns ``{"n", "e", "d"}`` (all ints)."""
    e = 65537
    half = bits // 2
    while True:
        p = _gen_prime(half)
        q = _gen_prime(bits - half)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) != 1:
            continue
        d = pow(e, -1, phi)
        return {"n": n, "e": e, "d": d}
