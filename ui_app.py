"""Giao diện Authenticator - Tkinter, cập nhật liên tục theo từng giây."""

from __future__ import annotations

import math
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import otpauth_migration as migration
import qr_reader
import totp_core as tc
import vault

APP_NAME = "Minit Authenticator"
ICON_FILE = "icon.ico"

MIGRATION_HINT = ("Đây là gói 'Chuyển tài khoản' của Google Authenticator, chứa nhiều tài "
                  "khoản cùng lúc chứ không phải một chuỗi key.\nHãy đóng hộp thoại này và "
                  "dùng menu ⋮ → Nhập từ ảnh QR…")

PALETTES = {
    "dark": {
        "bg": "#16181d",
        "header": "#1e2127",
        "card": "#242830",
        "card_hover": "#2c313a",
        "text": "#e8eaed",
        "subtext": "#9aa0a6",
        "accent": "#8ab4f8",
        "warn": "#f28b82",
        "border": "#343a44",
        "entry": "#1b1e24",
        "btn": "#2c313a",
        "btn_hover": "#39404b",
        "toast": "#3c4250",
    },
    "light": {
        "bg": "#f1f3f6",
        "header": "#ffffff",
        "card": "#ffffff",
        "card_hover": "#eef2fb",
        "text": "#1f2328",
        "subtext": "#5f6368",
        "accent": "#1a73e8",
        "warn": "#d93025",
        "border": "#dde1e6",
        "entry": "#ffffff",
        "btn": "#e8ebf0",
        "btn_hover": "#dbe0e8",
        "toast": "#323639",
    },
}

FONT = "Segoe UI"

SCALE = 1.0  # hệ số theo DPI màn hình, gán trong AuthenticatorApp.__init__


def px(value: float) -> int:
    """Quy đổi hằng số pixel (thiết kế ở 96 DPI) sang DPI thực của màn hình."""
    return int(round(value * SCALE))


