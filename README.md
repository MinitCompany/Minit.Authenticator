# Minit Authenticator — App tạo mã 2FA bằng Python

Ứng dụng desktop tạo mã xác thực 2 lớp (TOTP) giống Google Authenticator: nhập chuỗi
key bí mật, app sinh mã 6 số và tự làm mới mỗi 30 giây, có vòng đếm ngược cập nhật
liên tục theo từng giây.

## Tính năng

- Nhập **chuỗi key Base32** hoặc dán thẳng **liên kết `otpauth://`** (lấy từ mã QR)
- **Nhập từ ảnh QR**: quét file ảnh hoặc ảnh chụp màn hình trong clipboard (Ctrl+V) — đọc được
  cả mã QR đăng ký 2FA thông thường lẫn mã QR **"Chuyển tài khoản" của Google Authenticator**
  (gộp nhiều tài khoản trong một ảnh)
- Sinh mã TOTP chuẩn **RFC 6238** — hỗ trợ SHA1/SHA256/SHA512, 6–8 chữ số, chu kỳ 30/60s
- **Lưu lại** tài khoản, tự nạp mỗi lần mở app
- **Mã hoá file dữ liệu bằng mật khẩu chính** (tuỳ chọn) — PBKDF2-HMAC-SHA256 240.000 vòng
- Giao diện tối/sáng, vòng đếm ngược mượt, đổi màu đỏ khi còn ≤ 5 giây
- **Bấm vào thẻ để sao chép mã** vào clipboard
- Ẩn mã (chỉ hiện khi rê chuột), luôn hiện trên cùng, sắp xếp thứ tự
- Xuất/nhập dự phòng dạng danh sách `otpauth://`
- Phần sinh mã, lưu trữ, mã hoá và giao diện **chỉ dùng thư viện chuẩn Python**; riêng chức
  năng quét QR cần thêm 2 gói (đã kèm sẵn trong file .exe)

## Chạy nhanh (không cần đóng gói)

```
py -3 main.py
```

## Đóng gói thành file .exe

Nhấp đúp vào **`build.bat`** (tự cài PyInstaller nếu chưa có). Kết quả:

```
dist\Minit Authenticator.exe
```

Icon của app lấy từ **`icon.ico`** đặt cùng thư mục — muốn đổi icon thì thay file này rồi
build lại.

File exe này chạy độc lập — copy sang máy khác không cần cài Python.

Muốn khởi động nhanh hơn (đổi lại là một thư mục thay vì 1 file duy nhất), sửa
`--onefile` thành `--onedir` trong `build.bat`.

## Cách dùng

1. Bấm **＋** ở góc trên bên phải.
2. Điền **Nhà cung cấp** (VD: Google), **Tên tài khoản** (VD: email) và **Chuỗi key bí mật**.
   - Chuỗi key là đoạn chữ Base32 mà website hiện ra khi bật 2FA (VD: `JBSW Y3DP EHPK 3PXP`).
     Khoảng trắng và chữ thường đều được chấp nhận.
   - Nếu có liên kết `otpauth://totp/...` thì dán thẳng vào ô key — app tự điền hết các ô còn lại.
3. Xem trước mã ngay trong hộp thoại → bấm **Lưu**.
4. Ở màn hình chính, **bấm vào thẻ** để sao chép mã. **Chuột phải** để Sửa / Di chuyển / Xoá.

Menu **⋮** ở góc trên: nhập từ ảnh QR, đặt mật khẩu chính, đổi chủ đề, ẩn mã, ghim trên
cùng, xuất/nhập dự phòng, xem vị trí file dữ liệu.

## Chuyển tài khoản từ Google Authenticator sang

Google Authenticator không cho xem lại chuỗi key, chỉ cho xuất ra **ảnh QR**. Ảnh đó không
chứa key thường mà chứa một gói `otpauth-migration://` gộp nhiều tài khoản, secret nằm ở
dạng byte thô. App này tự giải được gói đó.

Các bước:

1. Trên điện thoại: mở Google Authenticator → **⋮ → Chuyển tài khoản → Xuất tài khoản** →
   chọn các tài khoản cần chuyển. Máy sẽ hiện một hoặc nhiều mã QR.
