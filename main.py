"""X28 - X 平台内容运营辅助工具入口。

第二阶段重构后，业务逻辑已拆分到 x28_app 包:
  - x28_app.config   配色 / 日志 / 代理修复 / .env
  - x28_app.utils    辅助函数 / 重试 / 安全模板 / keyring 凭证
  - x28_app.core     数据模型 / 持久化 / 抓取 / AI
  - x28_app.ui        CustomTkinter 主界面 / 配置向导

运行:  python main.py
"""

import os
import sys
import logging

# 导入 x28_app 包即触发: fix_proxy_env + load_dotenv + setup_logging
import x28_app  # noqa: F401  (副作用: 初始化日志与代理)
from x28_app.ui import AppGUI, ConfigWizard, should_show_wizard

log = logging.getLogger("x28.main")


def ensure_runtime_dirs() -> None:
    """确保运行时数据/日志目录存在。"""
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)


def maybe_run_wizard() -> bool:
    """首次启动或 Key 缺失时弹出配置向导。

    Returns:
        True 表示可以继续启动主界面；
        False 表示用户取消，应退出程序。
    """
    if not should_show_wizard():
        return True

    log.info("检测到 API Key 未配置，启动配置向导…")
    wizard = ConfigWizard()
    wizard.wait_window()
    return wizard.result


def main() -> int:
    ensure_runtime_dirs()
    log.info("X28 启动 (v%s)", x28_app.__version__)

    try:
        # 首次启动 / Key 缺失 → 引导配置
        if not maybe_run_wizard():
            log.info("用户取消配置向导，退出。")
            return 0

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