def enable_dpi_awareness() -> None:
    """Báo Windows rằng app tự xử lý DPI -> chữ nét thay vì bị phóng to mờ."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


# =========================================================================== card
class CardView:
    """Một thẻ tài khoản, vẽ bằng Canvas để có góc bo tròn + vòng đếm ngược."""

    def __init__(self, parent: tk.Widget, app: "AuthenticatorApp", account: dict):
        self.app = app
        self.account = account
        self.colors = app.colors
        self.counter = None
        self.code = ""
        self.hovering = False
        self.error = None
        self.height = px(88)

        self.canvas = tk.Canvas(parent, height=self.height, bg=self.colors["bg"],
                                highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(fill="x", padx=px(12), pady=(0, px(8)))

        c = self.colors
        self.bg_item = _rounded_rect(self.canvas, 0, 0, 100, self.height, px(14),
                                     fill=c["card"], outline=c["border"])
        self.title_item = self.canvas.create_text(px(18), px(22), anchor="w", text="",
                                                  font=(FONT, 9), fill=c["subtext"])
        self.code_item = self.canvas.create_text(px(17), px(48), anchor="w", text="------",
                                                 font=(FONT, 23, "bold"), fill=c["accent"])
        self.sub_item = self.canvas.create_text(px(18), px(71), anchor="w", text="",
                                                font=(FONT, 9), fill=c["subtext"])
        ring = max(2, px(3))
        self.track_item = self.canvas.create_oval(0, 0, 0, 0, outline=c["border"], width=ring)
        self.arc_item = self.canvas.create_arc(0, 0, 0, 0, start=90, extent=-359.9,
                                               style="arc", outline=c["accent"], width=ring)
        self.sec_item = self.canvas.create_text(0, 0, text="", font=(FONT, 9, "bold"),
                                                fill=c["subtext"])

        self.canvas.bind("<Configure>", self._relayout)
        self.canvas.bind("<Button-1>", self.copy_code)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)

        self.refresh_labels()

    # ------------------------------------------------------------------ layout
    def _relayout(self, event=None):
        w = event.width if event else self.canvas.winfo_width()
        self.canvas.coords(self.bg_item,
                           *self._rrect_points(1, 1, w - 1, self.height - 1, px(14)))
        cx, cy, r = w - px(38), self.height // 2, px(16)
        self.canvas.coords(self.track_item, cx - r, cy - r, cx + r, cy + r)
        self.canvas.coords(self.arc_item, cx - r, cy - r, cx + r, cy + r)
        self.canvas.coords(self.sec_item, cx, cy)

    @staticmethod
    def _rrect_points(x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    # ------------------------------------------------------------------ visuals
    def refresh_labels(self):
        issuer = self.account.get("issuer", "").strip()
        name = self.account.get("name", "").strip()
        title, sub = (issuer, name) if issuer else (name or "Không tên", "")
        self.canvas.itemconfig(self.title_item, text=title)
        self.canvas.itemconfig(self.sub_item, text=sub)
        self.counter = None  # buộc tính lại mã

    def update_tick(self, now: float):
        period = self.account.get("period", 30) or 30
        counter = int(now // period)
        remaining = period - (now % period)

        if counter != self.counter:
            self.counter = counter
            try:
                self.code = tc.totp(self.account["secret"], at=now,
                                    digits=self.account.get("digits", 6),
                                    period=period,
                                    algorithm=self.account.get("algorithm", "SHA1"))
                self.error = None
            except (tc.InvalidSecret, ValueError, AttributeError) as exc:
                self.code = ""
                self.error = str(exc)
            self.render_code()

        urgent = remaining <= 5
        color = self.colors["warn"] if urgent else self.colors["accent"]
        self.canvas.itemconfig(self.arc_item, outline=color,
                               extent=max(-359.9, min(-0.1, -360.0 * (remaining / period))))
        self.canvas.itemconfig(self.sec_item, text=str(max(1, math.ceil(remaining))),
                               fill=color if urgent else self.colors["subtext"])
        if not self.error:
            self.canvas.itemconfig(self.code_item, fill=color)

    def render_code(self):
        if self.error:
            self.canvas.itemconfig(self.code_item, text="KEY LỖI", fill=self.colors["warn"],
                                   font=(FONT, 14, "bold"))
            return
        self.canvas.itemconfig(self.code_item, font=(FONT, 23, "bold"))
        masked = self.app.settings.get("hide_codes") and not self.hovering
        text = "••• •••" if masked else tc.format_code(self.code)
        self.canvas.itemconfig(self.code_item, text=text)

    # ------------------------------------------------------------------ events
    def _on_enter(self, _event=None):
        self.hovering = True
        self.canvas.itemconfig(self.bg_item, fill=self.colors["card_hover"])
        if self.app.settings.get("hide_codes"):
            self.render_code()

    def _on_leave(self, _event=None):
        self.hovering = False
        self.canvas.itemconfig(self.bg_item, fill=self.colors["card"])
        if self.app.settings.get("hide_codes"):
            self.render_code()

    def copy_code(self, _event=None):
        if self.error or not self.code:
            self.app.toast("Chuỗi key không hợp lệ - hãy sửa lại tài khoản")
            return
        self.app.copy_to_clipboard(self.code)
        self.app.toast(f"Đã sao chép mã của {self.account.get('issuer') or self.account.get('name')}")
        self.canvas.itemconfig(self.bg_item, fill=self.colors["accent"])
        self.canvas.after(140, lambda: self.canvas.itemconfig(
            self.bg_item, fill=self.colors["card_hover"] if self.hovering else self.colors["card"]))

    def _on_menu(self, event):
        self.app.show_card_menu(self.account, event.x_root, event.y_root)

    def destroy(self):
        self.canvas.destroy()


# ============================================================================ app
class AuthenticatorApp(tk.Tk):
    def __init__(self):
        enable_dpi_awareness()
        super().__init__()
        self.withdraw()
        self._setup_scaling()
        self.settings = vault.load_settings()
        self.colors = PALETTES.get(self.settings.get("theme", "dark"), PALETTES["dark"])
        self.password: str | None = None
        self.accounts: list[dict] = []
        self.cards: dict[str, CardView] = {}
        self._tick_job = None
        self._toast_job = None
        self._menu_vars: dict[str, tk.BooleanVar] = {}
        self.ready = False

        self.title(APP_NAME)
        self.geometry(f"{px(400)}x{px(660)}")
        self.minsize(px(340), px(400))
        self.configure(bg=self.colors["bg"])
        self._apply_window_icon()

        if not self._unlock():
            self.destroy()
            return

        self._build_ui()
        self.attributes("-topmost", bool(self.settings.get("always_on_top")))
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.ready = True
        self._tick()

    def _setup_scaling(self):
        """Đồng bộ kích thước chữ (point) và hằng số pixel theo DPI thực tế."""
        global SCALE
        try:
            dpi = float(self.winfo_fpixels("1i"))
        except tk.TclError:
            dpi = 96.0
        dpi = min(max(dpi, 96.0), 240.0)
        SCALE = dpi / 96.0
        self.tk.call("tk", "scaling", dpi / 72.0)

    def _apply_window_icon(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon = os.path.join(base, ICON_FILE)
        if os.path.exists(icon):
            try:
                self.iconbitmap(default=icon)
            except tk.TclError:
                pass

    # ----------------------------------------------------------------- unlocking
    def _unlock(self) -> bool:
        try:
            encrypted = vault.is_encrypted()
        except Exception:
            encrypted = False

        if not encrypted:
            try:
                self.accounts = vault.load()
            except vault.VaultCorrupted as exc:
                messagebox.showerror(APP_NAME, f"Không đọc được dữ liệu:\n{exc}")
                self.accounts = []
            return True

        for _ in range(5):
            pwd = PasswordDialog(self, "Mở khoá kho mã",
                                 "Nhập mật khẩu chính để mở kho tài khoản:").result
            if pwd is None:
                return False
            try:
                self.accounts = vault.load(pwd)
                self.password = pwd
                return True
            except vault.WrongPassword:
                messagebox.showerror(APP_NAME, "Mật khẩu không đúng. Hãy thử lại.")
            except vault.VaultCorrupted as exc:
                messagebox.showerror(APP_NAME, f"File dữ liệu hỏng:\n{exc}")
                return False
        return False

    # ------------------------------------------------------------------ build ui
    def _apply_ttk_style(self):
        """Nhuộm màu combobox + thanh cuộn của ttk theo bảng màu đang dùng."""
        c = self.colors
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar", background=c["btn"], troughcolor=c["bg"],
                        bordercolor=c["bg"], arrowcolor=c["subtext"], relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", c["btn_hover"])])
        style.configure("TCombobox", fieldbackground=c["entry"], background=c["btn"],
                        foreground=c["text"], arrowcolor=c["text"], bordercolor=c["border"],
                        lightcolor=c["border"], darkcolor=c["border"],
                        selectbackground=c["entry"], selectforeground=c["text"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", c["entry"])],
                  background=[("readonly", c["btn"]), ("active", c["btn_hover"])],
                  foreground=[("readonly", c["text"])])
        self.option_add("*TCombobox*Listbox.background", c["card"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", c["header"])

    def _build_ui(self):
        c = self.colors
        self._apply_ttk_style()

        header = tk.Frame(self, bg=c["header"], height=px(56))
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text=APP_NAME, bg=c["header"], fg=c["text"],
                 font=(FONT, 14, "bold")).pack(side="left", padx=px(18))
        self._icon_button(header, "⋮", self._open_main_menu).pack(side="right", padx=(0, px(12)))
        self._icon_button(header, "＋", self.add_account).pack(side="right", padx=px(2))

        tk.Frame(self, bg=c["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=c["bg"])
        body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=c["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll_set)

        self.list_frame = tk.Frame(self.canvas, bg=c["bg"])
        self.list_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self.list_window, width=e.width))
        self.list_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.bind_all("<MouseWheel>", self._on_wheel)

        footer = tk.Frame(self, bg=c["header"])
        footer.pack(fill="x", side="bottom")
        tk.Frame(footer, bg=c["border"], height=1).pack(fill="x")
        self.status = tk.Label(footer, text="", bg=c["header"], fg=c["subtext"], font=(FONT, 8))
        self.status.pack(side="left", padx=px(14), pady=px(6))
        tk.Label(footer, text="Bấm vào thẻ để sao chép mã", bg=c["header"], fg=c["subtext"],
                 font=(FONT, 8)).pack(side="right", padx=px(14))

        self.toast_label = tk.Label(self, text="", bg=c["toast"], fg="#ffffff",
                                    font=(FONT, 9), padx=px(14), pady=px(7))

        self.empty_label = tk.Label(self.list_frame, bg=c["bg"], fg=c["subtext"], justify="center",
                                    font=(FONT, 10),
                                    text="\n\nChưa có tài khoản nào.\n\n"
                                         "Bấm ＋ ở góc trên để thêm chuỗi key 2FA\n"
                                         "hoặc dán liên kết otpauth://")

        menu_style = {"tearoff": 0, "bg": c["card"], "fg": c["text"], "bd": 0,
                      "activebackground": c["accent"], "activeforeground": c["header"]}
        self.main_menu = tk.Menu(self, **menu_style)
        self.card_menu = tk.Menu(self, **menu_style)

        self.bind("<Control-n>", lambda _e: self.add_account())
        self.bind("<Control-v>", self.import_qr_clipboard)
        self.bind("<F5>", lambda _e: self.rebuild_cards())
        self.rebuild_cards()

    def _icon_button(self, parent, text, command):
        c = self.colors
        btn = tk.Label(parent, text=text, bg=c["header"], fg=c["text"], font=(FONT, 15),
                       width=3, cursor="hand2")
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=c["btn_hover"]))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=c["header"]))
        return btn

    def _on_scroll_set(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.pack_forget()
        else:
            self.scrollbar.pack(side="right", fill="y")
        self.scrollbar.set(first, last)

    def _on_wheel(self, event):
        if event.widget.winfo_toplevel() is not self:
            return
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # -------------------------------------------------------------------- cards
    def rebuild_cards(self):
        for child in self.list_frame.winfo_children():
            if child is not self.empty_label:   # dọn cả thẻ lẫn khung đệm
                child.destroy()
        self.cards.clear()
        self.empty_label.pack_forget()

        if not self.accounts:
            self.empty_label.pack(fill="x", pady=px(40))
        else:
            tk.Frame(self.list_frame, bg=self.colors["bg"], height=px(12)).pack(fill="x")
            for account in self.accounts:
                self.cards[account["id"]] = CardView(self.list_frame, self, account)

        self.status.configure(text=f"{len(self.accounts)} tài khoản"
                                   + ("  •  đã khoá bằng mật khẩu" if self.password else ""))
        self.after_idle(lambda: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def _tick(self):
        now = time.time()
        for card in self.cards.values():
            card.update_tick(now)
        self._tick_job = self.after(50, self._tick)

    # ------------------------------------------------------------------ actions
    def add_account(self):
        result = AccountDialog(self, "Thêm tài khoản").result
        if result:
            self.accounts.append(vault.new_account(**result))
            self._persist()
            self.rebuild_cards()
            self.toast("Đã thêm tài khoản")

    def edit_account(self, account: dict):
        result = AccountDialog(self, "Sửa tài khoản", account).result
        if result:
            account.update(result)
            self._persist()
            self.rebuild_cards()
            self.toast("Đã cập nhật")

    def delete_account(self, account: dict):
        label = account.get("issuer") or account.get("name") or "tài khoản này"
        if not messagebox.askyesno(APP_NAME, f"Xoá {label}?\n\n"
                                             "Bạn sẽ không tạo được mã 2FA cho tài khoản này nữa "
                                             "trừ khi còn giữ chuỗi key gốc.", parent=self):
            return
        self.accounts = [a for a in self.accounts if a["id"] != account["id"]]
        self._persist()
        self.rebuild_cards()
        self.toast("Đã xoá tài khoản")

    def move_account(self, account: dict, delta: int):
        index = next((i for i, a in enumerate(self.accounts) if a["id"] == account["id"]), None)
        target = index + delta if index is not None else None
        if target is None or not 0 <= target < len(self.accounts):
            return
        self.accounts[index], self.accounts[target] = self.accounts[target], self.accounts[index]
        self._persist()
        self.rebuild_cards()

    def show_card_menu(self, account: dict, x: int, y: int):
        menu = self.card_menu
        menu.delete(0, "end")
        card = self.cards.get(account["id"])
        menu.add_command(label="Sao chép mã",
                         command=lambda: card and card.copy_code())
        menu.add_command(label="Sao chép liên kết otpauth://",
                         command=lambda: self._copy_uri(account))
        menu.add_separator()
        menu.add_command(label="Sửa…", command=lambda: self.edit_account(account))
        menu.add_command(label="Di chuyển lên", command=lambda: self.move_account(account, -1))
        menu.add_command(label="Di chuyển xuống", command=lambda: self.move_account(account, 1))
        menu.add_separator()
        menu.add_command(label="Xoá", command=lambda: self.delete_account(account))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _copy_uri(self, account: dict):
        self.copy_to_clipboard(tc.build_otpauth_uri(account))
        self.toast("Đã sao chép liên kết khôi phục (giữ bí mật!)")

    def _open_main_menu(self):
        menu = self.main_menu
        menu.delete(0, "end")
        menu.add_command(label="Thêm tài khoản…  (Ctrl+N)", command=self.add_account)
        menu.add_separator()
        menu.add_command(label="Đổi mật khẩu chính…" if self.password else "Đặt mật khẩu chính…",
                         command=self.change_password)
        if self.password:
            menu.add_command(label="Gỡ mật khẩu chính", command=self.remove_password)
        menu.add_separator()
        menu.add_command(label="Chủ đề: " + ("Tối → Sáng" if self.settings["theme"] == "dark"
                                             else "Sáng → Tối"), command=self.toggle_theme)
        self._menu_vars["hide"] = tk.BooleanVar(value=bool(self.settings.get("hide_codes")))
        self._menu_vars["top"] = tk.BooleanVar(value=bool(self.settings.get("always_on_top")))
        menu.add_checkbutton(label="Ẩn mã (hiện khi rê chuột)", onvalue=True, offvalue=False,
                             variable=self._menu_vars["hide"], command=self.toggle_hide)
        menu.add_checkbutton(label="Luôn hiện trên cùng", onvalue=True, offvalue=False,
                             variable=self._menu_vars["top"], command=self.toggle_topmost)
        menu.add_separator()
        menu.add_command(label="Nhập từ ảnh QR…", command=self.import_qr_file)
        menu.add_command(label="Dán ảnh QR từ clipboard  (Ctrl+V)",
                         command=self.import_qr_clipboard)
        menu.add_separator()
        menu.add_command(label="Xuất dự phòng…", command=self.export_accounts)
        menu.add_command(label="Nhập từ file sao lưu…", command=self.import_accounts)
        menu.add_separator()
        menu.add_command(label="Vị trí file dữ liệu…", command=self.show_about)
        try:
            menu.tk_popup(self.winfo_rootx() + self.winfo_width() - 40, self.winfo_rooty() + 48)
        finally:
            menu.grab_release()

    # ----------------------------------------------------------------- settings
    def toggle_theme(self):
        self.settings["theme"] = "light" if self.settings["theme"] == "dark" else "dark"
        vault.save_settings(self.settings)
        self._rebuild_everything()

    def toggle_hide(self):
        self.settings["hide_codes"] = not self.settings.get("hide_codes")
        vault.save_settings(self.settings)
        for card in self.cards.values():
            card.render_code()

    def toggle_topmost(self):
        self.settings["always_on_top"] = not self.settings.get("always_on_top")
        vault.save_settings(self.settings)
        self.attributes("-topmost", bool(self.settings["always_on_top"]))

    def _rebuild_everything(self):
        for job in (self._tick_job, self._toast_job):
            if job:
                self.after_cancel(job)
        self._tick_job = self._toast_job = None
        self.colors = PALETTES[self.settings["theme"]]
        self.configure(bg=self.colors["bg"])
        for child in self.winfo_children():
            if isinstance(child, (tk.Frame, tk.Label, tk.Menu)):
                child.destroy()
        self.cards.clear()
        self._build_ui()
        self._tick()

    def change_password(self):
        dialog = PasswordDialog(self, "Mật khẩu chính",
                                "Đặt mật khẩu để mã hoá file dữ liệu.\n"
                                "Để trống và bấm Lưu nếu muốn bỏ mật khẩu.",
                                confirm=True)
        if dialog.result is None:
            return
        self.password = dialog.result or None
        self._persist()
        self.toast("Đã cập nhật mật khẩu chính" if self.password else "Đã gỡ mật khẩu")
        self.rebuild_cards()

    def remove_password(self):
        if messagebox.askyesno(APP_NAME, "Gỡ mật khẩu? File dữ liệu sẽ được lưu ở dạng "
                                         "không mã hoá.", parent=self):
            self.password = None
            self._persist()
            self.rebuild_cards()
            self.toast("Đã gỡ mật khẩu chính")

    # ------------------------------------------------------------ import/export
    def export_accounts(self):
        if not self.accounts:
            self.toast("Chưa có gì để xuất")
            return
        if not messagebox.askyesno(APP_NAME, "File xuất chứa TOÀN BỘ chuỗi key ở dạng văn bản "
                                             "thường. Bất kỳ ai có file này đều tạo được mã 2FA "
                                             "của bạn.\n\nTiếp tục?", parent=self):
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt",
                                            initialfile="2fa-backup.txt",
                                            filetypes=[("Văn bản", "*.txt"), ("Tất cả", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(tc.build_otpauth_uri(a) for a in self.accounts) + "\n")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Không ghi được file:\n{exc}", parent=self)
            return
        self.toast(f"Đã xuất {len(self.accounts)} tài khoản")

    def import_accounts(self):
        path = filedialog.askopenfilename(parent=self, title="Chọn file sao lưu",
                                          filetypes=[("Văn bản", "*.txt"), ("Tất cả", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = [line.strip() for line in fh if line.strip()]
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Không đọc được file:\n{exc}", parent=self)
            return
        self._ingest_texts(lines)

    def import_qr_file(self):
        if not self._require_qr_support():
            return
        paths = filedialog.askopenfilenames(
            parent=self, title="Chọn ảnh chứa mã QR",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                       ("Tất cả", "*.*")])
        if not paths:
            return
        texts, errors = [], []
        for path in paths:
            try:
                texts.extend(qr_reader.read_image_file(path))
            except (qr_reader.QRNotFound, ValueError) as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
        if not texts:
            messagebox.showerror(APP_NAME, "Không đọc được mã QR nào.\n\n" + "\n".join(errors),
                                 parent=self)
            return
        self._ingest_texts(texts)

    def import_qr_clipboard(self, _event=None):
        if not self._require_qr_support():
            return
        try:
            texts = qr_reader.read_clipboard()
        except (qr_reader.QRNotFound, ValueError) as exc:
            messagebox.showwarning(APP_NAME, str(exc), parent=self)
            return
        self._ingest_texts(texts)

    def _require_qr_support(self) -> bool:
        if qr_reader.available():
            return True
        messagebox.showerror(
            APP_NAME,
            "Bản dựng này chưa kèm thư viện đọc mã QR.\n\n"
            f"Cài bằng lệnh:\n{qr_reader.INSTALL_HINT}\n\n"
            "Hoặc dùng menu ⋮ → Nhập từ file… với file sao lưu dạng văn bản.",
            parent=self)
        return False

    # -------------------------------------------------- xử lý chung khi nhập vào
    def _ingest_texts(self, texts: list[str]):
        """Nhận danh sách chuỗi (otpauth://, otpauth-migration://) và thêm vào app."""
        candidates: list[dict] = []
        problems: list[str] = []
        batches: list[tuple[int, int]] = []

        for text in texts:
            raw = (text or "").strip()
            if not raw:
                continue
            if migration.is_migration_uri(raw):
                try:
                    payload = migration.decode_migration_uri(raw)
                except migration.MigrationError as exc:
                    problems.append(f"Gói chuyển tài khoản: {exc}")
                    continue
                batches.append((payload["batch_index"] + 1, payload["batch_size"]))
                for item in payload["accounts"]:
                    label = f"{item['issuer']}: {item['name']}".strip(": ") or "(không tên)"
                    if item["type"] != "totp":
                        problems.append(f"{label}: loại HOTP, app này chỉ tạo mã TOTP")
                    elif item["algorithm"] not in tc.ALGORITHMS:
                        problems.append(f"{label}: thuật toán {item['algorithm']} không hỗ trợ")
                    else:
                        candidates.append(item)
            elif raw.lower().startswith("otpauth://"):
                try:
                    candidates.append(tc.parse_otpauth_uri(raw))
                except (ValueError, tc.InvalidSecret) as exc:
                    problems.append(f"Liên kết otpauth: {exc}")

        existing = {a["secret"] for a in self.accounts}
        fresh, duplicates = [], 0
        for item in candidates:
            label = f"{item.get('issuer', '')}: {item.get('name', '')}".strip(": ") or "(không tên)"
            try:
                secret = tc.validate_secret(item["secret"])
            except tc.InvalidSecret as exc:
                problems.append(f"{label}: {exc}")
                continue
            if secret in existing:
                duplicates += 1
                continue
            existing.add(secret)
            fresh.append(vault.new_account(
                issuer=item.get("issuer", ""), name=item.get("name", ""), secret=secret,
                digits=item.get("digits", 6), period=item.get("period", 30),
                algorithm=item.get("algorithm", "SHA1")))

        self._finish_ingest(fresh, duplicates, problems, batches)

    def _finish_ingest(self, fresh, duplicates, problems, batches):
        if not fresh:
            lines = ["Không có tài khoản mới nào được thêm."]
            if duplicates:
                lines.append(f"\n• {duplicates} tài khoản đã có sẵn trong app.")
            if problems:
                lines.append("\n• " + "\n• ".join(problems[:10]))
            messagebox.showinfo(APP_NAME, "\n".join(lines), parent=self)
            return

        preview = "\n".join(
            f"   • {(a['issuer'] + ' — ' if a['issuer'] else '') + (a['name'] or '(không tên)')}"
            for a in fresh[:15])
        if len(fresh) > 15:
            preview += f"\n   • … và {len(fresh) - 15} tài khoản nữa"

        notes = []
        if batches:
            part, total = batches[0]
            if total > 1:
                notes.append(f"\nĐây là phần {part}/{total} của bản xuất. Hãy quét nốt "
                             f"{total - 1} ảnh QR còn lại để có đủ tài khoản.")
        if duplicates:
            notes.append(f"\nBỏ qua {duplicates} tài khoản đã có sẵn.")
        if problems:
            notes.append("\nBỏ qua vì không hỗ trợ:\n   • " + "\n   • ".join(problems[:6]))

        if not messagebox.askyesno(
                APP_NAME,
                f"Tìm thấy {len(fresh)} tài khoản mới:\n\n{preview}\n" + "".join(notes)
                + "\n\nThêm vào app?", parent=self):
            return

        self.accounts.extend(fresh)
        self._persist()
        self.rebuild_cards()
        self.toast(f"Đã nhập {len(fresh)} tài khoản")

    def show_about(self):
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} - trình tạo mã 2FA (TOTP, RFC 6238)\n\n"
            f"File dữ liệu:\n{vault.vault_path()}\n\n"
            f"Cài đặt:\n{vault.settings_path()}\n\n"
            "Mẹo: đặt một file vault.json rỗng cạnh file .exe để chạy ở chế độ portable "
            "(dữ liệu nằm cùng thư mục exe).",
            parent=self)

    # ------------------------------------------------------------------- helpers
    def _persist(self):
        try:
            vault.save(self.accounts, self.password)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Không lưu được dữ liệu:\n{exc}", parent=self)

    def copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def toast(self, message: str):
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self.toast_label.configure(text=message)
        self.toast_label.place(relx=0.5, rely=1.0, anchor="s", y=-px(46))
        self.toast_label.lift()
        self._toast_job = self.after(1900, self.toast_label.place_forget)

    def _on_close(self):
        for job in (self._tick_job, self._toast_job):
            if job:
                self.after_cancel(job)
        self._tick_job = self._toast_job = None
        self.destroy()


