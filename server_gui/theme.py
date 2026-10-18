"""主题：Fusion 风格 + 调色板 + 全局 QSS（深色 / 浅色两套，默认浅色）。"""

import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPolygonF
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

# 主题标识（会话状态文件中 "theme" 字段的合法取值）
THEME_DARK = "dark"
THEME_LIGHT = "light"

_THEME_NAMES = {THEME_DARK: "深色", THEME_LIGHT: "浅色"}


def normalize_theme(value):
    """把任意值归一化为合法主题名；无效 / 缺省（首次运行）时回退浅色。"""
    return value if value in (THEME_DARK, THEME_LIGHT) else THEME_LIGHT


DARK_QSS = """
* { outline: none; }

QWidget {
    color: #d8dee9;
    font-size: 9pt;
}

QMainWindow, QDialog {
    background: #1e222a;
}

/* ---------- 分组卡片 ---------- */
QGroupBox {
    background: #242832;
    border: 1px solid #323947;
    border-radius: 8px;
    margin-top: 13px;
    padding: 8px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #7ea6ff;
    background: transparent;
}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QDateTimeEdit {
    background: #1a1d24;
    border: 1px solid #363d4c;
    border-radius: 6px;
    padding: 4px 8px;
    color: #d8dee9;
    selection-background-color: #3d5a99;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #4f7cff;
    background: #1c2029;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {
    color: #6a7181;
    background: #22252d;
    border-color: #2c313d;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: url(__ARROW__);
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background: #242832;
    border: 1px solid #3a4150;
    border-radius: 6px;
    selection-background-color: #3d5a99;
    selection-color: #ffffff;
    outline: none;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #333a48, stop:1 #2b3140);
    border: 1px solid #3d4657;
    border-radius: 6px;
    padding: 5px 14px;
    color: #d8dee9;
}
QPushButton:hover {
    background: #3b445a;
    border-color: #4d5a75;
}
QPushButton:pressed {
    background: #2f3646;
}
QPushButton:disabled {
    color: #5d6472;
    background: #272b34;
    border-color: #303542;
}

QPushButton[accent="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4f7cff, stop:1 #3a5fd9);
    border: 1px solid #5a86ff;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[accent="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5f8bff, stop:1 #4468e0);
    border-color: #7298ff;
}
QPushButton[accent="true"]:pressed {
    background: #3a5fd9;
}
QPushButton[accent="true"]:disabled {
    background: #2c3350;
    border-color: #35406b;
    color: #6a7181;
}

QPushButton[danger="true"] {
    background: #3a2730;
    border: 1px solid #6e2f42;
    color: #ff8fa3;
}
QPushButton[danger="true"]:hover {
    background: #4a2f3c;
    border-color: #8a3a52;
}
QPushButton[danger="true"]:pressed {
    background: #33222b;
}
QPushButton[danger="true"]:disabled {
    color: #5d6472;
    background: #272b34;
    border-color: #303542;
}

/* 自定义参数行内的方形小删除按钮。
   全局 QPushButton 的 padding 是 5px 14px（左右共 28px），套在 26px 宽的
   小按钮上会把内容区挤成负值，导致「✕」被整体裁剪而看不见；这里清零内边距。 */
QPushButton#rowDeleteBtn {
    padding: 0;
}

/* ---------- 复选框 ---------- */
QCheckBox {
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #3d4657;
    border-radius: 4px;
    background: #1a1d24;
}
QCheckBox::indicator:hover {
    border-color: #4f7cff;
}
QCheckBox::indicator:checked {
    background: #4f7cff;
    border-color: #5a86ff;
}
QCheckBox:disabled {
    color: #6a7181;
}

/* ---------- 进度条 ---------- */
QProgressBar {
    background: #1a1d24;
    border: 1px solid #363d4c;
    border-radius: 7px;
    height: 15px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b63d8, stop:1 #5f8bff);
    margin: 1px;
}

/* ---------- 树 / 表 ---------- */
QTreeWidget, QTreeView, QListWidget, QTableWidget {
    background: #1e222b;
    alternate-background-color: #232733;
    border: 1px solid #323947;
    border-radius: 6px;
    padding: 2px;
    outline: none;
}
QTreeWidget::item, QTreeView::item {
    height: 24px;
    border: none;
}
QTreeWidget::item:hover, QTreeView::item:hover {
    background: #2a3040;
}
QTreeWidget::item:selected, QTreeView::item:selected {
    background: #3d5a99;
    color: #ffffff;
}
QHeaderView::section {
    background: #282d3a;
    color: #9fb0cc;
    border: none;
    border-right: 1px solid #333947;
    border-bottom: 1px solid #333947;
    padding: 5px 8px;
    font-weight: 600;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3a4152;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #4a5468;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #3a4152;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #4a5468;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}

/* ---------- 分割器 ---------- */
QSplitter::handle {
    background: #1e222a;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QSplitter::handle:hover {
    background: #3d5a99;
}

/* ---------- 菜单 / 提示 ---------- */
QMenu {
    background: #242832;
    border: 1px solid #3a4150;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 24px 5px 16px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #3d5a99;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #363d4c;
    margin: 4px 8px;
}

QToolTip {
    background: #11141a;
    color: #d8dee9;
    border: 1px solid #4f7cff;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 9pt;
}

/* ---------- 日志视图 ---------- */
QPlainTextEdit#logView {
    background: #16181d;
    border: 1px solid #2c313d;
    border-radius: 6px;
    color: #d4d4d4;
    font-family: "Consolas", "Courier New", monospace;
}

/* ---------- 对话框按钮 ---------- */
QMessageBox {
    background: #242832;
}
QMessageBox QLabel {
    color: #d8dee9;
    background: transparent;
}
"""

