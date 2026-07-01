"""全局配置: 主题配色、日志系统、代理修复与 .env 加载。

导入本模块即自动执行启动前置初始化:
  1. fix_proxy_env()   修复 Windows 下 [scheme://host]:port 异常格式
  2. load_dotenv()     加载项目根 .env
  3. setup_logging()   配置控制台 + 轮转文件日志
"""

import os
import re
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv


# ------------------------------------------------------------------------------
# 日志系统
# ------------------------------------------------------------------------------
_LOG_DIR = "logs"


def setup_logging() -> logging.Logger:
    """配置 x28 命名空间日志: 控制台(INFO) + 轮转文件(DEBUG)。幂等。"""
    os.makedirs(_LOG_DIR, exist_ok=True)
    logger = logging.getLogger("x28")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:  # 避免重复添加 handler
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 轮转文件: 单文件 1MB，保留 3 份
    fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, "x28.log"),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.propagate = False
    return logger


# ------------------------------------------------------------------------------
# 代理修复
# ------------------------------------------------------------------------------
def fix_proxy_env() -> None:
    """检测并修复 Windows 下代理环境变量中的方括号格式问题。

    例如将 '[http://127.0.0.1]:7897' 修复为 'http://127.0.0.1:7897'，
    防止 requests/urllib 解析挂起。
    """
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        val = os.environ.get(key, "")
        if val:
            fixed = re.sub(r"^\[(.+)\]:(\d+)$", r"\1:\2", val.strip())
            if fixed != val:
                log.info("代理修复 %s: '%s' -> '%s'", key, val, fixed)
                os.environ[key] = fixed


# ------------------------------------------------------------------------------
# 启动前置初始化（导入即执行）
# ------------------------------------------------------------------------------
log = setup_logging()
fix_proxy_env()
load_dotenv()


# ------------------------------------------------------------------------------
# 主题配色系统（曜石黑高级质感）
# ------------------------------------------------------------------------------
COLORS = {
    "bg":            "#0c0c0e",   # 主背景：暗夜曜石黑
    "panel":         "#16161a",   # 侧栏/面板背景：深炭灰
    "card":          "#1e1e23",   # 推文卡片背景
    "card_hover":    "#27272e",   # 卡片悬停色
    "card_active":   "#1f1f2c",   # 卡片选中背景
    "input":         "#222228",   # 输入框/文本区背景
    "border":        "#2d2d36",   # 精致 1px 边框
    "accent":        "#e94560",   # 主高亮色（珊瑚红）
    "accent_hover":  "#c83650",   # 高亮悬停色
    "accent_dim":    "#7a1e30",   # 低饱和强调（禁用态）
    "text_primary":  "#f0f0f2",   # 主文字：纯白
    "text_secondary":"#8b8b9a",   # 次级文字：中灰
    "text_muted":    "#52525e",   # 辅助文字：暗灰
    "success":       "#2ecc71",   # 成功状态绿
    "warning":       "#f39c12",   # 警告状态橙
}