# ========================================================================= dialogs
class BaseDialog(tk.Toplevel):
    def __init__(self, parent: AuthenticatorApp, title: str):
        super().__init__(parent)
        self.app = parent
        self.colors = parent.colors
        self.result = None
        self.title(title)
        self.configure(bg=self.colors["bg"], padx=px(22), pady=px(18))
        self.resizable(False, False)
        self.transient(parent)
        self.bind("<Escape>", lambda _e: self._cancel())

    def _finish_setup(self, focus_widget: tk.Widget | None = None):
        self.update_idletasks()
        if self.app.winfo_viewable():
            px, py = self.app.winfo_rootx(), self.app.winfo_rooty()
            pw, ph = self.app.winfo_width(), self.app.winfo_height()
            x = px + (pw - self.winfo_width()) // 2
            y = py + max(40, (ph - self.winfo_height()) // 3)
        else:  # cửa sổ chính còn ẩn (lúc mở khoá) -> canh giữa màn hình
            x = (self.winfo_screenwidth() - self.winfo_width()) // 2
            y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        if focus_widget:
            focus_widget.focus_set()
        self.wait_window(self)

    def _cancel(self):
        self.result = None
        self.destroy()

    def _label(self, parent, text, **kw):
        opts = {"bg": self.colors["bg"], "fg": self.colors["subtext"],
                "font": (FONT, 9), "anchor": "w"}
        opts.update(kw)
        return tk.Label(parent, text=text, **opts)

    def _entry(self, parent, show=None, width=34):
        c = self.colors
        return tk.Entry(parent, bg=c["entry"], fg=c["text"], insertbackground=c["text"],
                        relief="flat", font=(FONT, 11), width=width, show=show,
                        highlightthickness=1, highlightbackground=c["border"],
                        highlightcolor=c["accent"])

    def _button(self, parent, text, command, primary=False):
        c = self.colors
        bg = c["accent"] if primary else c["btn"]
        fg = "#12161c" if primary else c["text"]
        btn = tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT, 10, "bold" if primary else "normal"),
                       padx=px(18), pady=px(8), cursor="hand2")
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=c["btn_hover"] if not primary else c["accent"]))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
        return btn


