"""敏感凭证安全存储层。

优先使用系统 keyring（Windows Credential Manager / macOS Keychain /
Linux Secret Service），失败时回退到 .env 环境变量（保持向后兼容）。

读取顺序:
  1. keyring 中的 X28/<key>
  2. os.getenv(key)  ← 旧 .env 配置仍然有效

写入:
  set_secret(key, value)
    • keyring 可用 → 写入 keyring
    • keyring 不可用 → 追加/更新到项目根 .env

这样既保护了新用户的 Key 安全，又不破坏老用户的 .env 工作流。
"""

import os
import logging
from typing import Optional

try:
    import keyring  # type: ignore
    _HAS_KEYRING = True
except Exception:  # pragma: no cover - keyring 未安装或后端不可用
    _HAS_KEYRING = False

log = logging.getLogger("x28.secrets")

# keyring 服务名（统一命名空间，便于在系统凭据管理器中识别）
_SERVICE_NAME = "X28"

# 已知敏感 Key 白名单（仅这些会被写入 keyring）
SENSITIVE_KEYS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "X_BEARER_TOKEN",
)


def is_keyring_available() -> bool:
    """keyring 后端是否可用（不抛异常）。"""
    if not _HAS_KEYRING:
        return False
    try:
        # 探测：能否获取当前用户名（不写入）
        keyring.get_password(_SERVICE_NAME, "__x28_probe__")
        return True
    except Exception as e:
        log.debug("keyring 后端不可用，回退到 .env: %s", e)
        return False


def get_secret(key: str, default: str = "") -> str:
    """读取敏感凭证: keyring 优先，回退到环境变量。"""
    if _HAS_KEYRING:
        try:
            val = keyring.get_password(_SERVICE_NAME, key)
            if val:
                return val
        except Exception as e:
            log.debug("keyring 读取 %s 失败: %s", key, e)
    # 回退: 环境变量（.env 已在 config.py 导入时加载）
    return os.getenv(key, default)


def set_secret(key: str, value: str) -> bool:
    """写入敏感凭证。

    Returns:
        True 表示已写入 keyring；False 表示回退到了 .env。
    """
    if key not in SENSITIVE_KEYS:
        log.warning("拒绝写入非白名单 Key: %s", key)
        return False

    value = (value or "").strip()
    if not value:
        delete_secret(key)
        return True

    if is_keyring_available():
        try:
            keyring.set_password(_SERVICE_NAME, key, value)
            log.info("凭证 %s 已写入系统 keyring", key)
            return True
        except Exception as e:
            log.warning("keyring 写入 %s 失败，回退到 .env: %s", key, e)

    # 回退: 写入 .env
    _write_env(key, value)
    log.info("凭证 %s 已写入 .env", key)
    return False


def delete_secret(key: str) -> None:
    """删除凭证（keyring + .env 都清）。"""
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            pass
    _remove_env_key(key)


def has_any_credentials() -> dict:
    """检查各类必要凭证的配置状态，供配置向导判断是否首次启动。

    Returns:
        {"ai_key": bool, "x_token": bool, "using_keyring": bool}
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
    if provider == "openai":
        ai_key_name = "OPENAI_API_KEY"
    elif provider == "anthropic":
        ai_key_name = "ANTHROPIC_API_KEY"
    else:
        ai_key_name = "GEMINI_API_KEY"

    ai_key = get_secret(ai_key_name, "")
    x_token = get_secret("X_BEARER_TOKEN", "")

    return {
        "ai_key": bool(ai_key.strip()),
        "x_token": bool(x_token.strip()),
        "using_keyring": is_keyring_available(),
        "provider": provider,
    }


# ------------------------------------------------------------------------------
# .env 回退实现
# ------------------------------------------------------------------------------
def _env_path() -> str:
    """项目根 .env 路径（基于本文件位置向上查找）。"""
    # utils/secrets.py → 上两级 = 项目根
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".env")


def _read_env_lines() -> list:
    path = _env_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception as e:
        log.warning("读取 .env 失败: %s", e)
        return []


def _write_env_lines(lines: list) -> None:
    try:
        path = _env_path()
        # 末尾保留换行
        content = "\n".join(lines).rstrip() + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        # 同步到当前进程环境变量，避免重启才生效
        os.environ.pop("__x28_env_reload__", None)
    except Exception as e:
        log.error("写入 .env 失败: %s", e)


def _write_env(key: str, value: str) -> None:
    """在 .env 中写入或更新一行 KEY=VALUE。"""
    lines = _read_env_lines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                lines[i] = f"{key}={value}"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}")
    _write_env_lines(lines)
    # 同步到当前进程
    os.environ[key] = value


def _remove_env_key(key: str) -> None:
    lines = _read_env_lines()
    new_lines = [line for line in lines
                 if line.strip().split("=", 1)[0].strip() != key
                 or not line.strip()
                 or line.strip().startswith("#")]
    _write_env_lines(new_lines)
    os.environ.pop(key, None)
