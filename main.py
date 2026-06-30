"""
X28 - X平台内容运营辅助工具 (第二阶段重构版)
核心改进:
  1. Obsidian 曜石黑高级 UI 配色 + 卡片 Hover 微交互
  2. 双模式监控：账号监控 + 关键词/话题监控
  3. 网络自愈：代理变量自动修复 + twiiit.com 智能网关
  4. Prompt 模板管理器：预设 + 自定义，持久化 data/prompts.json
"""

import os
import sys
import json
import re
import html
import io
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog
import requests
import pyperclip
from dotenv import load_dotenv
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# 0. 启动前置：修复代理变量（防止 [http://...] 格式导致网络库挂起）
# ==============================================================================
def fix_proxy_env():
    """检测并修复 Windows 下代理环境变量中的括号格式问题。
    例如将 '[http://127.0.0.1]:7897' 修复为 'http://127.0.0.1:7897'
    """
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        val = os.environ.get(key, "")
        if val:
            # 匹配 [scheme://host]:port 这类带方括号的异常格式
            fixed = re.sub(r'^\[(.+)\]:(\d+)$', r'\1:\2', val.strip())
            if fixed != val:
                print(f"[代理修复] {key}: '{val}' → '{fixed}'")
                os.environ[key] = fixed

fix_proxy_env()
load_dotenv()

# ==============================================================================
# 1. 主题配色系统（曜石黑高级质感）
# ==============================================================================
COLORS = {
    "bg":           "#0c0c0e",   # 主背景：暗夜曜石黑
    "panel":        "#16161a",   # 侧栏/面板背景：深炭灰
    "card":         "#1e1e23",   # 推文卡片背景
    "card_hover":   "#27272e",   # 卡片悬停色
    "card_active":  "#1f1f2c",   # 卡片选中背景
    "input":        "#222228",   # 输入框/文本区背景
    "border":       "#2d2d36",   # 精致 1px 边框
    "accent":       "#e94560",   # 主高亮色（珊瑚红）
    "accent_hover": "#c83650",   # 高亮悬停色
    "accent_dim":   "#7a1e30",   # 低饱和强调（禁用态）
    "text_primary": "#f0f0f2",   # 主文字：纯白
    "text_secondary":"#8b8b9a",  # 次级文字：中灰
    "text_muted":   "#52525e",   # 辅助文字：暗灰
    "success":      "#2ecc71",   # 成功状态绿
    "warning":      "#f39c12",   # 警告状态橙
}

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ==============================================================================
# 2. 工具函数
# ==============================================================================
def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>', re.DOTALL)
    cleantext = re.sub(cleanr, '', raw_html)
    return html.unescape(cleantext).strip()

def parse_k_notation(val_str):
    val_str = str(val_str).lower().strip()
    try:
        if 'k' in val_str:
            return int(float(val_str.replace('k', '')) * 1000)
        elif 'm' in val_str:
            return int(float(val_str.replace('m', '')) * 1_000_000)
        return int(val_str)
    except:
        return 0

def extract_stats(raw_html):
    likes, retweets = 0, 0
    likes_match = re.search(r'Likes?:\s*([\d\.\w]+)', raw_html, re.IGNORECASE)
    if likes_match:
        likes = parse_k_notation(likes_match.group(1))
    rt_match = re.search(r'Re-?tweets?:\s*([\d\.\w]+)', raw_html, re.IGNORECASE)
    if rt_match:
        retweets = parse_k_notation(rt_match.group(1))
    return likes, retweets

def generate_letter_avatar(letter, size=(42, 42), bg_color="#e94560", fg_color="#f0f0f2"):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size[0]-1, size[1]-1], fill=bg_color)
    letter = letter.upper()[:1] if letter else "X"
    try:
        font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), letter, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size[0]-w)/2, (size[1]-h)/2 - 1), letter, fill=fg_color, font=font)
    except:
        draw.text((14, 12), letter, fill=fg_color)
    return img

def format_pubdate(raw_str):
    """尝试多种时间格式，返回友好的本地时间字符串"""
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw_str.strip()[:31], fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass
    return raw_str[:16] if raw_str else "未知时间"


