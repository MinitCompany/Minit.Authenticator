"""Kiểm tra luồng nhập từ mã QR của Google Authenticator.

Tự dựng một gói otpauth-migration:// đúng chuẩn (encode protobuf thủ công), vẽ ra
ảnh QR thật, rồi cho app quét ngược lại và so khớp từng trường.

Chạy: py -3 test_qr.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import otpauth_migration as migration  # noqa: E402
import qr_reader  # noqa: E402
import totp_core as tc  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"[{'OK ' if ok else 'SAI'}] {label}: {got!r}" + ("" if ok else f" (mong đợi {want!r})"))


# ------------------------------------------------------- encoder protobuf (chỉ để test)
def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def tag(field: int, wire: int) -> bytes:
    return varint(field << 3 | wire)


def blob(field: int, data: bytes) -> bytes:
    return tag(field, 2) + varint(len(data)) + data


def num(field: int, value: int) -> bytes:
    return tag(field, 0) + varint(value)


def otp_params(secret: bytes, name: str, issuer: str, algo: int, digits: int, otype: int) -> bytes:
    body = (blob(1, secret) + blob(2, name.encode()) + blob(3, issuer.encode())
            + num(4, algo) + num(5, digits) + num(6, otype))
    return blob(1, body)


def make_qr(text: str, path: str) -> str:
    """Vẽ chuỗi thành ảnh QR PNG thật (dùng zxing-cpp), trả về đường dẫn."""
    import zxingcpp
    from PIL import Image
    if hasattr(zxingcpp, "create_barcode"):          # API mới
        barcode = zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode), scale=6)
    else:
        barcode = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, text, 600, 600)
    view = memoryview(barcode)
    height, width = view.shape
    Image.frombytes("L", (width, height), view.tobytes()).save(path)
    return path


def build_migration_uri(entries, batch_index=0, batch_size=1) -> str:
    payload = b"".join(entries) + num(2, 1) + num(3, batch_size) + num(4, batch_index) + num(5, 42)
    return "otpauth-migration://offline?data=" + quote(base64.b64encode(payload).decode(), safe="")


def main() -> int:
    secret_a = base64.b32decode("JBSWY3DPEHPK3PXP")
    secret_b = base64.b32decode("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    secret_c = base64.b32decode("MZXW6YTBOI======")

    uri = build_migration_uri([
        otp_params(secret_a, "nguyenvana@gmail.com", "Google", 1, 1, 2),   # SHA1, 6 số, TOTP
        otp_params(secret_b, "vana-dev", "GitHub", 2, 2, 2),               # SHA256, 8 số, TOTP
        otp_params(secret_c, "0987654321", "Ngân hàng ACB", 1, 1, 1),      # HOTP -> phải bị loại
    ], batch_index=0, batch_size=2)

    # --- 1. giải trực tiếp từ chuỗi ---------------------------------------
    payload = migration.decode_migration_uri(uri)
    check("số tài khoản trong gói", len(payload["accounts"]), 3)
    check("batch_size", payload["batch_size"], 2)
    check("batch_index", payload["batch_index"], 0)

    a, b, c = payload["accounts"]
    check("tk1 issuer", a["issuer"], "Google")
    check("tk1 name", a["name"], "nguyenvana@gmail.com")
    check("tk1 secret (Base32)", a["secret"], "JBSWY3DPEHPK3PXP")
    check("tk1 digits", a["digits"], 6)
    check("tk1 algorithm", a["algorithm"], "SHA1")
    check("tk1 type", a["type"], "totp")
    check("tk2 algorithm", b["algorithm"], "SHA256")
    check("tk2 digits", b["digits"], 8)
    check("tk2 secret", b["secret"], "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    check("tk3 bị nhận diện là HOTP", c["type"], "hotp")
    check("tên có dấu tiếng Việt", c["issuer"], "Ngân hàng ACB")

    # mã sinh ra từ secret vừa giải phải khớp với mã từ chuỗi key gốc
    check("mã TOTP khớp chuỗi key gốc",
          tc.totp(a["secret"], at=1234567890),
          tc.totp("JBSWY3DPEHPK3PXP", at=1234567890))

    # --- 2. vẽ QR thật rồi quét ngược -------------------------------------
    try:
        import zxingcpp
    except ImportError:
        print("\n[BỎ QUA] chưa cài zxing-cpp nên không test được phần quét ảnh")
        print("TẤT CẢ ĐỀU ĐẠT" if not failures else f"CÓ {failures} MỤC SAI")
        return 1 if failures else 0

    folder = tempfile.mkdtemp(prefix="qrtest-")
    tmp = make_qr(uri, os.path.join(folder, "export.png"))
    check("đã tạo ảnh QR", os.path.getsize(tmp) > 0, True)

    texts = qr_reader.read_image_file(tmp)
    check("số mã QR đọc được", len(texts), 1)
    check("chuỗi quét ra khớp chuỗi gốc", texts[0], uri)

    scanned = migration.decode_migration_uri(texts[0])
    check("secret sau khi quét ảnh", scanned["accounts"][0]["secret"], "JBSWY3DPEHPK3PXP")

    # --- 3. QR đăng ký 2FA thông thường (otpauth://) ------------------------
    plain = "otpauth://totp/GitHub:me%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=GitHub"
    tmp2 = make_qr(plain, os.path.join(folder, "setup.png"))
    check("quét QR đăng ký thường",
          tc.parse_otpauth_uri(qr_reader.read_image_file(tmp2)[0])["secret"], "JBSWY3DPEHPK3PXP")

    # --- 4. các trường hợp hỏng -------------------------------------------
    for bad, why in [("otpauth-migration://offline?data=", "thiếu data"),
                     ("otpauth-migration://offline?data=!!!!", "base64 sai"),
                     ("http://example.com", "sai scheme")]:
        try:
            migration.decode_migration_uri(bad)
            check(f"chặn chuỗi hỏng ({why})", "không báo lỗi", "MigrationError")
        except migration.MigrationError:
            check(f"chặn chuỗi hỏng ({why})", "MigrationError", "MigrationError")

    print()
    print("TẤT CẢ ĐỀU ĐẠT" if not failures else f"CÓ {failures} MỤC SAI")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
