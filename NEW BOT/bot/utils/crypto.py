"""
Cryptographic helpers.

Uses Python's standard-library cryptographic primitives only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_token(
    length: int = 32,
) -> str:

    length = max(
        16,
        min(
            int(length),
            256,
        ),
    )

    return secrets.token_urlsafe(
        length
    )[:length]


def generate_numeric_code(
    digits: int = 6,
) -> str:

    digits = max(
        4,
        min(
            int(digits),
            12,
        ),
    )

    minimum = 10 ** (
        digits - 1
    )

    maximum = (
        10 ** digits
    ) - 1

    return str(
        secrets.randbelow(
            maximum - minimum + 1
        )
        + minimum
    )


def hash_token(
    token: str,
    *,
    salt: bytes | None = None,
) -> str:

    if salt is None:
        salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(token).encode("utf-8"),
        salt,
        200_000,
    )

    return (
        salt.hex()
        + ":"
        + digest.hex()
    )


def verify_token(
    token: str,
    stored_hash: str,
) -> bool:

    try:

        salt_hex, digest_hex = (
            str(stored_hash).split(
                ":",
                1,
            )
        )

        salt = bytes.fromhex(
            salt_hex
        )

        expected = bytes.fromhex(
            digest_hex
        )

    except (
        ValueError,
        TypeError,
    ):

        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        str(token).encode("utf-8"),
        salt,
        200_000,
    )

    return hmac.compare_digest(
        actual,
        expected,
    )


def hmac_sign(
    value: str,
    secret: str,
) -> str:

    return hmac.new(
        str(secret).encode(
            "utf-8"
        ),
        str(value).encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()


def hmac_verify(
    value: str,
    signature: str,
    secret: str,
) -> bool:

    expected = hmac_sign(
        value,
        secret,
    )

    return hmac.compare_digest(
        expected,
        str(signature),
    )


__all__ = [
    "generate_token",
    "generate_numeric_code",
    "hash_token",
    "verify_token",
    "hmac_sign",
    "hmac_verify",
]