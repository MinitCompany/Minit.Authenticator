"""Lưu trữ tài khoản 2FA. Hỗ trợ tuỳ chọn khoá bằng mật khẩu chính.

File dữ liệu (Windows): %APPDATA%\\Minit Authenticator\\vault.json
Mã hoá: PBKDF2-HMAC-SHA256 -> keystream HMAC-SHA256 (chế độ đếm) + xác thực
HMAC-SHA256 theo kiểu encrypt-then-MAC. Toàn bộ dùng thư viện chuẩn Python.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import sys
import tempfile
import uuid

VAULT_VERSION = 2
KDF_ITERATIONS = 240_000
SALT_BYTES = 16
NONCE_BYTES = 16


class WrongPassword(Exception):
    """Mật khẩu chính không đúng hoặc file dữ liệu đã bị sửa đổi."""


class VaultCorrupted(Exception):
    """File dữ liệu hỏng / không đọc được."""


# --------------------------------------------------------------------------- paths
def data_dir() -> str:
    portable = os.path.join(_app_dir(), "vault.json")
    if os.path.exists(portable):          # chế độ portable: đặt vault.json cạnh exe
        return _app_dir()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Minit Authenticator")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, "minit-authenticator")
    os.makedirs(path, exist_ok=True)
    return path


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def vault_path() -> str:
    return os.path.join(data_dir(), "vault.json")


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


# ------------------------------------------------------------------------- crypto
def _derive(password: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    material = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, 64)
    return material[:32], material[32:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _encrypt(plaintext: bytes, password: str) -> dict:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    enc_key, mac_key = _derive(password, salt, KDF_ITERATIONS)
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext))))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return {
        "version": VAULT_VERSION,
        "encrypted": True,
        "kdf": {"name": "pbkdf2-sha256", "iterations": KDF_ITERATIONS, "salt": b64(salt)},
        "nonce": b64(nonce),
        "ciphertext": b64(ciphertext),
        "tag": b64(tag),
    }


def _decrypt(blob: dict, password: str) -> bytes:
    try:
        salt = base64.b64decode(blob["kdf"]["salt"])
        iterations = int(blob["kdf"]["iterations"])
        nonce = base64.b64decode(blob["nonce"])
        ciphertext = base64.b64decode(blob["ciphertext"])
        tag = base64.b64decode(blob["tag"])
    except (KeyError, ValueError, TypeError) as exc:
        raise VaultCorrupted("Cấu trúc file mã hoá không hợp lệ") from exc

    enc_key, mac_key = _derive(password, salt, iterations)
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()):
        raise WrongPassword("Mật khẩu không đúng")
    return bytes(a ^ b for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext))))


# -------------------------------------------------------------------------- vault
def new_account(issuer: str = "", name: str = "", secret: str = "",
                digits: int = 6, period: int = 30, algorithm: str = "SHA1") -> dict:
    return {
        "id": uuid.uuid4().hex,
        "issuer": issuer.strip(),
        "name": name.strip(),
        "secret": secret,
        "digits": digits,
        "period": period,
        "algorithm": algorithm,
    }


def is_encrypted() -> bool:
    path = vault_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return bool(json.load(fh).get("encrypted"))
    except (OSError, json.JSONDecodeError):
        return False


def load(password: str | None = None) -> list[dict]:
    """Đọc danh sách tài khoản. Ném WrongPassword nếu mật khẩu sai."""
    path = vault_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultCorrupted(f"Không đọc được {path}") from exc

    if blob.get("encrypted"):
        if password is None:
            raise WrongPassword("Cần mật khẩu chính")
        try:
            data = json.loads(_decrypt(blob, password).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VaultCorrupted("Dữ liệu giải mã bị hỏng") from exc
    else:
        data = blob

    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        raise VaultCorrupted("Danh sách tài khoản không hợp lệ")
    return [_sanitize(item) for item in accounts if isinstance(item, dict) and item.get("secret")]


def save(accounts: list[dict], password: str | None = None) -> None:
    payload = {"version": VAULT_VERSION, "encrypted": False, "accounts": accounts}
    blob = _encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"), password) \
        if password else payload
    _atomic_write(vault_path(), json.dumps(blob, ensure_ascii=False, indent=2))


def _sanitize(item: dict) -> dict:
    return {
        "id": item.get("id") or uuid.uuid4().hex,
        "issuer": str(item.get("issuer", "")),
        "name": str(item.get("name", "")),
        "secret": str(item.get("secret", "")),
        "digits": int(item.get("digits", 6)),
        "period": int(item.get("period", 30)) or 30,
        "algorithm": str(item.get("algorithm", "SHA1")).upper(),
    }


# ----------------------------------------------------------------------- settings
DEFAULT_SETTINGS = {"theme": "dark", "hide_codes": False, "always_on_top": False}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    try:
        _atomic_write(settings_path(), json.dumps(settings, ensure_ascii=False, indent=2))
    except OSError:
        pass


def _atomic_write(path: str, text: str) -> None:
    """Ghi qua file tạm rồi replace để không mất dữ liệu nếu tắt máy giữa chừng."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
