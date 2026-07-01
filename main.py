"""X28 - X 平台内容运营辅助工具入口。

第二阶段重构后，业务逻辑已拆分到 x28 包:
  - x28.config   配色 / 日志 / 代理修复 / .env
  - x28.utils    辅助函数 / 重试 / 安全模板
  - x28.core     数据模型 / 持久化 / 抓取 / AI
  - x28.ui        CustomTkinter 主界面

运行:  python main.py
"""

import os
import sys
import logging

# 导入 x28 包即触发: fix_proxy_env + load_dotenv + setup_logging
import x28  # noqa: F401  (副作用: 初始化日志与代理)
from x28.ui import AppGUI

log = logging.getLogger("x28.main")


def ensure_runtime_dirs() -> None:
    """确保运行时数据/日志目录存在。"""
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)


def main() -> int:
    ensure_runtime_dirs()
    log.info("X28 启动 (v%s)", x28.__version__)
    try:
        app = AppGUI()
        app.mainloop()
    except Exception as e:  # 顶层兜底，避免无堆栈的静默崩溃
        log.exception("X28 运行异常退出: %s", e)
        try:
            from tkinter import messagebox
            messagebox.showerror("X28 启动错误", f"{e}\n\n详见 logs/x28.log")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
