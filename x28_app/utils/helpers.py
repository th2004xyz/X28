"""通用辅助函数、重试装饰器与安全模板替换。

注意:
  - safe_format 用于 Prompt 模板替换，仅替换已知占位符，
    避免用户推文内容中出现的 `{...}` 触发 KeyError。
  - retry 装饰器用于抓取层，提供指数退避重试。
"""

import re
import html
import time
import functools
import logging
from datetime import datetime
from typing import Callable, Type

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("x28.utils")


# ------------------------------------------------------------------------------
# HTML / 文本清洗
# ------------------------------------------------------------------------------
_TAG_RE = re.compile("<.*?>", re.DOTALL)


def clean_html(raw_html: str) -> str:
    """剥离 HTML 标签并反转义实体，返回纯文本。"""
    if not raw_html:
        return ""
    text = re.sub(_TAG_RE, "", raw_html)
    return html.unescape(text).strip()


def parse_k_notation(val_str) -> int:
    """解析 '1.2k' / '3M' / '1234' 等数字字符串为整数。失败返回 0。"""
    val_str = str(val_str).lower().strip()
    try:
        if "k" in val_str:
            return int(float(val_str.replace("k", "")) * 1000)
        if "m" in val_str:
            return int(float(val_str.replace("m", "")) * 1_000_000)
        return int(val_str)
    except (ValueError, TypeError):
        return 0


def extract_stats(raw_html: str):
    """从 Nitter RSS description HTML 中提取 likes / retweets 计数。"""
    likes, retweets = 0, 0
    m = re.search(r"Likes?:\s*([\d\.\w]+)", raw_html, re.IGNORECASE)
    if m:
        likes = parse_k_notation(m.group(1))
    m = re.search(r"Re-?tweets?:\s*([\d\.\w]+)", raw_html, re.IGNORECASE)
    if m:
        retweets = parse_k_notation(m.group(1))
    return likes, retweets


def format_pubdate(raw_str: str) -> str:
    """尝试多种时间格式，返回友好的本地时间字符串。"""
    if not raw_str:
        return "未知时间"
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw_str.strip()[:31], fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return raw_str[:16]


# ------------------------------------------------------------------------------
# 头像生成（字母占位）
# ------------------------------------------------------------------------------
_AVATAR_CACHE: dict = {}


def generate_letter_avatar(letter: str, size=(42, 42),
                           bg_color="#e94560", fg_color="#f0f0f2") -> Image.Image:
    """生成圆形字母头像。同字母结果缓存复用，避免重复创建。"""
    key = (letter, size, bg_color, fg_color)
    cached = _AVATAR_CACHE.get(key)
    if cached is not None:
        return cached

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size[0] - 1, size[1] - 1], fill=bg_color)
    letter = (letter.upper()[:1] if letter else "X")
    try:
        font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), letter, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size[0] - w) / 2, (size[1] - h) / 2 - 1),
                  letter, fill=fg_color, font=font)
    except Exception:  # pragma: no cover - 极端环境下字体加载失败
        draw.text((14, 12), letter, fill=fg_color)

    _AVATAR_CACHE[key] = img
    return img


# ------------------------------------------------------------------------------
# 安全模板替换
# ------------------------------------------------------------------------------
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def safe_format(template: str, **kwargs) -> str:
    """安全替换 {placeholder}，仅替换 kwargs 中已知的键。

    与 str.format 不同，模板或用户内容中出现的未知名占位符会被原样保留，
    不会抛出 KeyError。这修复了「用户推文含 {xxx} 时 Prompt 渲染崩溃」的 Bug。
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in kwargs:
            return str(kwargs[key])
        return match.group(0)  # 未知占位符原样保留
    return _PLACEHOLDER_RE.sub(_replace, template)


# ------------------------------------------------------------------------------
# 重试装饰器（指数退避）
# ------------------------------------------------------------------------------
def retry(times: int = 3, delay: float = 1.5, backoff: float = 2.0,
          exceptions: tuple = (Exception,)) -> Callable:
    """指数退避重试装饰器。

    Args:
        times:     最大尝试次数（含首次）
        delay:     首次失败后等待秒数
        backoff:   每次重试等待时长的倍数
        exceptions: 触发重试的异常类型
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if attempt >= times:
                        log.warning("%s 重试 %d 次后仍失败: %s",
                                    func.__name__, attempt, e)
                        raise
                    log.info("%s 第 %d/%d 次失败: %s，%.1fs 后重试…",
                             func.__name__, attempt, times, e, wait)
                    time.sleep(wait)
                    wait *= backoff
        return wrapper
    return decorator
