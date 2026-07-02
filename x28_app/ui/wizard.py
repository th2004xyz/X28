"""首次启动配置向导。

引导用户填写 AI API Key 与（可选）X Bearer Token，
完成后写入系统 keyring（不可用时回退到 .env）。

调用方式:
  from x28_app.ui.wizard import ConfigWizard
  ok = ConfigWizard(parent).result  # True 表示用户已确认完成配置
"""

import os
import logging
from tkinter import BooleanVar, StringVar

import customtkinter as ctk

from ..config import COLORS
from ..utils.secrets import (
    get_secret, set_secret, has_any_credentials, is_keyring_available,
)

log = logging.getLogger("x28.wizard")


class ConfigWizard(ctk.CTkToplevel):
    """配置向导对话框（单页表单）。

    Attributes:
        result: True 表示用户已完成配置并保存；False/None 表示取消。
    """

    def __init__(self, parent=None, force_open: bool = False):
        super().__init__(parent)
        self.result = False
        self._force_open = force_open

        self.title("X28 配置向导")
        self.geometry("520x620")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        self.transient(parent)

        # 模态：抢焦点，关闭前阻塞父窗口交互
        self.grab_set()

        # 拉取当前状态
        self._status = has_any_credentials()
        self._provider_var = StringVar(value=self._status["provider"])
        self._show_key_var = BooleanVar(value=False)
        self._show_token_var = BooleanVar(value=False)

        self._build_ui()
        self._refresh_provider_fields()

        # 居中显示
        self.after(50, self._center)

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)

        # ---- 标题区 ----
        title_f = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        title_f.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        title_f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_f,
            text="✦  X28 配置向导",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, padx=20, pady=(18, 4))

        storage_hint = (
            "✓ 凭证将存入系统 keyring（推荐）"
            if is_keyring_available()
            else "⚠ keyring 不可用，凭证将存入 .env"
        )
        storage_color = COLORS["success"] if is_keyring_available() else COLORS["warning"]
        ctk.CTkLabel(
            title_f,
            text=storage_hint,
            font=ctk.CTkFont(size=11),
            text_color=storage_color,
        ).grid(row=1, column=0, padx=20, pady=(0, 6))

        ctk.CTkLabel(
            title_f,
            text="首次使用请填写以下信息，全部保存在本机，不会上传。",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            wraplength=460,
            justify="center",
        ).grid(row=2, column=0, padx=20, pady=(0, 16))

        # ---- 表单区 ----
        form = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        form.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        form.grid_columnconfigure(0, weight=1)

        # AI 提供商
        ctk.CTkLabel(
            form, text="① AI 提供商",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")

        self._provider_seg = ctk.CTkSegmentedButton(
            form,
            values=["gemini", "openai", "anthropic"],
            command=self._on_provider_change,
            fg_color=COLORS["input"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["input"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self._provider_seg.set(self._status["provider"])
        self._provider_seg.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")

        # API Key
        self._key_label = ctk.CTkLabel(
            form, text="② API Key",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w")
        self._key_label.grid(row=2, column=0, padx=16, pady=(4, 4), sticky="w")

        self._key_hint = ctk.CTkLabel(
            form, text="",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            anchor="w")
        self._key_hint.grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")

        key_f = ctk.CTkFrame(form, fg_color="transparent")
        key_f.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="ew")
        key_f.grid_columnconfigure(0, weight=1)
        key_f.grid_columnconfigure(1, weight=0)

        self._key_entry = ctk.CTkEntry(
            key_f, show="*",
            fg_color=COLORS["input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12), height=36)
        self._key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._key_toggle = ctk.CTkButton(
            key_f, text="👁", width=40, height=36,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(size=14),
            corner_radius=6,
            command=lambda: self._toggle_visibility(
                self._key_entry, self._show_key_var, self._key_toggle))
        self._key_toggle.grid(row=0, column=1)

        # X Bearer Token (可选)
        ctk.CTkLabel(
            form, text="③ X API Bearer Token（可选，留空使用 Nitter）",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=5, column=0, padx=16, pady=(4, 4), sticky="w")

        ctk.CTkLabel(
            form,
            text="配置后走官方 X API v2 抓取，更稳定；不填则用 Nitter 多网关轮询。",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            anchor="w",
            wraplength=440,
            justify="left",
        ).grid(row=6, column=0, padx=16, pady=(0, 4), sticky="w")

        token_f = ctk.CTkFrame(form, fg_color="transparent")
        token_f.grid(row=7, column=0, padx=16, pady=(0, 14), sticky="ew")
        token_f.grid_columnconfigure(0, weight=1)
        token_f.grid_columnconfigure(1, weight=0)

        self._token_entry = ctk.CTkEntry(
            token_f, show="*",
            fg_color=COLORS["input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12), height=36,
            placeholder_text="可选，留空使用 Nitter")
        self._token_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._token_toggle = ctk.CTkButton(
            token_f, text="👁", width=40, height=36,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(size=14),
            corner_radius=6,
            command=lambda: self._toggle_visibility(
                self._token_entry, self._show_token_var, self._token_toggle))
        self._token_toggle.grid(row=0, column=1)

        # ---- 操作按钮 ----
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="ew")
        btn_f.grid_columnconfigure(0, weight=1)
        btn_f.grid_columnconfigure(1, weight=1)

        self._cancel_btn = ctk.CTkButton(
            btn_f, text="取消",
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42, corner_radius=8,
            command=self._on_cancel)
        self._cancel_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._save_btn = ctk.CTkButton(
            btn_f, text="💾 保存并启动",
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42, corner_radius=8,
            command=self._on_save)
        self._save_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # ---- 预填当前已有值（便于编辑）----
        self._prefill_existing()

    def _prefill_existing(self):
        """预填已有凭证，便于用户在原基础上修改。"""
        provider = self._provider_var.get()
        if provider == "openai":
            key_name = "OPENAI_API_KEY"
        elif provider == "anthropic":
            key_name = "ANTHROPIC_API_KEY"
        else:
            key_name = "GEMINI_API_KEY"

        existing = get_secret(key_name, "")
        if existing:
            self._key_entry.insert(0, existing)
        existing_token = get_secret("X_BEARER_TOKEN", "")
        if existing_token:
            self._token_entry.insert(0, existing_token)

    def _refresh_provider_fields(self):
        """根据所选 provider 刷新 Key 标签与提示。"""
        provider = self._provider_var.get()
        if provider == "openai":
            key_name = "OPENAI_API_KEY"
            hint = "支持中转，可在 .env 设 OPENAI_BASE_URL"
        elif provider == "anthropic":
            key_name = "ANTHROPIC_API_KEY"
            hint = "Claude API Key，以 sk-ant- 开头"
        else:
            key_name = "GEMINI_API_KEY"
            hint = "Google AI Studio 免费申请: aistudio.google.com/app/apikey"

        self._key_label.configure(text=f"② {provider.upper()} API Key")
        self._key_hint.configure(text=hint)

        # 重新预填该 provider 已有的 Key
        self._key_entry.delete(0, "end")
        existing = get_secret(key_name, "")
        if existing:
            self._key_entry.insert(0, existing)

    def _on_provider_change(self, val):
        self._provider_var.set(val)
        self._refresh_provider_fields()

    def _toggle_visibility(self, entry, var, btn):
        new = not var.get()
        var.set(new)
        entry.configure(show="" if new else "*")
        btn.configure(text="🙈" if new else "👁")

    # ------------------------------------------------------------------ 操作
    def _on_cancel(self):
        self.result = False
        self.grab_release()
        self.destroy()

    def _on_save(self):
        provider = self._provider_var.get()
        key_val = self._key_entry.get().strip()
        token_val = self._token_entry.get().strip()

        if not key_val:
            from tkinter import messagebox
            messagebox.showwarning("提示", f"请填写 {provider.upper()} API Key！",
                                   parent=self)
            return

        # 同步 LLM_PROVIDER 到 .env (非敏感配置)
        from ..utils.secrets import _write_env, _env_path
        _write_env("LLM_PROVIDER", provider)

        # 写入 Key（keyring 优先，fallback .env）
        if provider == "openai":
            set_secret("OPENAI_API_KEY", key_val)
        elif provider == "anthropic":
            set_secret("ANTHROPIC_API_KEY", key_val)
        else:
            set_secret("GEMINI_API_KEY", key_val)

        if token_val:
            set_secret("X_BEARER_TOKEN", token_val)

        log.info("配置向导完成: provider=%s", provider)
        self.result = True
        self.grab_release()
        self.destroy()


def should_show_wizard() -> bool:
    """检查是否应该弹出配置向导（首次启动或 Key 缺失）。"""
    status = has_any_credentials()
    return not status["ai_key"]