2. Trên máy tính, mở app này rồi làm 1 trong 2 cách:
   - **Nhanh nhất:** chụp màn hình vùng chứa mã QR (hoặc chụp bằng điện thoại rồi copy ảnh),
     sau đó bấm **Ctrl+V** ngay trong app.
   - Hoặc lưu ảnh QR thành file rồi vào **⋮ → Nhập từ ảnh QR…** (chọn được nhiều file cùng lúc).
3. App liệt kê các tài khoản tìm thấy để bạn xác nhận trước khi thêm.

Lưu ý:

- Nếu bạn có nhiều tài khoản, Google chia thành **nhiều ảnh QR**. App sẽ báo "đây là phần
  1/3…" — cứ quét lần lượt hết các ảnh, tài khoản trùng sẽ tự bỏ qua.
- Tài khoản loại **HOTP** (đếm theo lượt, rất hiếm) sẽ bị bỏ qua vì app này chỉ tạo mã TOTP.
- ⚠️ **Tuyệt đối không đưa ảnh QR export lên các trang "decode QR online"** — một ảnh đó
  chứa toàn bộ hạt giống 2FA của mọi tài khoản bạn có. App này giải mã hoàn toàn offline.

### Còn thuật toán thì sao?

Gần như 100% dịch vụ dùng bộ mặc định **SHA1 / 6 chữ số / 30 giây**, và Google Authenticator
cũng chỉ chạy đúng bộ này — nên bạn không cần biết gì thêm, cứ để nguyên ba ô mặc định
trong hộp thoại thêm tài khoản. Khi nhập từ mã QR, app đọc thẳng thuật toán và số chữ số
ghi trong gói dữ liệu nên luôn khớp.

## Nơi lưu dữ liệu

```
%APPDATA%\Minit Authenticator\vault.json     ← tài khoản
%APPDATA%\Minit Authenticator\settings.json  ← cài đặt giao diện
```

**Chế độ portable:** tạo một file `vault.json` rỗng đặt cạnh `Minit Authenticator.exe`,
app sẽ đọc/ghi dữ liệu ngay tại thư mục đó (tiện để mang theo USB).

## Bảo mật — đọc kỹ

- Mặc định `vault.json` là **văn bản thường**. Ai đọc được file đó thì tạo được mã 2FA
  của bạn. Hãy vào menu **⋮ → Đặt mật khẩu chính** để mã hoá file.
- Mã hoá dùng PBKDF2-HMAC-SHA256 (240k vòng) sinh khoá, dòng khoá HMAC-SHA256 ở chế độ
  đếm, xác thực bằng HMAC-SHA256 theo kiểu encrypt-then-MAC. **Quên mật khẩu là mất dữ
  liệu** — không có cách khôi phục.
- File xuất dự phòng chứa key ở dạng thô. Cất giữ như cất mật khẩu.
- Đây là công cụ cá nhân trên máy tính; nó không đồng bộ đám mây và không thay thế được
  khoá bảo mật phần cứng.

## Kiểm tra

```
py -3 test_core.py     # vector chuẩn RFC 6238, otpauth://, mã hoá kho dữ liệu
py -3 test_qr.py       # giải gói otpauth-migration:// + vẽ ảnh QR thật rồi quét ngược
```

## Cấu trúc mã nguồn

| File | Vai trò |
|---|---|
| `main.py` | Điểm khởi động |
| `ui_app.py` | Toàn bộ giao diện Tkinter (thẻ tài khoản, vòng đếm, hộp thoại) |
| `totp_core.py` | Thuật toán HOTP/TOTP, xử lý chuỗi key và `otpauth://` |
| `otpauth_migration.py` | Giải gói `otpauth-migration://` của Google Authenticator (tự đọc protobuf) |
| `qr_reader.py` | Đọc mã QR từ file ảnh / clipboard |
| `vault.py` | Đọc/ghi + mã hoá kho tài khoản, cài đặt |
| `icon.ico` | Icon của app (dùng cho cả cửa sổ lẫn file exe) |
| `test_core.py`, `test_qr.py` | Bộ kiểm tra |
| `build.bat` | Đóng gói ra `.exe` |