# ==============================================================================
# 3. 数据管理层 (DataManager) — 读写 data/config.json 与 data/prompts.json
# ==============================================================================
class DataManager:
    """管理账号列表、关键词列表、Prompt 模板的本地持久化"""

    DEFAULT_ACCOUNTS = ["@RockstarGames", "@GTAVIGame", "@Google", "@OpenAI"]
    DEFAULT_KEYWORDS  = ["AI agent", "Twitter growth", "X platform"]

    DEFAULT_PROMPTS = {
        "标准回复 (Reply)": (
            "你是一个专业的X平台内容运营专家。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条{language}回复，要求：\n"
            "- 有实质性观点，不是泛泛而谈\n"
            "- 语气自然，像真人在对话\n"
            "- 不超过100字\n"
            "- 不要加hashtag\n"
            "- 直接输出回复内容，不要任何前缀说明"
        ),
        "转推评论 (Quote Tweet)": (
            "你是一个专业的X平台内容运营专家。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条用于转推（Quote Tweet）的{language}评论，要求：\n"
            "- 表达实质性的观点和态度，语气要吸睛\n"
            "- 包含1-2个适当的emoji以增强观感\n"
            "- 不超过140字\n"
            "- 直接输出评论内容，不需要任何额外前缀"
        ),
        "系列推文 Thread": (
            "你是一个专业的X平台内容运营专家。\n"
            "参考推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请基于这条推文的话题，生成一条{language} Thread，要求：\n"
            "- 共4条推文，每条开头用 [1/4] [2/4] [3/4] [4/4] 标注\n"
            "- 第1条：抓眼球的钩子句，提出核心问题或观点\n"
            "- 第2-3条：展开论述，每条一个要点\n"
            "- 第4条：总结并加入行动号召(CTA)\n"
            "- 每条不超过250字符，之间用 \"---\" 分隔\n"
            "- 直接输出内容，不要任何前缀说明"
        ),
        "幽默互动": (
            "你是一个幽默风趣的X平台运营达人。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条有趣、幽默、带点网络流行语风格的{language}回复，要求：\n"
            "- 轻松调侃但不冒犯\n"
            "- 可加1-2个emoji\n"
            "- 不超过80字\n"
            "- 直接输出内容，不要任何前缀"
        ),
        "专业分析": (
            "你是一位资深的科技/商业分析师。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请对这条推文的话题做一段深度的{language}点评分析，要求：\n"
            "- 从行业视角提供独到的见解\n"
            "- 引用数据或趋势加以佐证（如有）\n"
            "- 语气专业严谨但不失可读性\n"
            "- 不超过150字\n"
            "- 直接输出内容，不要任何前缀"
        ),
    }

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.config_path  = os.path.join(data_dir, "config.json")
        self.prompts_path = os.path.join(data_dir, "prompts.json")
        self._load_config()
        self._load_prompts()

    # ---- 账号与关键词 ----
    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.accounts = cfg.get("accounts", self.DEFAULT_ACCOUNTS)
                self.keywords = cfg.get("keywords", self.DEFAULT_KEYWORDS)
                return
            except Exception as e:
                print(f"加载 config.json 失败: {e}")
        self.accounts = list(self.DEFAULT_ACCOUNTS)
        self.keywords = list(self.DEFAULT_KEYWORDS)
        self._save_config()

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"accounts": self.accounts, "keywords": self.keywords},
                          f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存 config.json 失败: {e}")

    def add_account(self, acc):
        acc = acc.strip()
        if not acc.startswith("@"):
            acc = "@" + acc
        if acc not in self.accounts:
            self.accounts.append(acc)
            self._save_config()
        return acc

    def remove_account(self, acc):
        if acc in self.accounts:
            self.accounts.remove(acc)
            self._save_config()

    def add_keyword(self, kw):
        kw = kw.strip()
        if kw and kw not in self.keywords:
            self.keywords.append(kw)
            self._save_config()

    def remove_keyword(self, kw):
        if kw in self.keywords:
            self.keywords.remove(kw)
            self._save_config()

    # ---- Prompt 模板 ----
    def _load_prompts(self):
        if os.path.exists(self.prompts_path):
            try:
                with open(self.prompts_path, "r", encoding="utf-8") as f:
                    self.prompts = json.load(f)
                # 补全缺失的默认模板
                for k, v in self.DEFAULT_PROMPTS.items():
                    self.prompts.setdefault(k, v)
                return
            except Exception as e:
                print(f"加载 prompts.json 失败: {e}")
        self.prompts = dict(self.DEFAULT_PROMPTS)
        self._save_prompts()

    def _save_prompts(self):
        try:
            with open(self.prompts_path, "w", encoding="utf-8") as f:
                json.dump(self.prompts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存 prompts.json 失败: {e}")

    def save_prompt(self, name, content):
        self.prompts[name.strip()] = content
        self._save_prompts()

    def delete_prompt(self, name):
        if name in self.prompts:
            del self.prompts[name]
            self._save_prompts()

    def get_prompt_names(self):
        return list(self.prompts.keys())

    def get_prompt(self, name):
        return self.prompts.get(name, "")


# ==============================================================================
# 4. 数据抓取层 (TwitterScraper) — twiiit.com 智能网关
# ==============================================================================
class TwitterScraper:
    """
    优先使用官方 X API v2；
    失败或未配置时，使用 twiiit.com 作为 Nitter 智能网关进行 RSS 抓取。
    twiiit.com 会自动重定向到当前存活的 Nitter 实例，无需维护实例列表。
    """

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    def __init__(self, bearer_token=""):
        self.bearer_token = (bearer_token or "").strip()

    # ---------- 公开接口 ----------
    def get_tweets_by_account(self, username: str):
        clean = username.lstrip("@")
        if self.bearer_token:
            try:
                return self._x_api_user(clean)
            except Exception as e:
                print(f"X API 失败: {e}，降级到 Nitter…")
        return self._nitter_user(clean)

    def get_tweets_by_keyword(self, query: str):
        """通过关键词搜索推文（使用 twiiit.com 搜索 RSS）"""
        return self._nitter_search(query)

    # ---------- X API v2 ----------
    def _x_api_user(self, username):
        h = {"Authorization": f"Bearer {self.bearer_token}"}
        r = requests.get(
            f"https://api.twitter.com/2/users/by/username/{username}",
            headers=h, timeout=10)
        r.raise_for_status()
        uid = r.json()["data"]["id"]

        r2 = requests.get(
            f"https://api.twitter.com/2/users/{uid}/tweets",
            headers=h, timeout=10,
            params={
                "max_results": 20,
                "tweet.fields": "created_at,public_metrics",
                "expansions": "author_id",
                "user.fields": "profile_image_url,username,name",
            })
        r2.raise_for_status()
        data = r2.json()
        users_map = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        tweets = []
        for t in data.get("data", []):
            m = t.get("public_metrics", {})
            uid2 = t.get("author_id", "")
            uinfo = users_map.get(uid2, {})
            dt_str = t.get("created_at", "")
            try:
                dt_str = datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M")
            except:
                pass
            tweets.append({
                "username": f"@{username}",
                "display_name": uinfo.get("name", username),
                "text": t.get("text", ""),
                "time": dt_str,
                "likes": m.get("like_count", 0),
                "retweets": m.get("retweet_count", 0),
                "avatar_url": uinfo.get("profile_image_url", ""),
            })
        return tweets

    # ---------- Nitter / twiiit.com ----------
    def _nitter_user(self, username):
        url = f"https://twiiit.com/{username}/rss"
        return self._fetch_and_parse_rss(url, default_username=username)

    def _nitter_search(self, query):
        import urllib.parse
        q = urllib.parse.quote(query)
        url = f"https://twiiit.com/search/rss?f=tweets&q={q}"
        return self._fetch_and_parse_rss(url, default_username=query)

    def _fetch_and_parse_rss(self, url, default_username=""):
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=12, allow_redirects=True)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            return self._parse_rss(resp.text, default_username)
        except requests.exceptions.ProxyError as e:
            raise Exception(f"代理连接失败，请检查代理设置或关闭代理后重试。({e})")
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"网络连接错误，请检查网络是否畅通。({e})")
        except requests.exceptions.Timeout:
            raise Exception("请求超时，请确认网络可访问 twiiit.com，可能需要科学上网。")
        except Exception as e:
            raise Exception(str(e))

    def _parse_rss(self, xml_text, default_username):
        import xml.etree.ElementTree as ET
        tweets = []
        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
            channel = root.find("channel")
            if channel is None:
                return []
            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            for item in channel.findall("item")[:20]:
                desc_el   = item.find("description")
                date_el   = item.find("pubDate")
                creator_el = item.find("dc:creator", ns)

                raw_html = desc_el.text if desc_el is not None else ""
                text = clean_html(raw_html)
                likes, retweets = extract_stats(raw_html)
                time_str = format_pubdate(date_el.text if date_el is not None else "")

                display_name = (creator_el.text or default_username) if creator_el is not None else default_username
                disp_clean = display_name.lstrip("@")
                username_tag = f"@{disp_clean}" if not display_name.startswith("@") else display_name

                tweets.append({
                    "username": username_tag,
                    "display_name": disp_clean,
                    "text": text,
                    "time": time_str,
                    "likes": likes,
                    "retweets": retweets,
                    "avatar_url": "",  # twiiit.com 不提供头像 URL，使用字母头像
                })
        except ET.ParseError as e:
            raise Exception(f"RSS 解析失败 (XML 格式错误): {e}")
        return tweets


