"""Giải mã liên kết otpauth-migration:// — mã QR "Chuyển tài khoản" của Google Authenticator.

Mã QR đó không chứa chuỗi key thường mà chứa một gói protobuf (đã base64) gộp
nhiều tài khoản. Module này tự đọc protobuf bằng thư viện chuẩn, không cần cài
thư viện protobuf.

Cấu trúc gói (do cộng đồng dịch ngược, ổn định nhiều năm nay):

    MigrationPayload
      1: repeated OtpParameters otp_parameters
           1: bytes  secret        <- byte thô, phải mã hoá Base32 mới thành key
           2: string name
           3: string issuer
           4: enum   algorithm     0/1=SHA1, 2=SHA256, 3=SHA512, 4=MD5
           5: enum   digits        0/1=6 số, 2=8 số
           6: enum   type          1=HOTP, 0/2=TOTP
           7: int64  counter       (chỉ dùng cho HOTP)
      2: int32 version
      3: int32 batch_size          <- tổng số ảnh QR khi export bị chia nhỏ
      4: int32 batch_index         <- ảnh QR này là phần thứ mấy (đếm từ 0)
      5: int32 batch_id
"""

from __future__ import annotations

import base64
import binascii
from urllib.parse import unquote, urlparse

SCHEME = "otpauth-migration"

ALGORITHM_NAMES = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
DIGIT_COUNTS = {0: 6, 1: 6, 2: 8}
OTP_TYPES = {0: "totp", 1: "hotp", 2: "totp"}

# Google Authenticator luôn dùng chu kỳ 30 giây; gói dữ liệu không chứa trường này.
PERIOD = 30


class MigrationError(ValueError):
    """Chuỗi otpauth-migration:// không hợp lệ hoặc gói dữ liệu hỏng."""


# ------------------------------------------------------------------- protobuf
def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise MigrationError("Gói dữ liệu bị cắt cụt")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise MigrationError("Số varint quá dài")


def _iter_fields(data: bytes):
    """Duyệt lần lượt các trường protobuf: trả về (số hiệu trường, wire type, giá trị)."""
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            raise MigrationError("Số hiệu trường không hợp lệ")
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 2:
            length, pos = _read_varint(data, pos)
            if pos + length > len(data):
                raise MigrationError("Gói dữ liệu bị cắt cụt")
            value, pos = data[pos:pos + length], pos + length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if pos + size > len(data):
                raise MigrationError("Gói dữ liệu bị cắt cụt")
            value, pos = int.from_bytes(data[pos:pos + size], "little"), pos + size
        else:
            raise MigrationError(f"Kiểu dữ liệu protobuf không hỗ trợ: {wire}")
        yield field, wire, value


def _decode_otp_parameters(blob: bytes) -> dict | None:
    secret = b""
    name = issuer = ""
    algorithm_id, digits_id, type_id, counter = 1, 1, 2, 0

    for field, wire, value in _iter_fields(blob):
        if field == 1 and wire == 2:
            secret = value
        elif field == 2 and wire == 2:
            name = value.decode("utf-8", "replace")
        elif field == 3 and wire == 2:
            issuer = value.decode("utf-8", "replace")
        elif field == 4 and wire == 0:
            algorithm_id = value
        elif field == 5 and wire == 0:
            digits_id = value
        elif field == 6 and wire == 0:
            type_id = value
        elif field == 7 and wire == 0:
            counter = value

    if not secret:
        return None

    # Nhãn đôi khi ở dạng "NhàCungCấp:tên" trong khi trường issuer để trống
    name = name.strip()
    if not issuer and ":" in name:
        issuer, name = (part.strip() for part in name.split(":", 1))

    return {
        "issuer": issuer.strip(),
        "name": name,
        "secret": base64.b32encode(secret).decode("ascii").rstrip("="),
        "digits": DIGIT_COUNTS.get(digits_id, 6),
        "period": PERIOD,
        "algorithm": ALGORITHM_NAMES.get(algorithm_id, "SHA1"),
        "type": OTP_TYPES.get(type_id, "totp"),
        "counter": counter,
    }


# ----------------------------------------------------------------------- API
def decode_payload(raw: bytes) -> dict:
    """Giải gói protobuf đã base64-decode."""
    accounts: list[dict] = []
    meta = {"version": 0, "batch_size": 1, "batch_index": 0, "batch_id": 0}

    for field, wire, value in _iter_fields(raw):
        if field == 1 and wire == 2:
            item = _decode_otp_parameters(value)
            if item:
                accounts.append(item)
        elif field == 2 and wire == 0:
            meta["version"] = value
        elif field == 3 and wire == 0:
            meta["batch_size"] = value
        elif field == 4 and wire == 0:
            meta["batch_index"] = value
        elif field == 5 and wire == 0:
            meta["batch_id"] = value

    if not accounts:
        raise MigrationError("Không tìm thấy tài khoản nào trong gói dữ liệu")
    return {"accounts": accounts, **meta}


def decode_migration_uri(uri: str) -> dict:
    """otpauth-migration://offline?data=... -> {'accounts': [...], 'batch_size': n, ...}"""
    text = (uri or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() != SCHEME:
        raise MigrationError("Liên kết phải bắt đầu bằng otpauth-migration://")

    # Tự tách tham số thay vì dùng parse_qs: parse_qs biến dấu '+' thành khoảng
    # trắng, mà '+' lại là ký tự hợp lệ trong base64 nên sẽ làm hỏng dữ liệu.
    encoded = ""
    for part in parsed.query.split("&"):
        if part.startswith("data="):
            encoded = unquote(part[len("data="):])
            break
    if not encoded:
        raise MigrationError("Liên kết thiếu tham số data")

    encoded = encoded.replace(" ", "+").replace("\n", "").replace("\r", "")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.b64decode(padded)
    except (binascii.Error, ValueError):
        try:
            raw = base64.urlsafe_b64decode(padded)
        except (binascii.Error, ValueError) as exc:
            raise MigrationError("Phần data không phải base64 hợp lệ") from exc

    return decode_payload(raw)


def is_migration_uri(text: str) -> bool:
    return (text or "").strip().lower().startswith(SCHEME + "://")
