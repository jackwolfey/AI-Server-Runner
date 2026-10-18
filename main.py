"""AI Server Runner —— 启动入口。

运行：python main.py
依赖：PySide6、gpu-smi（GPU 监控）
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from server_gui.constants import STATE_FILENAME, program_dir  # noqa: E402
from server_gui.main_window import MainWindow  # noqa: E402
from server_gui.theme import apply_theme, normalize_theme  # noqa: E402

APP_ICON = "app_icon.ico"


def _resource_path(name):
    """只读资源路径。

    PyInstaller 打包后资源随 datas 解压到 _MEIPASS 临时目录；
    源码运行时资源与 main.py 同目录。
    """
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(__file__))
    return os.path.join(base, name)


def _saved_theme():
    """从会话状态文件读取上次选择的主题；缺省 / 文件无效时返回 None。"""
    path = os.path.join(program_dir(), STATE_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get("theme") if isinstance(data, dict) else None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Server Runner")
    app.setOrganizationName("AI Server Runner")
    icon = QIcon(_resource_path(APP_ICON))
    if not icon.isNull():
        app.setWindowIcon(icon)  # 窗口 / 任务栏 / 关于对话框统一使用
    apply_theme(app, normalize_theme(_saved_theme()))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
