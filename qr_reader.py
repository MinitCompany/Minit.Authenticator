"""Đọc mã QR từ file ảnh hoặc từ ảnh đang nằm trong clipboard.

Thử lần lượt các thư viện có trên máy: zxing-cpp (chính) -> pyzbar -> OpenCV.
Nếu không có cái nào thì ném QRUnavailable để giao diện hiện hướng dẫn cài đặt.
Toàn bộ xử lý diễn ra ngay trên máy, không gửi ảnh đi đâu cả.
"""

from __future__ import annotations

INSTALL_HINT = "py -3 -m pip install zxing-cpp pillow"


class QRUnavailable(RuntimeError):
    """Máy chưa có thư viện đọc QR."""


class QRNotFound(ValueError):
    """Ảnh hợp lệ nhưng không tìm thấy mã QR nào."""


# ------------------------------------------------------------------ backends
def _try_zxingcpp(image) -> list[str]:
    import zxingcpp
    results = zxingcpp.read_barcodes(image.convert("RGB"))
    return [r.text for r in results if getattr(r, "text", "")]


def _try_pyzbar(image) -> list[str]:
    from pyzbar import pyzbar
    return [d.data.decode("utf-8", "replace") for d in pyzbar.decode(image) if d.data]


def _try_opencv(image) -> list[str]:
    import cv2
    import numpy as np
    array = np.array(image.convert("RGB"))[:, :, ::-1]        # RGB -> BGR
    ok, texts, _pts, _codes = cv2.QRCodeDetector().detectAndDecodeMulti(array)
    return [t for t in texts if t] if ok else []


_BACKENDS = (_try_zxingcpp, _try_pyzbar, _try_opencv)


def available() -> bool:
    """True nếu máy có ít nhất một thư viện đọc QR và có Pillow để mở ảnh."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    for name in ("zxingcpp", "pyzbar.pyzbar", "cv2"):
        try:
            __import__(name)
            return True
        except ImportError:
            continue
    return False


def _decode(image) -> list[str]:
    errors = []
    for backend in _BACKENDS:
        try:
            texts = backend(image)
        except ImportError:
            continue
        except Exception as exc:                     # thư viện có nhưng lỗi khi chạy
            errors.append(f"{backend.__name__}: {exc}")
            continue
        if texts:
            return texts
    if errors and not available():
        raise QRUnavailable("; ".join(errors))
    if not available():
        raise QRUnavailable(f"Chưa cài thư viện đọc QR. Chạy: {INSTALL_HINT}")
    raise QRNotFound("Không tìm thấy mã QR nào trong ảnh")


# ---------------------------------------------------------------------- API
def _open(path: str):
    try:
        from PIL import Image
    except ImportError as exc:
        raise QRUnavailable(f"Chưa cài Pillow. Chạy: {INSTALL_HINT}") from exc
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        raise ValueError(f"Không mở được ảnh: {exc}") from exc
    return image


def read_image_file(path: str) -> list[str]:
    """Trả về danh sách chuỗi đọc được từ mọi mã QR trong file ảnh."""
    return _decode(_open(path))


def read_clipboard() -> list[str]:
    """Đọc mã QR từ ảnh vừa chụp màn hình (Win+Shift+S) hoặc file ảnh đã copy."""
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise QRUnavailable(f"Chưa cài Pillow. Chạy: {INSTALL_HINT}") from exc

    try:
        data = ImageGrab.grabclipboard()
    except Exception as exc:
        raise ValueError(f"Không đọc được clipboard: {exc}") from exc

    if data is None:
        raise ValueError("Clipboard không có ảnh. Hãy chụp màn hình vùng chứa mã QR "
                         "(Win+Shift+S) rồi thử lại.")

    if isinstance(data, list):                       # clipboard chứa đường dẫn file
        texts: list[str] = []
        for path in data:
            try:
                texts.extend(read_image_file(str(path)))
            except (ValueError, QRNotFound):
                continue
        if not texts:
            raise QRNotFound("Không tìm thấy mã QR trong (các) file đã copy")
        return texts

    return _decode(data)
