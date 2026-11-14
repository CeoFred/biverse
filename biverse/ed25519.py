"""Ed25519 signatures (RFC 8032) in pure Python.

Used to check that an update manifest was published by the Biverse release job.
Python 3.8's standard library has no Ed25519 and the app keeps its runtime
dependencies minimal, so this is the RFC's reference algorithm on extended
coordinates. It is not constant-time: fine for verifying public data and for
signing in CI, not for signing on shared machines.
"""

from __future__ import annotations

import hashlib
from typing import Tuple

Point = Tuple[int, int, int, int]

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


class BadSignature(ValueError):
    pass


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _add(a: Point, b: Point) -> Point:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    pa = (y1 - x1) * (y2 - x2) % P
    pb = (y1 + x1) * (y2 + x2) % P
    pc = t1 * 2 * D * t2 % P
    pd = z1 * 2 * z2 % P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s: int, pt: Point) -> Point:
    q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a: Point, b: Point) -> bool:
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _recover_x(y: int, sign: int) -> int:
    if y >= P:
        raise BadSignature("bad point")
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    if x2 == 0:
        if sign:
            raise BadSignature("bad point")
        return 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        raise BadSignature("bad point")
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)  # type: Point


def _compress(pt: Point) -> bytes:
    x, y, z, _ = pt
    zinv = pow(z, P - 2, P)
    x, y = x * zinv % P, y * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s: bytes) -> Point:
    if len(s) != 32:
        raise BadSignature("bad point length")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return (x, y, 1, x * y % P)


def _expand(secret: bytes) -> Tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes")
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return _compress(_mul(a, G))


def sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(secret)
    pub = _compress(_mul(a, G))
    r = _sha512_int(prefix + msg) % L
    rs = _compress(_mul(r, G))
    h = _sha512_int(rs + pub + msg) % L
    s = (r + h * a) % L
    return rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> None:
    """Raise ``BadSignature`` unless ``signature`` is ``public``'s signature of ``msg``."""
    if len(public) != 32 or len(signature) != 64:
        raise BadSignature("bad key or signature length")
    a = _decompress(public)
    rs = signature[:32]
    r = _decompress(rs)
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        raise BadSignature("bad signature")
    h = _sha512_int(rs + public + msg) % L
    if not _equal(_mul(s, G), _add(r, _mul(h, a))):
        raise BadSignature("the signature does not match")
