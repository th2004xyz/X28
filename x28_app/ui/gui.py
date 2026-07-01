"""主界面 (AppGUI) — 曜石黑 Obsidian 主题。

迁移自原 main.py 的 AppGUI，行为与 UI 保持不变，集成以下改进:
  - 使用 core 层模块 (DataManager / TwitterScraper / AIGenerator)
  - 使用 Tweet dataclass
  - safe_format 替换 str.format，修复用户推文含 {xxx} 时的渲染崩溃
  - CTkImage 头像缓存（同字母头像复用）
  - 手动/自动模式切换时清理残留卡片高亮
  - 刷新按钮 force_refresh=True 绕过抓取缓存
  - 删除监控项后更健壮的 active_item 校验
"""

import os
import threading
import logging
from datetime import datetime
from tkinter import messagebox, simpledialog

import customtkinter as ctk
import pyperclip

from ..config import COLORS
from ..core import DataManager, TwitterScraper, AIGenerator, Tweet
from ..utils.helpers import generate_letter_avatar, safe_format

log = logging.getLogger("x28.gui")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AppGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        # ---- 初始化各层 ----
        self.data_manager = DataManager()

        provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        if provider == "openai":
            ai_key = os.getenv("OPENAI_API_KEY", "")
            ai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif provider == "anthropic":
            ai_key = os.getenv("ANTHROPIC_API_KEY", "")
            ai_model = os.getenv("ANTHROPIC_MODEL", "claude-5-fable")
        else:
            provider = "gemini"
            ai_key = os.getenv("GEMINI_API_KEY", "")
            ai_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

        self.ai_generator = AIGenerator(
            provider=provider, api_key=ai_key, model=ai_model,
            base_url=os.getenv("OPENAI_BASE_URL", ""))
        self.scraper = TwitterScraper(bearer_token=os.getenv("X_BEARER_TOKEN", ""))

        # ---- 运行时状态 ----
        self.monitor_mode = "账号"       # "账号" | "关键词"
        self.selected_tweet: Tweet | None = None
        self.selected_card = None
        self._ctk_avatar_cache: dict = {}  # 字母 -> CTkImage
        self.language_mode = "英文"
        self.active_item = None           # 当前选中的账号或关键词
        self.ai_model_name = ai_model
        self.ai_provider = provider

        self._setup_window()
        self._build_ui()

        # 启动后自动加载第一个账号
        first = (self.data_manager.accounts or self.data_manager.keywords)
        if first:
            self.active_item = first[0]
            self._refresh_side_list()
            self._load_tweets_async(first[0])

    # ==========================================================================
    # 窗口与顶层容器
    # ==========================================================================
    def _setup_window(self):
        self.title("X28 · X平台内容运营辅助工具")
        self.geometry("1260x800")
        self.minsize(1080, 680)
        self.configure(fg_color=COLORS["bg"])
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

    # ==========================================================================
    # 构建全部 UI 组件
    # ==========================================================================
    def _build_ui(self):
        self._build_header()
        self._build_main_area()
        self._build_statusbar()

    # ----- Header -----
    def _build_header(self):
        hf = ctk.CTkFrame(self, fg_color=COLORS["panel"], height=56, corner_radius=0)
        hf.grid(row=0, column=0, sticky="nsew")
        hf.grid_propagate(False)
        hf.grid_columnconfigure(0, weight=1)
        hf.grid_columnconfigure(1, weight=0)
        hf.grid_columnconfigure(2, weight=0)
        hf.grid_rowconfigure(0, weight=1)

        logo = ctk.CTkLabel(
            hf, text="✦  X28  |  X平台内容运营助手",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=COLORS["text_primary"])
        logo.grid(row=0, column=0, padx=24, sticky="w")

        self.lang_seg = ctk.CTkSegmentedButton(
            hf, values=["英文", "中文"],
            command=self._on_lang_change,
            fg_color=COLORS["input"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["input"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            width=130, height=32)
        self.lang_seg.set("英文")
        self.lang_seg.grid(row=0, column=1, padx=10)

        self.refresh_btn = ctk.CTkButton(
            hf, text="⟳  刷新", width=90, height=32,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=6,
            command=self._refresh_current)
        self.refresh_btn.grid(row=0, column=2, padx=20)

    # ----- 三栏主区域 -----
    def _build_main_area(self):
        self.main = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self.main.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_columnconfigure(0, weight=0, minsize=230)
        self.main.grid_columnconfigure(1, weight=3, minsize=380)
        self.main.grid_columnconfigure(2, weight=4, minsize=440)

        self._build_sidebar()
        self._build_tweet_panel()
        self._build_ai_panel()

    # ---------- 左栏：账号/关键词监控管理 ----------
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self.main, fg_color=COLORS["panel"], corner_radius=10)
        sb.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        sb.grid_rowconfigure(0, weight=0)
        sb.grid_rowconfigure(1, weight=0)
        sb.grid_rowconfigure(2, weight=1)
        sb.grid_rowconfigure(3, weight=0)
        sb.grid_columnconfigure(0, weight=1)

        self.mode_seg = ctk.CTkSegmentedButton(
            sb, values=["账号", "关键词"],
            command=self._on_mode_change,
            fg_color=COLORS["input"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["input"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"))
        self.mode_seg.set("账号")
        self.mode_seg.grid(row=0, column=0, padx=10, pady=(12, 0), sticky="ew")

        self.side_title = ctk.CTkLabel(
            sb, text="监控账号",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"])
        self.side_title.grid(row=1, column=0, padx=14, pady=(8, 4), sticky="w")

        self.side_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["card_hover"])
        self.side_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        self.side_scroll.grid_columnconfigure(0, weight=1)

        add_f = ctk.CTkFrame(sb, fg_color="transparent")
        add_f.grid(row=3, column=0, sticky="ew", padx=8, pady=10)
        add_f.grid_columnconfigure(0, weight=1)
        add_f.grid_columnconfigure(1, weight=0)

        self.add_entry = ctk.CTkEntry(
            add_f, placeholder_text="添加账号/@用户名 或关键词",
            fg_color=COLORS["input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=11))
        self.add_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.add_entry.bind("<Return>", lambda e: self._add_item())

        self.add_btn = ctk.CTkButton(
            add_f, text="+", width=32, height=32,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=6,
            command=self._add_item)
        self.add_btn.grid(row=0, column=1)

        self._refresh_side_list()

    def _current_items(self):
        """返回当前模式下的监控项列表。"""
        return (self.data_manager.accounts
                if self.monitor_mode == "账号"
                else self.data_manager.keywords)

    def _refresh_side_list(self):
        for w in self.side_scroll.winfo_children():
            w.destroy()

        items = self._current_items()
        # active_item 健壮性：若已不在列表中则修正为 None 或首项
        if self.active_item and self.active_item not in items:
            self.active_item = items[0] if items else None

        label_text = "监控账号" if self.monitor_mode == "账号" else "监控关键词"
        self.side_title.configure(text=label_text)

        for i, item in enumerate(items):
            row_f = ctk.CTkFrame(self.side_scroll, fg_color="transparent")
            row_f.grid(row=i, column=0, sticky="ew", pady=2, padx=2)
            row_f.grid_columnconfigure(0, weight=1)
            row_f.grid_columnconfigure(1, weight=0)

            is_active = (item == self.active_item)
            btn_fg = COLORS["accent"] if is_active else COLORS["input"]
            btn_border = COLORS["accent"] if is_active else COLORS["border"]

            item_btn = ctk.CTkButton(
                row_f, text=item, anchor="w",
                fg_color=btn_fg,
                hover_color=COLORS["accent"] if not is_active else COLORS["accent_hover"],
                border_color=btn_border, border_width=1,
                text_color=COLORS["text_primary"],
                font=ctk.CTkFont(size=12, weight="bold" if is_active else "normal"),
                corner_radius=6,
                command=lambda it=item: self._select_item(it))
            item_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))

            del_btn = ctk.CTkButton(
                row_f, text="✕", width=26, height=26,
                fg_color="transparent", hover_color=COLORS["accent"],
                text_color=COLORS["text_muted"],
                font=ctk.CTkFont(size=11),
                corner_radius=5,
                command=lambda it=item: self._remove_item(it))
            del_btn.grid(row=0, column=1)

    def _on_mode_change(self, val):
        self.monitor_mode = val
        items = self._current_items()
        self.active_item = items[0] if items else None
        self._refresh_side_list()
        if self.active_item:
            self._load_tweets_async(self.active_item)
        else:
            self._clear_tweet_panel(f"暂无{val}监控，请在下方添加")

    def _select_item(self, item):
        self.active_item = item
        self._refresh_side_list()
        self._load_tweets_async(item)

    def _add_item(self):
        val = self.add_entry.get().strip()
        if not val:
            return
        if self.monitor_mode == "账号":
            val = self.data_manager.add_account(val)
        else:
            self.data_manager.add_keyword(val)
        self.add_entry.delete(0, "end")
        self._refresh_side_list()
        self._select_item(val)

    def _remove_item(self, item):
        all_items = self._current_items()
        if len(all_items) <= 1:
            messagebox.showwarning("提示", "至少需要保留一项！")
            return
        if messagebox.askyesno("确认删除", f"确认删除「{item}」吗？"):
            if self.monitor_mode == "账号":
                self.data_manager.remove_account(item)
            else:
                self.data_manager.remove_keyword(item)
            # 删除后修正 active_item
            remaining = self._current_items()
            if self.active_item == item or self.active_item not in remaining:
                self.active_item = remaining[0] if remaining else None
            self._refresh_side_list()
            if self.active_item:
                self._load_tweets_async(self.active_item)
            else:
                self._clear_tweet_panel("已清空，请添加新的监控项")

    def _clear_tweet_panel(self, msg="暂无内容"):
        """清空中栏推文列表并显示提示（用于列表为空时的健壮性处理）。"""
        for w in self.tweets_scroll.winfo_children():
            w.destroy()
        self.selected_tweet = None
        self.selected_card = None
        self.tweet_panel_title.configure(text="推文监控面板")
        ctk.CTkLabel(
            self.tweets_scroll, text=msg,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            justify="center").grid(row=0, column=0, pady=40)

    # ---------- 中栏：推文列表 + 手动输入 ----------
    def _build_tweet_panel(self):
        self._tweet_panel_frame = ctk.CTkFrame(self.main, fg_color=COLORS["panel"], corner_radius=10)
        self._tweet_panel_frame.grid(row=0, column=1, sticky="nsew", padx=6)
        self._tweet_panel_frame.grid_rowconfigure(0, weight=0)
        self._tweet_panel_frame.grid_rowconfigure(1, weight=0)
        self._tweet_panel_frame.grid_rowconfigure(2, weight=1)
        self._tweet_panel_frame.grid_columnconfigure(0, weight=1)

        self.tweet_panel_title = ctk.CTkLabel(
            self._tweet_panel_frame, text="推文面板",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"])
        self.tweet_panel_title.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        self.tweet_mode_seg = ctk.CTkSegmentedButton(
            self._tweet_panel_frame,
            values=["📡 自动抓取", "✏️ 手动输入"],
            command=self._on_tweet_mode_change,
            fg_color=COLORS["input"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["input"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"))
        self.tweet_mode_seg.set("📡 自动抓取")
        self.tweet_mode_seg.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")

        self.tweets_scroll = ctk.CTkScrollableFrame(
            self._tweet_panel_frame, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["card_hover"])
        self.tweets_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self.tweets_scroll.grid_columnconfigure(0, weight=1)

        self._build_manual_input_panel(self._tweet_panel_frame)

    def _build_manual_input_panel(self, parent):
        self.manual_panel = ctk.CTkFrame(parent, fg_color="transparent")
        self.manual_panel.grid_columnconfigure(0, weight=1)
        self.manual_panel.grid_rowconfigure(4, weight=1)

        hint = ctk.CTkLabel(
            self.manual_panel,
            text=("📋  从浏览器中复制推文内容，粘贴到下方。\n"
                  "填好后点击「确认选中」即可使用 AI 生成文案。"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            justify="left")
        hint.grid(row=0, column=0, padx=14, pady=(10, 6), sticky="w")

        ctk.CTkLabel(
            self.manual_panel, text="推文作者（选填，如 @elonmusk）",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).grid(row=1, column=0, padx=14, pady=(6, 2), sticky="w")

        self.manual_author = ctk.CTkEntry(
            self.manual_panel,
            placeholder_text="@用户名 或 显示名称",
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=12),
            height=34)
        self.manual_author.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.manual_panel, text="推文正文内容（从 X 浏览器复制粘贴）",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")

        self.manual_content = ctk.CTkTextbox(
            self.manual_panel,
            fg_color=COLORS["input"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=13),
            corner_radius=6,
            wrap="word")
        self.manual_content.grid(row=4, column=0, padx=14, pady=(0, 10), sticky="nsew")
        self.manual_content.insert("0.0", "在此粘贴推文内容…")
        self.manual_content.bind("<FocusIn>", self._manual_content_focus)

        self.manual_confirm_btn = ctk.CTkButton(
            self.manual_panel,
            text="✅  确认选中此推文，开始生成",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40, corner_radius=6,
            command=self._confirm_manual_tweet)
        self.manual_confirm_btn.grid(row=5, column=0, padx=14, pady=(0, 14), sticky="ew")

    def _manual_content_focus(self, event):
        current = self.manual_content.get("0.0", "end").strip()
        if current == "在此粘贴推文内容…":
            self.manual_content.delete("0.0", "end")

    def _on_tweet_mode_change(self, val):
        if val == "✏️ 手动输入":
            self.tweets_scroll.grid_remove()
            self.manual_panel.grid(row=2, column=0, sticky="nsew", padx=4, pady=(0, 8))
            self.tweet_panel_title.configure(text="手动输入推文")
            self._set_status("手动输入模式：请从浏览器复制推文内容粘贴到下方")
        else:
            self.manual_panel.grid_remove()
            self.tweets_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
            self.tweet_panel_title.configure(text="推文监控面板")
            if self.active_item:
                self._set_status(f"自动抓取模式：正在加载 {self.active_item}")

    def _clear_card_highlight(self):
        """取消当前选中卡片的视觉高亮（用于手动模式覆盖选中态时）。"""
        if self.selected_card and self.selected_card.winfo_exists():
            self.selected_card.configure(
                fg_color=COLORS["card"],
                border_color=COLORS["border"], border_width=1)

    def _confirm_manual_tweet(self):
        content = self.manual_content.get("0.0", "end").strip()
        author = self.manual_author.get().strip()

        if not content or content == "在此粘贴推文内容…":
            messagebox.showwarning("提示", "请先在文本框中粘贴推文内容！")
            return

        if not author:
            author = "未知作者"
        if not author.startswith("@"):
            display_name = author
            username_tag = f"@{author}"
        else:
            display_name = author.lstrip("@")
            username_tag = author

        # 清理自动模式下残留的卡片高亮，保证选中态一致
        self._clear_card_highlight()

        self.selected_tweet = Tweet(
            username=username_tag,
            display_name=display_name,
            text=content,
            time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            likes=0,
            retweets=0,
            avatar_url="",
        )
        self.selected_card = None  # 手动模式没有卡片对象

        self.tweet_preview.configure(state="normal")
        self.tweet_preview.delete("0.0", "end")
        self.tweet_preview.insert(
            "0.0",
            f"作者: {display_name} ({username_tag})\n"
            f"时间: {self.selected_tweet.time}\n\n"
            f"{content}")
        self.tweet_preview.configure(state="disabled")

        self._set_status(f"✓ 已选中手动输入推文（作者: {username_tag}），请点击右侧按钮生成内容")

        self.manual_confirm_btn.configure(text="✅  已选中！请切换至右侧生成", fg_color=COLORS["success"])
        self.after(2000, lambda: self.manual_confirm_btn.configure(
            text="✅  确认选中此推文，开始生成", fg_color=COLORS["accent"]))

    # ---------- 右栏：AI 生成面板 ----------
    def _build_ai_panel(self):
        af = ctk.CTkFrame(self.main, fg_color=COLORS["panel"], corner_radius=10)
        af.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        af.grid_rowconfigure(0, weight=0)
        af.grid_rowconfigure(1, weight=0)
        af.grid_rowconfigure(2, weight=0)
        af.grid_rowconfigure(3, weight=0)
        af.grid_rowconfigure(4, weight=0)
        af.grid_rowconfigure(5, weight=0)
        af.grid_rowconfigure(6, weight=0)
        af.grid_rowconfigure(7, weight=1)
        af.grid_columnconfigure(0, weight=1)

        # === Prompt 选择 ===
        pm_top = ctk.CTkFrame(af, fg_color="transparent")
        pm_top.grid(row=0, column=0, padx=14, pady=(12, 2), sticky="ew")
        pm_top.grid_columnconfigure(0, weight=1)
        pm_top.grid_columnconfigure(1, weight=0)
        pm_top.grid_columnconfigure(2, weight=0)
        pm_top.grid_columnconfigure(3, weight=0)

        pm_label = ctk.CTkLabel(
            pm_top, text="Prompt 模板",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"])
        pm_label.grid(row=0, column=0, sticky="w")

        self.save_prompt_btn = ctk.CTkButton(
            pm_top, text="💾 保存", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._save_prompt)
        self.save_prompt_btn.grid(row=0, column=1, padx=2)

        self.new_prompt_btn = ctk.CTkButton(
            pm_top, text="＋ 新建", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._new_prompt)
        self.new_prompt_btn.grid(row=0, column=2, padx=2)

        self.del_prompt_btn = ctk.CTkButton(
            pm_top, text="✕ 删除", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["accent"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._delete_prompt)
        self.del_prompt_btn.grid(row=0, column=3, padx=(2, 0))

        names = self.data_manager.get_prompt_names()
        self._current_prompt_name = names[0] if names else ""
        self.prompt_combo = ctk.CTkOptionMenu(
            af,
            values=names,
            command=self._on_prompt_select,
            fg_color=COLORS["input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text_primary"],
            dropdown_text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12))
        self.prompt_combo.grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        if self._current_prompt_name:
            self.prompt_combo.set(self._current_prompt_name)

        self.prompt_editor = ctk.CTkTextbox(
            af, height=110,
            fg_color=COLORS["input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=11),
            corner_radius=6,
            wrap="word")
        self.prompt_editor.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="ew")
        if self._current_prompt_name:
            self.prompt_editor.insert("0.0", self.data_manager.get_prompt(self._current_prompt_name))

        # === 三大操作按钮 ===
        btn_f = ctk.CTkFrame(af, fg_color="transparent")
        btn_f.grid(row=3, column=0, padx=14, pady=(0, 8), sticky="ew")
        btn_f.grid_columnconfigure(0, weight=1)
        btn_f.grid_columnconfigure(1, weight=1)
        btn_f.grid_columnconfigure(2, weight=1)

        self.btn_reply = ctk.CTkButton(
            btn_f, text="💬 回复",
            fg_color=COLORS["input"], hover_color=COLORS["accent"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34, corner_radius=6,
            command=lambda: self._generate("reply"))
        self.btn_reply.grid(row=0, column=0, padx=2, sticky="ew")

        self.btn_retweet = ctk.CTkButton(
            btn_f, text="🔁 转推",
            fg_color=COLORS["input"], hover_color=COLORS["accent"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34, corner_radius=6,
            command=lambda: self._generate("retweet"))
        self.btn_retweet.grid(row=0, column=1, padx=2, sticky="ew")

        self.btn_thread = ctk.CTkButton(
            btn_f, text="🧵 Thread",
            fg_color=COLORS["input"], hover_color=COLORS["accent"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34, corner_radius=6,
            command=lambda: self._generate("thread"))
        self.btn_thread.grid(row=0, column=2, padx=2, sticky="ew")

        # === 源推文预览 ===
        src_lbl = ctk.CTkLabel(
            af, text="选中的源推文",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"])
        src_lbl.grid(row=4, column=0, padx=14, pady=(4, 2), sticky="w")

        self.tweet_preview = ctk.CTkTextbox(
            af, height=80,
            fg_color=COLORS["input"],
            text_color=COLORS["text_secondary"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=11),
            corner_radius=6)
        self.tweet_preview.grid(row=5, column=0, padx=14, pady=(0, 8), sticky="ew")
        self.tweet_preview.insert("0.0", "— 请在中栏点击选择一条推文 —")
        self.tweet_preview.configure(state="disabled")

        # === 生成结果区 ===
        res_lbl = ctk.CTkLabel(
            af, text="AI 生成结果  (可直接编辑)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"])
        res_lbl.grid(row=6, column=0, padx=14, pady=(0, 2), sticky="w")

        self.result_box = ctk.CTkTextbox(
            af,
            fg_color=COLORS["input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1,
            font=ctk.CTkFont(size=13),
            corner_radius=6,
            wrap="word")
        self.result_box.grid(row=7, column=0, padx=14, pady=(0, 8), sticky="nsew")
        self.result_box.insert("0.0", "等待生成…")

        self.copy_btn = ctk.CTkButton(
            af, text="📋  一键复制到剪贴板",
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38, corner_radius=6,
            command=self._copy_result)
        self.copy_btn.grid(row=8, column=0, padx=14, pady=(0, 14), sticky="ew")

    # ----- 状态栏 -----
    def _build_statusbar(self):
        sb = ctk.CTkFrame(self, fg_color=COLORS["panel"], height=28, corner_radius=0)
        sb.grid(row=2, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_columnconfigure(1, weight=0)
        sb.grid_rowconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            sb, text="就绪",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"])
        self.status_lbl.grid(row=0, column=0, padx=14, sticky="w")

        engine_info = f"引擎: {self.ai_provider.upper()} / {self.ai_model_name}"
        ctk.CTkLabel(
            sb, text=engine_info,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]).grid(row=0, column=1, padx=14, sticky="e")

    def _set_status(self, msg):
        self.status_lbl.configure(text=msg)

    # ==========================================================================
    # Prompt 管理
    # ==========================================================================
    def _refresh_prompt_combo(self):
        names = self.data_manager.get_prompt_names()
        self.prompt_combo.configure(values=names)
        if names:
            self.prompt_combo.set(names[0])
            self._on_prompt_select(names[0])

    def _on_prompt_select(self, name):
        self._current_prompt_name = name
        content = self.data_manager.get_prompt(name)
        self.prompt_editor.delete("0.0", "end")
        self.prompt_editor.insert("0.0", content)

    def _save_prompt(self):
        name = self._current_prompt_name
        content = self.prompt_editor.get("0.0", "end").strip()
        if not name or not content:
            return
        self.data_manager.save_prompt(name, content)
        self._set_status(f"Prompt「{name}」已保存 ✓")

    def _new_prompt(self):
        name = simpledialog.askstring("新建 Prompt 模板", "请输入新模板名称：", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        default_content = (
            "你是一个X平台内容运营专家。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请用{language}生成内容：\n"
            "（在此编辑你的 Prompt 要求）"
        )
        self.data_manager.save_prompt(name, default_content)
        self._current_prompt_name = name
        self._refresh_prompt_combo()
        self.prompt_combo.set(name)
        self._on_prompt_select(name)
        self._set_status(f"新建 Prompt「{name}」成功，请编辑后保存。")

    def _delete_prompt(self):
        name = self._current_prompt_name
        if not name:
            return
        if len(self.data_manager.get_prompt_names()) <= 1:
            messagebox.showwarning("提示", "至少需要保留一个 Prompt 模板！")
            return
        if messagebox.askyesno("确认删除", f"确定删除 Prompt 模板「{name}」吗？"):
            self.data_manager.delete_prompt(name)
            self._refresh_prompt_combo()
            self._set_status(f"已删除 Prompt「{name}」")

    # ==========================================================================
    # 推文抓取与渲染
    # ==========================================================================
    def _on_lang_change(self, val):
        self.language_mode = val
        self._set_status(f"语言切换为：{val}")

    def _refresh_current(self):
        if self.active_item:
            # 用户主动刷新 → 强制绕过抓取缓存
            self._load_tweets_async(self.active_item, force_refresh=True)

    def _load_tweets_async(self, item, force_refresh: bool = False):
        mode_text = "账号" if self.monitor_mode == "账号" else "关键词"
        self._set_status(f"正在抓取「{item}」的最新推文…")
        for w in self.tweets_scroll.winfo_children():
            w.destroy()
        self.selected_tweet = None
        self.selected_card = None

        self.tweet_panel_title.configure(
            text=f"推文监控 · {mode_text}：{item}")

        loading = ctk.CTkLabel(
            self.tweets_scroll,
            text="📡  正在联网抓取数据，请稍候…",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"])
        loading.grid(row=0, column=0, pady=50)

        def _run():
            try:
                if self.monitor_mode == "账号":
                    tweets = self.scraper.get_tweets_by_account(
                        item, force_refresh=force_refresh)
                else:
                    tweets = self.scraper.get_tweets_by_keyword(
                        item, force_refresh=force_refresh)
                self.after(0, lambda: self._render_tweets(tweets, item))
            except Exception as e:
                log.warning("抓取「%s」失败: %s", item, e)
                self.after(0, lambda: self._show_fetch_error(str(e), item))

        threading.Thread(target=_run, daemon=True).start()

    def _render_tweets(self, tweets, item):
        for w in self.tweets_scroll.winfo_children():
            w.destroy()

        if not tweets:
            ctk.CTkLabel(
                self.tweets_scroll,
                text="⚠  该账号暂无可解析的推文\n（可能实例暂时不可用或内容为空）",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_secondary"],
                justify="center").grid(row=0, column=0, pady=40)
            self._set_status(f"「{item}」推文加载完毕（0条）")
            return

        self._set_status(f"「{item}」加载完毕 · {len(tweets)} 条推文")
        for i, t in enumerate(tweets):
            self._build_tweet_card(i, t)

    def _show_fetch_error(self, err_msg, item):
        for w in self.tweets_scroll.winfo_children():
            w.destroy()
        self._set_status(f"抓取失败：{err_msg[:80]}")

        ctk.CTkLabel(
            self.tweets_scroll,
            text=(f"❌  推文抓取失败\n\n"
                  f"{err_msg}\n\n"
                  f"建议：\n"
                  f"• 确认网络可访问海外站点（如需科学上网请开启）\n"
                  f"• 检查 .env 中的代理设置\n"
                  f"• 或配置官方 X_BEARER_TOKEN 使用官方 API"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["accent"],
            justify="left",
            wraplength=330).grid(row=0, column=0, pady=30, padx=20, sticky="w")

    def _build_tweet_card(self, row_idx, tweet: Tweet):
        card = ctk.CTkFrame(
            self.tweets_scroll,
            fg_color=COLORS["card"],
            border_color=COLORS["border"], border_width=1,
            corner_radius=8)
        card.grid(row=row_idx, column=0, sticky="ew", padx=6, pady=5)
        card.grid_columnconfigure(0, weight=0)
        card.grid_columnconfigure(1, weight=1)

        # 头像（字母占位 + CTkImage 缓存）
        initial = (tweet.display_name or "X")[0].upper()
        ctk_avatar = self._ctk_avatar_cache.get(initial)
        if ctk_avatar is None:
            avatar_img = generate_letter_avatar(initial)
            ctk_avatar = ctk.CTkImage(light_image=avatar_img,
                                      dark_image=avatar_img, size=(38, 38))
            self._ctk_avatar_cache[initial] = ctk_avatar
        av_lbl = ctk.CTkLabel(card, image=ctk_avatar, text="")
        av_lbl.grid(row=0, column=0, rowspan=3, padx=(12, 8), pady=12, sticky="n")

        hdr = ctk.CTkLabel(
            card,
            text=f"{tweet.display_name}  {tweet.username}  ·  {tweet.time}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_muted"],
            anchor="w")
        hdr.grid(row=0, column=1, padx=(0, 10), pady=(10, 2), sticky="w")

        content = ctk.CTkLabel(
            card, text=tweet.text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_primary"],
            justify="left",
            anchor="w",
            wraplength=340)
        content.grid(row=1, column=1, padx=(0, 14), pady=4, sticky="w")

        stats = ctk.CTkLabel(
            card,
            text=f"♥ {tweet.likes:,}    ⟳ {tweet.retweets:,}",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            anchor="w")
        stats.grid(row=2, column=1, padx=(0, 10), pady=(2, 10), sticky="w")

        self._bind_card_events(card, tweet)

    def _bind_card_events(self, card, tweet):
        def on_enter(e):
            if card != self.selected_card:
                card.configure(fg_color=COLORS["card_hover"])

        def on_leave(e):
            if card != self.selected_card:
                card.configure(fg_color=COLORS["card"])

        def on_click(e):
            self._select_tweet(card, tweet)

        for w in [card] + card.winfo_children():
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)
            for child in w.winfo_children():
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)
                child.bind("<Button-1>", on_click)

    def _select_tweet(self, card, tweet: Tweet):
        # 取消上一张卡片高亮
        if self.selected_card and self.selected_card.winfo_exists():
            self.selected_card.configure(
                fg_color=COLORS["card"],
                border_color=COLORS["border"], border_width=1)

        card.configure(
            fg_color=COLORS["card_active"],
            border_color=COLORS["accent"], border_width=2)
        self.selected_card = card
        self.selected_tweet = tweet

        self.tweet_preview.configure(state="normal")
        self.tweet_preview.delete("0.0", "end")
        preview = (f"作者: {tweet.display_name} ({tweet.username})\n"
                   f"时间: {tweet.time}\n\n"
                   f"{tweet.text}")
        self.tweet_preview.insert("0.0", preview)
        self.tweet_preview.configure(state="disabled")
        self._set_status(f"已选中 {tweet.username} 的推文")

    # ==========================================================================
    # AI 生成
    # ==========================================================================
    def _get_active_prompt_template(self):
        return self.prompt_editor.get("0.0", "end").strip()

    def _set_generating(self, is_gen, action=""):
        state = "disabled" if is_gen else "normal"
        for btn, label in [
            (self.btn_reply, "💬 回复"),
            (self.btn_retweet, "🔁 转推"),
            (self.btn_thread, "🧵 Thread"),
        ]:
            btn.configure(state=state)
            if not is_gen:
                btn.configure(text=label, fg_color=COLORS["input"])
        self.refresh_btn.configure(state=state)

        if is_gen:
            labels = {"reply": "💬 回复", "retweet": "🔁 转推", "thread": "🧵 Thread"}
            target = {"reply": self.btn_reply,
                      "retweet": self.btn_retweet,
                      "thread": self.btn_thread}.get(action)
            if target:
                target.configure(text="⏳ 生成中…", fg_color=COLORS["accent"])

    def _generate(self, action):
        if not self.selected_tweet:
            messagebox.showwarning("提示", "请先在中栏点击选择一条推文！")
            return

        template = self._get_active_prompt_template()
        if not template:
            messagebox.showwarning("提示", "当前 Prompt 模板为空，请先填写或选择一个模板！")
            return

        self._set_generating(True, action)
        self._set_status("AI 正在生成中，请稍候…")
        self.result_box.delete("0.0", "end")
        self.result_box.insert("0.0", "🤖  AI 正在深度分析推文内容，请耐心等待…")

        tw = self.selected_tweet
        # safe_format: 仅替换已知占位符，用户推文中的 {xxx} 不会触发 KeyError
        prompt = safe_format(
            template,
            tweet_content=tw.text,
            author=f"{tw.display_name} ({tw.username})",
            language=self.language_mode,
        )

        def _run():
            try:
                result = self.ai_generator.generate(prompt)
                self.after(0, lambda: self._on_gen_success(result))
            except Exception as e:
                log.warning("AI 生成失败: %s", e)
                self.after(0, lambda: self._on_gen_fail(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_gen_success(self, result):
        self._set_generating(False)
        self.result_box.delete("0.0", "end")
        self.result_box.insert("0.0", result.strip())
        self._set_status("✓ AI 内容生成成功！")

    def _on_gen_fail(self, err):
        self._set_generating(False)
        self.result_box.delete("0.0", "end")
        self.result_box.insert("0.0",
            f"❌  生成失败\n\n{err}\n\n"
            "请检查 .env 中的 API Key 及网络连接是否正常。")
        self._set_status(f"生成失败: {err[:60]}")

    def _copy_result(self):
        content = self.result_box.get("0.0", "end").strip()
        if not content or "等待生成" in content or "正在深度分析" in content:
            messagebox.showwarning("提示", "生成结果为空或尚未生成，无法复制！")
            return
        pyperclip.copy(content)
        self._set_status("✓ 已复制到剪贴板！")
        orig = self.copy_btn.cget("text")
        self.copy_btn.configure(text="✅  复制成功！", fg_color=COLORS["success"])
        self.after(1800, lambda: self.copy_btn.configure(text=orig, fg_color=COLORS["accent"]))
