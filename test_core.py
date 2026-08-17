"""Kiểm tra lõi TOTP bằng vector chuẩn RFC 6238 + thử mã hoá kho dữ liệu.

Chạy: py -3 test_core.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totp_core as tc  # noqa: E402
import vault  # noqa: E402

failures = 0


def check(label: str, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"[{'OK ' if ok else 'SAI'}] {label}: {got!r}" + ("" if ok else f" (mong đợi {want!r})"))


def b32(seed_ascii: str) -> str:
    return base64.b32encode(seed_ascii.encode()).decode()


def main() -> int:
    # --- RFC 6238 Appendix B (mã 8 chữ số) -----------------------------------
    s1 = b32("12345678901234567890")
    s256 = b32("12345678901234567890123456789012")
    s512 = b32("1234567890123456789012345678901234567890123456789012345678901234")

    vectors = [
        (59, s1, "SHA1", "94287082"),
        (59, s256, "SHA256", "46119246"),
        (59, s512, "SHA512", "90693936"),
        (1111111109, s1, "SHA1", "07081804"),
        (1111111111, s1, "SHA1", "14050471"),
        (1234567890, s1, "SHA1", "89005924"),
        (2000000000, s1, "SHA1", "69279037"),
        (20000000000, s1, "SHA1", "65353130"),
        (1111111109, s256, "SHA256", "68084774"),
        (1234567890, s512, "SHA512", "93441116"),
    ]
    for at, secret, algo, want in vectors:
        check(f"RFC6238 {algo} t={at}",
              tc.totp(secret, at=at, digits=8, period=30, algorithm=algo), want)

    # --- chuẩn hoá key & định dạng ------------------------------------------
    check("normalize (có khoảng trắng/thường)", tc.validate_secret("jbsw y3dp ehpk 3pxp"),
          "JBSWY3DPEHPK3PXP")
    check("mã 6 số của JBSWY3DPEHPK3PXP tại t=0", tc.totp("JBSWY3DPEHPK3PXP", at=0), "282760")
    check("format_code", tc.format_code("123456"), "123 456")

    for bad in ("", "abc!def", "11111111"):
        try:
            tc.validate_secret(bad)
            check(f"key sai bị chặn: {bad!r}", "không báo lỗi", "InvalidSecret")
        except tc.InvalidSecret:
            check(f"key sai bị chặn: {bad!r}", "InvalidSecret", "InvalidSecret")

    # --- otpauth URI ---------------------------------------------------------
    parsed = tc.parse_otpauth_uri(
        "otpauth://totp/GitHub:me%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=GitHub&digits=6&period=30")
    check("URI issuer", parsed["issuer"], "GitHub")
    check("URI name", parsed["name"], "me@example.com")
    check("URI secret", parsed["secret"], "JBSWY3DPEHPK3PXP")
    account = vault.new_account(**parsed)
    check("URI khứ hồi", tc.parse_otpauth_uri(tc.build_otpauth_uri(account))["secret"],
          "JBSWY3DPEHPK3PXP")

    # --- kho dữ liệu ---------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        vault.data_dir = lambda: tmp
        accounts = [vault.new_account("Google", "me@gmail.com", "JBSWY3DPEHPK3PXP")]

        vault.save(accounts, None)
        check("lưu/đọc không mật khẩu", vault.load()[0]["secret"], "JBSWY3DPEHPK3PXP")
        check("cờ encrypted (không mật khẩu)", vault.is_encrypted(), False)

        vault.save(accounts, "mat-khau-manh")
        check("cờ encrypted (có mật khẩu)", vault.is_encrypted(), True)
        check("giải mã đúng mật khẩu", vault.load("mat-khau-manh")[0]["name"], "me@gmail.com")
        with open(vault.vault_path(), "r", encoding="utf-8") as fh:
            check("key không lộ trong file", "JBSWY3DPEHPK3PXP" in fh.read(), False)
        try:
            vault.load("sai-mat-khau")
            check("mật khẩu sai bị chặn", "không báo lỗi", "WrongPassword")
        except vault.WrongPassword:
            check("mật khẩu sai bị chặn", "WrongPassword", "WrongPassword")

    print()
    print("TẤT CẢ ĐỀU ĐẠT" if not failures else f"CÓ {failures} MỤC SAI")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