class PasswordDialog(BaseDialog):
    def __init__(self, parent, title, message, confirm=False):
        super().__init__(parent, title)
        self.confirm = confirm

        self._label(self, message, fg=self.colors["text"], font=(FONT, 10),
                    justify="left", wraplength=px(330)).pack(fill="x", pady=(0, 14))

        self.entry = self._entry(self, show="•")
        self.entry.pack(fill="x", ipady=6)

        self.entry2 = None
        if confirm:
            self._label(self, "Nhập lại mật khẩu").pack(fill="x", pady=(12, 4))
            self.entry2 = self._entry(self, show="•")
            self.entry2.pack(fill="x", ipady=6)

        self.error = self._label(self, "", fg=self.colors["warn"], wraplength=px(330),
                                 justify="left")
        self.error.pack(fill="x", pady=(8, 0))

        row = tk.Frame(self, bg=self.colors["bg"])
        row.pack(fill="x", pady=(16, 0))
        self._button(row, "Huỷ", self._cancel).pack(side="right", padx=(8, 0))
        self._button(row, "Lưu" if confirm else "Mở khoá", self._submit, primary=True).pack(side="right")

        self.bind("<Return>", lambda _e: self._submit())
        self._finish_setup(self.entry)

    def _submit(self):
        value = self.entry.get()
        if self.confirm:
            if value != self.entry2.get():
                self.error.configure(text="Hai lần nhập chưa khớp.")
                return
            if value and len(value) < 4:
                self.error.configure(text="Mật khẩu nên có ít nhất 4 ký tự.")
                return
        elif not value:
            self.error.configure(text="Hãy nhập mật khẩu.")
            return
        self.result = value
        self.destroy()


