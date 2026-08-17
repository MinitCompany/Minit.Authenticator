"""Điểm khởi động ứng dụng Authenticator."""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        from ui_app import AuthenticatorApp
    except ImportError as exc:  # thiếu tkinter
        print(f"Không nạp được giao diện: {exc}", file=sys.stderr)
        return 1

    app = AuthenticatorApp()
    if not getattr(app, "ready", False):
        return 0
    app.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        try:
            import tkinter.messagebox as mb
            mb.showerror("Minit Authenticator", traceback.format_exc())
        except Exception:
            traceback.print_exc()
        sys.exit(1)
