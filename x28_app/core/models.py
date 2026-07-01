"""数据模型: 用 dataclass 规范推文数据结构。

替代原始的裸 dict，提供:
  - 字段类型提示与默认值
  - 兼容 dict 的构造方式 (from_dict)
  - 序列化为 dict (to_dict)
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class Tweet:
    """标准化推文数据结构。

    Attributes:
        username:     @用户名 (含 @)
        display_name: 显示名称
        text:         推文纯文本
        time:         友好化后的时间字符串
        likes:        点赞数
        retweets:     转推数
        avatar_url:   头像 URL (Nitter 通常为空，回退到字母头像)
    """
    username: str = ""
    display_name: str = ""
    text: str = ""
    time: str = "未知时间"
    likes: int = 0
    retweets: int = 0
    avatar_url: str = ""

    # ------------------------------------------------------------------ 兼容层
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Tweet":
        """从原始 dict 构造 Tweet，缺字段使用默认值。"""
        return cls(
            username=d.get("username", ""),
            display_name=d.get("display_name", ""),
            text=d.get("text", ""),
            time=d.get("time", "未知时间"),
            likes=int(d.get("likes", 0) or 0),
            retweets=int(d.get("retweets", 0) or 0),
            avatar_url=d.get("avatar_url", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化回 dict，便于 JSON 持久化或与旧代码兼容。"""
        return asdict(self)

    # 兼容旧的 dict 下标访问（便于渐进迁移，避免遗漏处崩溃）
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
