"""Lõi tính mã TOTP/HOTP (RFC 4226 / RFC 6238) - chỉ dùng thư viện chuẩn."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import struct
import time
from urllib.parse import parse_qs, unquote, urlparse

ALGORITHMS = ("SHA1", "SHA256", "SHA512")
DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30
DEFAULT_ALGORITHM = "SHA1"


class InvalidSecret(ValueError):
    """Chuỗi key không hợp lệ (không phải Base32)."""


def normalize_secret(secret: str) -> str:
    """Bỏ khoảng trắng/gạch nối, viết hoa và thêm '=' cho đủ bội số 8."""
    cleaned = re.sub(r"[\s\-_]", "", secret or "").upper()
    if not cleaned:
        raise InvalidSecret("Chuỗi key trống")
    cleaned = cleaned.rstrip("=")
    if not re.fullmatch(r"[A-Z2-7]+", cleaned):
        raise InvalidSecret("Chuỗi key chỉ được chứa ký tự A-Z và 2-7 (Base32)")
    return cleaned + "=" * (-len(cleaned) % 8)


def decode_secret(secret: str) -> bytes:
    try:
        key = base64.b32decode(normalize_secret(secret), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidSecret("Không giải mã được chuỗi key Base32") from exc
    if not key:
        raise InvalidSecret("Chuỗi key trống sau khi giải mã")
    return key


def hotp(key: bytes, counter: int, digits: int = DEFAULT_DIGITS,
         algorithm: str = DEFAULT_ALGORITHM) -> str:
    digest = getattr(hashlib, algorithm.lower())
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def totp(secret: str, at: float | None = None, digits: int = DEFAULT_DIGITS,
         period: int = DEFAULT_PERIOD, algorithm: str = DEFAULT_ALGORITHM) -> str:
    now = time.time() if at is None else at
    return hotp(decode_secret(secret), int(now // period), digits, algorithm)


def seconds_remaining(at: float | None = None, period: int = DEFAULT_PERIOD) -> float:
    now = time.time() if at is None else at
    return period - (now % period)


def format_code(code: str) -> str:
    """123456 -> '123 456', 12345678 -> '1234 5678'."""
    half = len(code) // 2
    return f"{code[:half]} {code[half:]}" if len(code) % 2 == 0 else code


def validate_secret(secret: str) -> str:
    """Trả về chuỗi key đã chuẩn hoá, ném InvalidSecret nếu sai."""
    decode_secret(secret)
    return normalize_secret(secret)


def parse_otpauth_uri(uri: str) -> dict:
    """Phân tích liên kết otpauth://totp/Issuer:tai_khoan?secret=...&issuer=..."""
    parsed = urlparse((uri or "").strip())
    if parsed.scheme.lower() != "otpauth":
        raise ValueError("Liên kết phải bắt đầu bằng otpauth://")
    if parsed.netloc.lower() != "totp":
        raise ValueError("Chỉ hỗ trợ loại 'totp' (không hỗ trợ hotp)")

    params = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items() if v}
    secret = params.get("secret", "")
    if not secret:
        raise ValueError("Liên kết thiếu tham số secret")

    label = unquote(parsed.path.lstrip("/"))
    issuer, name = "", label
    if ":" in label:
        issuer, name = (part.strip() for part in label.split(":", 1))
    issuer = params.get("issuer", issuer).strip()

    algorithm = params.get("algorithm", DEFAULT_ALGORITHM).upper()
    if algorithm not in ALGORITHMS:
        algorithm = DEFAULT_ALGORITHM

    try:
        digits = int(params.get("digits", DEFAULT_DIGITS))
    except ValueError:
        digits = DEFAULT_DIGITS
    if digits not in (6, 7, 8):
        digits = DEFAULT_DIGITS

    try:
        period = int(params.get("period", DEFAULT_PERIOD))
    except ValueError:
        period = DEFAULT_PERIOD
    if period <= 0:
        period = DEFAULT_PERIOD

    return {
        "issuer": issuer,
        "name": name.strip(),
        "secret": validate_secret(secret),
        "digits": digits,
        "period": period,
        "algorithm": algorithm,
    }


def build_otpauth_uri(account: dict) -> str:
    from urllib.parse import quote
    issuer = account.get("issuer", "").strip()
    name = account.get("name", "").strip() or "account"
    label = quote(f"{issuer}:{name}" if issuer else name, safe="")
    query = [f"secret={account['secret']}"]
    if issuer:
        query.append(f"issuer={quote(issuer, safe='')}")
    query.append(f"algorithm={account.get('algorithm', DEFAULT_ALGORITHM)}")
    query.append(f"digits={account.get('digits', DEFAULT_DIGITS)}")
    query.append(f"period={account.get('period', DEFAULT_PERIOD)}")
    return f"otpauth://totp/{label}?" + "&".join(query)