class AccountDialog(BaseDialog):
    def __init__(self, parent, title, account: dict | None = None):
        super().__init__(parent, title)
        self._preview_job = None
        c = self.colors

        self._label(self, "Nhà cung cấp  (VD: Google, Facebook, Binance)").pack(fill="x")
        self.issuer = self._entry(self)
        self.issuer.pack(fill="x", ipady=5, pady=(3, 12))

        self._label(self, "Tên tài khoản  (VD: email của bạn)").pack(fill="x")
        self.name = self._entry(self)
        self.name.pack(fill="x", ipady=5, pady=(3, 12))

        self._label(self, "Chuỗi key bí mật  (Base32) — hoặc dán cả liên kết otpauth://").pack(fill="x")
        self.secret = self._entry(self)
        self.secret.pack(fill="x", ipady=5, pady=(3, 12))

        adv = tk.Frame(self, bg=c["bg"])
        adv.pack(fill="x", pady=(0, 6))
        self.digits = tk.StringVar(value="6")
        self.period = tk.StringVar(value="30")
        self.algorithm = tk.StringVar(value="SHA1")
        self._combo(adv, "Số chữ số", self.digits, ["6", "7", "8"]).pack(side="left")
        self._combo(adv, "Chu kỳ (giây)", self.period, ["30", "60"]).pack(side="left", padx=12)
        self._combo(adv, "Thuật toán", self.algorithm, list(tc.ALGORITHMS)).pack(side="left")

        preview_box = tk.Frame(self, bg=c["card"], highlightthickness=1,
                               highlightbackground=c["border"])
        preview_box.pack(fill="x", pady=(10, 0))
        self._label(preview_box, "Xem trước mã", bg=c["card"]).pack(anchor="w", padx=12, pady=(8, 0))
        self.preview = tk.Label(preview_box, text="— — —", bg=c["card"], fg=c["accent"],
                                font=(FONT, 20, "bold"))
        self.preview.pack(anchor="w", padx=12, pady=(0, 10))

        self.error = self._label(self, "", fg=c["warn"], wraplength=px(340), justify="left")
        self.error.pack(fill="x", pady=(8, 0))

        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(14, 0))
        self._button(row, "Huỷ", self._cancel).pack(side="right", padx=(8, 0))
        self._button(row, "Lưu", self._submit, primary=True).pack(side="right")

        if account:
            self.issuer.insert(0, account.get("issuer", ""))
            self.name.insert(0, account.get("name", ""))
            self.secret.insert(0, account.get("secret", ""))
            self.digits.set(str(account.get("digits", 6)))
            self.period.set(str(account.get("period", 30)))
            self.algorithm.set(account.get("algorithm", "SHA1"))

        self.secret.bind("<KeyRelease>", self._maybe_expand_uri)
        self.bind("<Return>", lambda _e: self._submit())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._update_preview()
        self._finish_setup(self.issuer)

    def _combo(self, parent, label, variable, values):
        box = tk.Frame(parent, bg=self.colors["bg"])
        self._label(box, label).pack(anchor="w")
        combo = ttk.Combobox(box, textvariable=variable, values=values, width=8,
                             state="readonly", font=(FONT, 10))
        combo.pack(anchor="w", pady=(3, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())
        return box

    def _maybe_expand_uri(self, _event=None):
        raw = self.secret.get().strip()
        if migration.is_migration_uri(raw):
            self.error.configure(text=MIGRATION_HINT)
            self._update_preview()
            return
        if raw.lower().startswith("otpauth://"):
            try:
                parsed = tc.parse_otpauth_uri(raw)
            except (ValueError, tc.InvalidSecret):
                return
            self.secret.delete(0, "end")
            self.secret.insert(0, parsed["secret"])
            if parsed["issuer"]:
                self.issuer.delete(0, "end")
                self.issuer.insert(0, parsed["issuer"])
            if parsed["name"]:
                self.name.delete(0, "end")
                self.name.insert(0, parsed["name"])
            self.digits.set(str(parsed["digits"]))
            self.period.set(str(parsed["period"]))
            self.algorithm.set(parsed["algorithm"])
            self.error.configure(text="")
        self._update_preview()

    def _update_preview(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
        try:
            code = tc.totp(self.secret.get(), digits=int(self.digits.get()),
                           period=int(self.period.get()), algorithm=self.algorithm.get())
            self.preview.configure(text=tc.format_code(code), fg=self.colors["accent"])
        except (tc.InvalidSecret, ValueError):
            self.preview.configure(text="— — —", fg=self.colors["subtext"])
        self._preview_job = self.after(500, self._update_preview)

    def _submit(self):
        self._maybe_expand_uri()
        if migration.is_migration_uri(self.secret.get()):
            self.error.configure(text=MIGRATION_HINT)
            return
        try:
            secret = tc.validate_secret(self.secret.get())
        except tc.InvalidSecret as exc:
            self.error.configure(text=f"Chuỗi key không hợp lệ: {exc}")
            return
        if not self.issuer.get().strip() and not self.name.get().strip():
            self.error.configure(text="Hãy nhập ít nhất nhà cung cấp hoặc tên tài khoản.")
            return
        if self._preview_job:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self.result = {
            "issuer": self.issuer.get().strip(),
            "name": self.name.get().strip(),
            "secret": secret,
            "digits": int(self.digits.get()),
            "period": int(self.period.get()),
            "algorithm": self.algorithm.get(),
        }
        self.destroy()

    def _cancel(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        super()._cancel()