LIGHT_QSS = """
* { outline: none; }

QWidget {
    color: #2a2f3a;
    font-size: 9pt;
}

QMainWindow, QDialog {
    background: #f5f6f8;
}

/* ---------- 分组卡片 ---------- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #d9dee7;
    border-radius: 8px;
    margin-top: 13px;
    padding: 8px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #3a6fd8;
    background: transparent;
}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QDateTimeEdit {
    background: #ffffff;
    border: 1px solid #c9d0dc;
    border-radius: 6px;
    padding: 4px 8px;
    color: #2a2f3a;
    selection-background-color: #3d5a99;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #4f7cff;
    background: #ffffff;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {
    color: #a8b0bd;
    background: #f0f2f6;
    border-color: #dfe3ea;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: url(__ARROW__);
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #c9d0dc;
    border-radius: 6px;
    selection-background-color: #3d5a99;
    selection-color: #ffffff;
    outline: none;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #ffffff, stop:1 #e9ecf2);
    border: 1px solid #c9d0dc;
    border-radius: 6px;
    padding: 5px 14px;
    color: #2a2f3a;
}
QPushButton:hover {
    background: #eef1f6;
    border-color: #a8b4c6;
}
QPushButton:pressed {
    background: #e2e6ee;
}
QPushButton:disabled {
    color: #a8b0bd;
    background: #f0f2f6;
    border-color: #dfe3ea;
}

QPushButton[accent="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4f7cff, stop:1 #3a5fd9);
    border: 1px solid #5a86ff;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[accent="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5f8bff, stop:1 #4468e0);
    border-color: #7298ff;
}
QPushButton[accent="true"]:pressed {
    background: #3a5fd9;
}
QPushButton[accent="true"]:disabled {
    background: #dfe5f5;
    border-color: #c5cff0;
    color: #9aa6c8;
}

QPushButton[danger="true"] {
    background: #fdeef1;
    border: 1px solid #e3a7b4;
    color: #c2255c;
}
QPushButton[danger="true"]:hover {
    background: #fadbe1;
    border-color: #d98a9c;
}
QPushButton[danger="true"]:pressed {
    background: #f9d0d8;
}
QPushButton[danger="true"]:disabled {
    color: #b8bec9;
    background: #f0f2f6;
    border-color: #dfe3ea;
}

/* 自定义参数行内的方形小删除按钮（清零内边距，避免「✕」被裁剪）。 */
QPushButton#rowDeleteBtn {
    padding: 0;
}

/* ---------- 复选框 ---------- */
QCheckBox {
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #c9d0dc;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #4f7cff;
}
QCheckBox::indicator:checked {
    background: #4f7cff;
    border-color: #5a86ff;
}
QCheckBox:disabled {
    color: #a8b0bd;
}

/* ---------- 进度条 ---------- */
QProgressBar {
    background: #eceff4;
    border: 1px solid #c9d0dc;
    border-radius: 7px;
    height: 15px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b63d8, stop:1 #5f8bff);
    margin: 1px;
}

/* ---------- 树 / 表 ---------- */
QTreeWidget, QTreeView, QListWidget, QTableWidget {
    background: #ffffff;
    alternate-background-color: #f3f5f9;
    border: 1px solid #d9dee7;
    border-radius: 6px;
    padding: 2px;
    outline: none;
}
QTreeWidget::item, QTreeView::item {
    height: 24px;
    border: none;
}
QTreeWidget::item:hover, QTreeView::item:hover {
    background: #e8edf6;
}
QTreeWidget::item:selected, QTreeView::item:selected {
    background: #3d5a99;
    color: #ffffff;
}
QHeaderView::section {
    background: #eef1f6;
    color: #5a6a85;
    border: none;
    border-right: 1px solid #dfe3ea;
    border-bottom: 1px solid #dfe3ea;
    padding: 5px 8px;
    font-weight: 600;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c3cad6;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #a8b2c2;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c3cad6;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #a8b2c2;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}

/* ---------- 分割器 ---------- */
QSplitter::handle {
    background: #e7eaf0;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QSplitter::handle:hover {
    background: #3d5a99;
}

/* ---------- 菜单 / 提示 ---------- */
QMenu {
    background: #ffffff;
    border: 1px solid #c9d0dc;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 24px 5px 16px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #3d5a99;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #dfe3ea;
    margin: 4px 8px;
}

QToolTip {
    background: #ffffff;
    color: #2a2f3a;
    border: 1px solid #4f7cff;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 9pt;
}

/* ---------- 日志视图 ---------- */
QPlainTextEdit#logView {
    background: #fbfcfd;
    border: 1px solid #dfe3ea;
    border-radius: 6px;
    color: #2a2f3a;
    font-family: "Consolas", "Courier New", monospace;
}

/* ---------- 对话框按钮 ---------- */
QMessageBox {
    background: #ffffff;
}
QMessageBox QLabel {
    color: #2a2f3a;
    background: transparent;
}
"""