# ==============================================================================
# 5. AI 生成适配层 (AIGenerator) — 多模型免费版支持
# ==============================================================================
class AIGenerator:
    def __init__(self, provider="gemini", api_key="", model="", base_url=""):
        self.provider = provider.lower().strip()
        self.api_key  = api_key.strip()
        self.model    = model.strip()
        self.base_url = base_url.strip()

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise Exception(f"未配置 {self.provider.upper()} API Key！请检查项目目录下的 .env 文件。")
        if self.provider == "gemini":
            return self._gemini(prompt)
        elif self.provider == "openai":
            return self._openai(prompt)
        elif self.provider == "anthropic":
            return self._anthropic(prompt)
        raise Exception(f"不支持的 AI 提供商: {self.provider}")

    def _gemini(self, prompt):
        model = self.model or "gemini-3.5-flash"
        url = (f"https://generativelanguage.googleapis.com/v1beta"
               f"/models/{model}:generateContent?key={self.api_key}")
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]},
                             headers={"Content-Type": "application/json"}, timeout=45)
        if resp.status_code != 200:
            raise Exception(f"Gemini API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise Exception(f"Gemini 响应格式异常: {resp.text[:300]}")

    def _openai(self, prompt):
        base = self.base_url or "https://api.openai.com/v1"
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            json={"model": self.model or "gpt-4o-mini",
                  "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"}, timeout=45)
        if resp.status_code != 200:
            raise Exception(f"OpenAI API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise Exception(f"OpenAI 响应格式异常: {resp.text[:300]}")

    def _anthropic(self, prompt):
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": self.model or "claude-5-fable", "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"}, timeout=45)
        if resp.status_code != 200:
            raise Exception(f"Anthropic API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["content"][0]["text"]
        except (KeyError, IndexError):
            raise Exception(f"Anthropic 响应格式异常: {resp.text[:300]}")


# ==============================================================================
# 6. 主界面 (AppGUI) — 曜石黑 Obsidian 全面重构版
# ==============================================================================
class AppGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        # ---- 初始化各层 ----
        self.data_manager = DataManager()

        provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        if provider == "openai":
            ai_key   = os.getenv("OPENAI_API_KEY", "")
            ai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif provider == "anthropic":
            ai_key   = os.getenv("ANTHROPIC_API_KEY", "")
            ai_model = os.getenv("ANTHROPIC_MODEL", "claude-5-fable")
        else:
            provider = "gemini"
            ai_key   = os.getenv("GEMINI_API_KEY", "")
            ai_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

        self.ai_generator = AIGenerator(
            provider=provider, api_key=ai_key, model=ai_model,
            base_url=os.getenv("OPENAI_BASE_URL", ""))
        self.scraper = TwitterScraper(bearer_token=os.getenv("X_BEARER_TOKEN", ""))

        # ---- 运行时状态 ----
        self.monitor_mode   = "账号"      # "账号" | "关键词"
        self.selected_tweet = None
        self.selected_card  = None
        self.avatar_cache   = {}
        self.language_mode  = "英文"
        self.active_item    = None        # 当前选中的账号或关键词
        self.ai_model_name  = ai_model
        self.ai_provider    = provider

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

        # 品牌 Logo 文字
        logo = ctk.CTkLabel(
            hf,
            text="✦  X28  |  X平台内容运营助手",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=COLORS["text_primary"])
        logo.grid(row=0, column=0, padx=24, sticky="w")

        # 语言切换
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

        # 刷新按钮
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
        sb.grid_rowconfigure(0, weight=0)  # 模式切换
        sb.grid_rowconfigure(1, weight=0)  # 面板标题
        sb.grid_rowconfigure(2, weight=1)  # 滚动列表
        sb.grid_rowconfigure(3, weight=0)  # 添加区
        sb.grid_columnconfigure(0, weight=1)

        # 模式切换 Segmented button
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

        # 滚动列表容器
        self.side_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["card_hover"])
        self.side_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        self.side_scroll.grid_columnconfigure(0, weight=1)

        # 底部添加输入框
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

    def _refresh_side_list(self):
        for w in self.side_scroll.winfo_children():
            w.destroy()

        items = (self.data_manager.accounts
                 if self.monitor_mode == "账号"
                 else self.data_manager.keywords)

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
        items = (self.data_manager.accounts
                 if val == "账号"
                 else self.data_manager.keywords)
        self.active_item = items[0] if items else None
        self._refresh_side_list()
        if self.active_item:
            self._load_tweets_async(self.active_item)

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
        all_items = (self.data_manager.accounts
                     if self.monitor_mode == "账号"
                     else self.data_manager.keywords)
        if len(all_items) <= 1:
            messagebox.showwarning("提示", "至少需要保留一项！")
            return
        if messagebox.askyesno("确认删除", f"确认删除「{item}」吗？"):
            if self.monitor_mode == "账号":
                self.data_manager.remove_account(item)
            else:
                self.data_manager.remove_keyword(item)
            if self.active_item == item:
                remaining = (self.data_manager.accounts
                             if self.monitor_mode == "账号"
                             else self.data_manager.keywords)
                self.active_item = remaining[0] if remaining else None
            self._refresh_side_list()
            if self.active_item:
                self._load_tweets_async(self.active_item)

    # ---------- 中栏：推文列表 + 手动输入 ----------
    def _build_tweet_panel(self):
        self._tweet_panel_frame = ctk.CTkFrame(self.main, fg_color=COLORS["panel"], corner_radius=10)
        self._tweet_panel_frame.grid(row=0, column=1, sticky="nsew", padx=6)
        self._tweet_panel_frame.grid_rowconfigure(0, weight=0)  # 顶部标题行
        self._tweet_panel_frame.grid_rowconfigure(1, weight=0)  # 模式切换 Tab
        self._tweet_panel_frame.grid_rowconfigure(2, weight=1)  # 内容区（推文列表 或 手动输入）
        self._tweet_panel_frame.grid_columnconfigure(0, weight=1)

        # 顶部标题
        self.tweet_panel_title = ctk.CTkLabel(
            self._tweet_panel_frame, text="推文面板",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"])
        self.tweet_panel_title.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        # 模式切换 Tab：自动抓取 | 手动输入
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

        # 自动抓取区域（推文列表滚动框）
        self.tweets_scroll = ctk.CTkScrollableFrame(
            self._tweet_panel_frame, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["card_hover"])
        self.tweets_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self.tweets_scroll.grid_columnconfigure(0, weight=1)

        # 手动输入区域（默认隐藏）
        self._build_manual_input_panel(self._tweet_panel_frame)

    def _build_manual_input_panel(self, parent):
        """构建手动输入推文的面板，默认隐藏"""
        self.manual_panel = ctk.CTkFrame(parent, fg_color="transparent")
        # 默认不 grid，由模式切换控制显示/隐藏
        self.manual_panel.grid_columnconfigure(0, weight=1)
        self.manual_panel.grid_rowconfigure(4, weight=1)

        # 提示说明
        hint = ctk.CTkLabel(
            self.manual_panel,
            text=("📋  从浏览器中复制推文内容，粘贴到下方。\n"
                  "填好后点击「确认选中」即可使用 AI 生成文案。"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            justify="left")
        hint.grid(row=0, column=0, padx=14, pady=(10, 6), sticky="w")

        # 作者用户名输入
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

        # 推文正文输入
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

        # 确认选中按钮
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
        """首次点击时清除占位文字"""
        current = self.manual_content.get("0.0", "end").strip()
        if current == "在此粘贴推文内容…":
            self.manual_content.delete("0.0", "end")

    def _on_tweet_mode_change(self, val):
        """切换自动抓取 / 手动输入模式"""
        if val == "✏️ 手动输入":
            # 隐藏推文列表，显示手动输入面板
            self.tweets_scroll.grid_remove()
            self.manual_panel.grid(row=2, column=0, sticky="nsew", padx=4, pady=(0, 8))
            self.tweet_panel_title.configure(text="手动输入推文")
            self._set_status("手动输入模式：请从浏览器复制推文内容粘贴到下方")
        else:
            # 隐藏手动面板，显示推文列表
            self.manual_panel.grid_remove()
            self.tweets_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
            self.tweet_panel_title.configure(text="推文监控面板")
            if self.active_item:
                self._set_status(f"自动抓取模式：正在加载 {self.active_item}")

    def _confirm_manual_tweet(self):
        """将手动输入的内容设为当前选中推文，更新右侧预览"""
        content = self.manual_content.get("0.0", "end").strip()
        author  = self.manual_author.get().strip()

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

        # 构建与自动抓取一致的 tweet dict
        self.selected_tweet = {
            "username":     username_tag,
            "display_name": display_name,
            "text":         content,
            "time":         datetime.now().strftime("%Y-%m-%d %H:%M"),
            "likes":        0,
            "retweets":     0,
            "avatar_url":   "",
        }
        self.selected_card = None  # 手动模式没有卡片对象

        # 更新右侧「源推文预览」
        self.tweet_preview.configure(state="normal")
        self.tweet_preview.delete("0.0", "end")
        self.tweet_preview.insert(
            "0.0",
            f"作者: {display_name} ({username_tag})\n"
            f"时间: {self.selected_tweet['time']}\n\n"
            f"{content}")
        self.tweet_preview.configure(state="disabled")

        self._set_status(f"✓ 已选中手动输入推文（作者: {username_tag}），请点击右侧按钮生成内容")

        # 按钮反馈
        self.manual_confirm_btn.configure(text="✅  已选中！请切换至右侧生成", fg_color=COLORS["success"])
        self.after(2000, lambda: self.manual_confirm_btn.configure(
            text="✅  确认选中此推文，开始生成", fg_color=COLORS["accent"]))

    # ---------- 右栏：AI 生成面板 ----------
    def _build_ai_panel(self):
        af = ctk.CTkFrame(self.main, fg_color=COLORS["panel"], corner_radius=10)
        af.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        af.grid_rowconfigure(0, weight=0)   # Prompt 选择区
        af.grid_rowconfigure(1, weight=0)   # Prompt 编辑区
        af.grid_rowconfigure(2, weight=0)   # 操作按钮组
        af.grid_rowconfigure(3, weight=0)   # 预览标题
        af.grid_rowconfigure(4, weight=0)   # 源推文预览
        af.grid_rowconfigure(5, weight=0)   # 生成结果标题
        af.grid_rowconfigure(6, weight=1)   # 生成结果文本框
        af.grid_rowconfigure(7, weight=0)   # 复制按钮
        af.grid_columnconfigure(0, weight=1)

        # === Prompt 选择 ===
        pm_title = ctk.CTkLabel(
            af, text="Prompt 模板",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"])
        pm_title.grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

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

        # 保存按钮
        self.save_prompt_btn = ctk.CTkButton(
            pm_top, text="💾 保存", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._save_prompt)
        self.save_prompt_btn.grid(row=0, column=1, padx=2)

        # 新增按钮
        self.new_prompt_btn = ctk.CTkButton(
            pm_top, text="＋ 新建", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._new_prompt)
        self.new_prompt_btn.grid(row=0, column=2, padx=2)

        # 删除按钮
        self.del_prompt_btn = ctk.CTkButton(
            pm_top, text="✕ 删除", width=60, height=26,
            fg_color=COLORS["input"], hover_color=COLORS["accent"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(size=11),
            corner_radius=5,
            command=self._delete_prompt)
        self.del_prompt_btn.grid(row=0, column=3, padx=(2, 0))

        # Prompt 名称下拉选择
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

        # Prompt 内容编辑框
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

        # 复制按钮
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
        name    = self._current_prompt_name
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
            self._load_tweets_async(self.active_item)

    def _load_tweets_async(self, item):
        mode_text = "账号" if self.monitor_mode == "账号" else "关键词"
        self._set_status(f"正在抓取「{item}」的最新推文…")
        for w in self.tweets_scroll.winfo_children():
            w.destroy()
        self.selected_tweet = None
        self.selected_card  = None

        # 更新面板标题
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
                    tweets = self.scraper.get_tweets_by_account(item)
                else:
                    tweets = self.scraper.get_tweets_by_keyword(item)
                self.after(0, lambda: self._render_tweets(tweets, item))
            except Exception as e:
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

    def _build_tweet_card(self, row_idx, tweet):
        card = ctk.CTkFrame(
            self.tweets_scroll,
            fg_color=COLORS["card"],
            border_color=COLORS["border"], border_width=1,
            corner_radius=8)
        card.grid(row=row_idx, column=0, sticky="ew", padx=6, pady=5)
        card.grid_columnconfigure(0, weight=0)  # 头像
        card.grid_columnconfigure(1, weight=1)  # 文字

        # 头像（字母占位）
        initial = (tweet["display_name"] or "X")[0].upper()
        avatar_img = generate_letter_avatar(initial)
        ctk_avatar = ctk.CTkImage(light_image=avatar_img, dark_image=avatar_img, size=(38, 38))
        av_lbl = ctk.CTkLabel(card, image=ctk_avatar, text="")
        av_lbl.grid(row=0, column=0, rowspan=3, padx=(12, 8), pady=12, sticky="n")

        # 用户名 + 时间
        hdr = ctk.CTkLabel(
            card,
            text=f"{tweet['display_name']}  {tweet['username']}  ·  {tweet['time']}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_muted"],
            anchor="w")
        hdr.grid(row=0, column=1, padx=(0, 10), pady=(10, 2), sticky="w")

        # 推文正文
        content = ctk.CTkLabel(
            card, text=tweet["text"],
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_primary"],
            justify="left",
            anchor="w",
            wraplength=340)
        content.grid(row=1, column=1, padx=(0, 14), pady=4, sticky="w")

        # 互动数据
        stats = ctk.CTkLabel(
            card,
            text=f"♥ {tweet['likes']:,}    ⟳ {tweet['retweets']:,}",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            anchor="w")
        stats.grid(row=2, column=1, padx=(0, 10), pady=(2, 10), sticky="w")

        # 绑定 Hover 微交互 & 点击事件
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
            # 递归绑定子孙控件
            for child in w.winfo_children():
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)
                child.bind("<Button-1>", on_click)

    def _select_tweet(self, card, tweet):
        # 取消上一张卡片高亮
        if self.selected_card and self.selected_card.winfo_exists():
            self.selected_card.configure(
                fg_color=COLORS["card"],
                border_color=COLORS["border"], border_width=1)

        # 高亮当前卡片（左边框红色 + 背景微亮）
        card.configure(
            fg_color=COLORS["card_active"],
            border_color=COLORS["accent"], border_width=2)
        self.selected_card  = card
        self.selected_tweet = tweet

        # 更新源推文预览框
        self.tweet_preview.configure(state="normal")
        self.tweet_preview.delete("0.0", "end")
        preview = (f"作者: {tweet['display_name']} ({tweet['username']})\n"
                   f"时间: {tweet['time']}\n\n"
                   f"{tweet['text']}")
        self.tweet_preview.insert("0.0", preview)
        self.tweet_preview.configure(state="disabled")
        self._set_status(f"已选中 {tweet['username']} 的推文")

    # ==========================================================================
    # AI 生成
    # ==========================================================================
    def _get_active_prompt_template(self):
        """返回当前编辑框中的 Prompt 模板（允许用户临时修改）"""
        return self.prompt_editor.get("0.0", "end").strip()

    def _set_generating(self, is_gen, action=""):
        state = "disabled" if is_gen else "normal"
        for btn, label in [
            (self.btn_reply,   "💬 回复"),
            (self.btn_retweet, "🔁 转推"),
            (self.btn_thread,  "🧵 Thread"),
        ]:
            btn.configure(state=state)
            if not is_gen:
                btn.configure(text=label, fg_color=COLORS["input"])
        self.refresh_btn.configure(state=state)

        if is_gen:
            labels = {"reply": "💬 回复", "retweet": "🔁 转推", "thread": "🧵 Thread"}
            target = {"reply": self.btn_reply, "retweet": self.btn_retweet, "thread": self.btn_thread}.get(action)
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

        # 将 template 中的占位符替换
        prompt = template.format(
            tweet_content=self.selected_tweet["text"],
            author=f"{self.selected_tweet['display_name']} ({self.selected_tweet['username']})",
            language=self.language_mode,
        )

        def _run():
            try:
                result = self.ai_generator.generate(prompt)
                self.after(0, lambda: self._on_gen_success(result))
            except Exception as e:
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


# ==============================================================================
# 7. 程序入口
# ==============================================================================
if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    app = AppGUI()
    app.mainloop()