_ARROW_DIR = os.path.join(tempfile.gettempdir(), "ai_server_runner_assets")


def _arrow_png(color_hex):
    """生成下拉箭头小三角 PNG 并返回本地路径。

    QSS 一旦自定义 QComboBox 样式，默认箭头就不再绘制，而 url() 只认
    真实文件路径（不支持 data: URL），因此这里用 QImage 运行时画一个
    10x6 的倒三角缓存到临时目录。生成失败时返回空串（仅缺箭头）。
    """
    try:
        os.makedirs(_ARROW_DIR, exist_ok=True)
        path = os.path.join(_ARROW_DIR, f"arrow_{color_hex.lstrip('#')}.png")
        if not os.path.exists(path):
            img = QImage(10, 6, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color_hex))
            painter.drawPolygon(QPolygonF([
                QPointF(0.5, 0.5), QPointF(9.5, 0.5), QPointF(5.0, 5.5)]))
            painter.end()
            img.save(path, "PNG")
        return path.replace("\\", "/")  # QSS url() 中反斜杠会被吞掉
    except Exception:
        return ""


def _dark_palette():
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#1e222a"))
    pal.setColor(QPalette.WindowText, QColor("#d8dee9"))
    pal.setColor(QPalette.Base, QColor("#1a1d24"))
    pal.setColor(QPalette.AlternateBase, QColor("#22262f"))
    pal.setColor(QPalette.Text, QColor("#d8dee9"))
    pal.setColor(QPalette.Button, QColor("#2b3140"))
    pal.setColor(QPalette.ButtonText, QColor("#d8dee9"))
    pal.setColor(QPalette.Highlight, QColor("#3d5a99"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#11141a"))
    pal.setColor(QPalette.ToolTipText, QColor("#d8dee9"))
    pal.setColor(QPalette.PlaceholderText, QColor("#6a7181"))
    pal.setColor(QPalette.Light, QColor("#3a4152"))
    pal.setColor(QPalette.Midlight, QColor("#323947"))
    pal.setColor(QPalette.Dark, QColor("#14161b"))
    pal.setColor(QPalette.Mid, QColor("#282d3a"))
    pal.setColor(QPalette.Shadow, QColor("#0d0f13"))
    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.WindowText, QColor("#6a7181"))
        pal.setColor(group, QPalette.Text, QColor("#6a7181"))
        pal.setColor(group, QPalette.ButtonText, QColor("#6a7181"))
        pal.setColor(group, QPalette.Base, QColor("#22252d"))
        pal.setColor(group, QPalette.Button, QColor("#272b34"))
    return pal


def _light_palette():
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#f5f6f8"))
    pal.setColor(QPalette.WindowText, QColor("#2a2f3a"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.AlternateBase, QColor("#f3f5f9"))
    pal.setColor(QPalette.Text, QColor("#2a2f3a"))
    pal.setColor(QPalette.Button, QColor("#eef1f6"))
    pal.setColor(QPalette.ButtonText, QColor("#2a2f3a"))
    pal.setColor(QPalette.Highlight, QColor("#3d5a99"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipText, QColor("#2a2f3a"))
    pal.setColor(QPalette.PlaceholderText, QColor("#98a0ad"))
    pal.setColor(QPalette.Light, QColor("#ffffff"))
    pal.setColor(QPalette.Midlight, QColor("#e9ecf2"))
    pal.setColor(QPalette.Dark, QColor("#c9d0dc"))
    pal.setColor(QPalette.Mid, QColor("#dfe3ea"))
    pal.setColor(QPalette.Shadow, QColor("#a8b0bd"))
    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.WindowText, QColor("#a8b0bd"))
        pal.setColor(group, QPalette.Text, QColor("#a8b0bd"))
        pal.setColor(group, QPalette.ButtonText, QColor("#a8b0bd"))
        pal.setColor(group, QPalette.Base, QColor("#f0f2f6"))
        pal.setColor(group, QPalette.Button, QColor("#eceef2"))
    return pal


def apply_theme(app: QApplication, theme=THEME_LIGHT):
    """套用 Fusion 风格 + 指定主题（深色 / 浅色）的调色板与全局 QSS。"""
    theme = normalize_theme(theme)
    app.setStyle("Fusion")
    app.setPalette(_dark_palette() if theme == THEME_DARK else _light_palette())
    app.setFont(QFont("Microsoft YaHei UI", 9))
    qss = DARK_QSS if theme == THEME_DARK else LIGHT_QSS
    arrow = _arrow_png("#d8dee9" if theme == THEME_DARK else "#5a6a85")
    app.setStyleSheet(qss.replace("__ARROW__", arrow))


class ThemeDialog(QDialog):
    """主题选择对话框：主题下拉框（默认选中当前主题）+ 确认 / 取消。"""

    def __init__(self, parent, current=THEME_LIGHT):
        super().__init__(parent)
        self.setWindowTitle("主题")
        self.setMinimumWidth(280)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("主题："))
        self.combo = QComboBox()
        self.combo.addItem(_THEME_NAMES[THEME_DARK], THEME_DARK)
        self.combo.addItem(_THEME_NAMES[THEME_LIGHT], THEME_LIGHT)
        idx = self.combo.findData(normalize_theme(current))
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        row.addWidget(self.combo, 1)
        lay.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        ok_btn = QPushButton("确认")
        ok_btn.setProperty("accent", True)
        ok_btn.clicked.connect(self.accept)
        btns.addWidget(ok_btn)
        lay.addLayout(btns)

    def selected_theme(self):
        """返回下拉框当前选中的主题标识。"""
        return self.combo.currentData()
