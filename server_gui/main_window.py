"""主窗口：布局、预设管理、命令构造、会话持久化、退出清理。"""

import json
import os
import re
import threading
import webbrowser
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__
from .constants import (BASE_TITLE, DEFAULT_COMFY_ARGS, DEFAULT_COMFY_MAIN,
                        DEFAULT_COMFY_PYTHON, DEFAULT_COMFY_PORT,
                        DEFAULT_EXE, DEFAULT_EXTRA_ARGS, DEFAULT_LLAMA_PORT,
                        DEFAULT_MODEL, DEFAULT_WORKDIR, PRESET_FILENAME,
                        STATE_FILENAME, program_dir)
from .gpu_monitor import GpuMonitorBar
from .model_library import ModelLibraryDialog
from .param_editor import ParamEditorDialog
from .presets import PresetStore
from .process_panel import ProcessPanel
from .theme import THEME_LIGHT, ThemeDialog, apply_theme, normalize_theme
from .winprocess import win_cmdline_split

# 主窗口最小尺寸（与原版一致）
MIN_W, MIN_H = 940, 660
DEFAULT_W, DEFAULT_H = 1120, 820


class MainWindow(QMainWindow):

    _close_finished = Signal()  # 退出清理线程完成（跨线程触发）

    def __init__(self):
        super().__init__()
        self.setWindowTitle(BASE_TITLE)
        self.resize(DEFAULT_W, DEFAULT_H)
        self.setMinimumSize(MIN_W, MIN_H)

        self._closing = False
        self._suppress_select = False
        self._current_preset_path = None
        self._current_preset_index = None
        self._input_snapshot = None
        self._theme = THEME_LIGHT  # 首次运行默认浅色，之后以状态文件为准

        self.presets = PresetStore(None)
        self.panels = []

        # 会话状态文件：跟随程序所在目录（打包成 exe 后为 exe 所在目录）；
        # 若不存在则尝试旧版 tkinter 程序的位置
        base = program_dir()
        self._state_path = os.path.join(base, STATE_FILENAME)
        self._legacy_state_path = os.path.join(
            os.path.dirname(base), STATE_FILENAME)

        self._build_ui()

        # 工作目录变更 → 防抖 600ms 后重载预设
        self._workdir_timer = QTimer(self)
        self._workdir_timer.setSingleShot(True)
        self._workdir_timer.setInterval(600)
        self._workdir_timer.timeout.connect(self._reload_presets)
        self.workdir_edit.textChanged.connect(self._workdir_timer.start)

        self._close_finished.connect(self._final_close)

        self._load_session()
        self._reload_presets()
        self._snapshot_inputs()
        self._update_title()

    # ================================================================== UI
    def _build_ui(self):
        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # 上下分割：上=配置区+GPU条，下=双日志
        self.vsplit = QSplitter(Qt.Vertical)
        root_lay.addWidget(self.vsplit)

        # ---------------- 上半部分：左输入 + GPU条 / 右预设 ----------------
        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(10, 8, 10, 2)
        top_lay.setSpacing(6)

        self.hsplit = QSplitter(Qt.Horizontal)
        top_lay.addWidget(self.hsplit, 1)

        self.hsplit.addWidget(self._build_left_config())
        self.hsplit.addWidget(self._build_right_presets())
        self.hsplit.setStretchFactor(0, 1)
        self.hsplit.setStretchFactor(1, 0)
        self.hsplit.setSizes([760, 340])

        # GPU 监控条
        self.gpu_bar = GpuMonitorBar()
        top_lay.addWidget(self.gpu_bar)

        self.vsplit.addWidget(top)

        # ---------------- 下半部分：双服务面板（各带按钮栏+日志） ----------------
        self.logs_split = QSplitter(Qt.Horizontal)
        self.llama_panel = ProcessPanel(
            self, name="llama-server",
            build_command=self._build_llama_command,
            page_url_fn=self._llama_page_url,
            ready_probe_fn=self._llama_probe,
            open_label="打开 WebUI", stop_grace=8)
        self.comfy_panel = ProcessPanel(
            self, name="ComfyUI",
            build_command=self._build_comfy_command,
            page_url_fn=self._comfy_page_url,
            ready_probe_fn=self._comfy_probe,
            open_label="打开 ComfyUI", stop_grace=15)
        self.logs_split.addWidget(self.llama_panel)
        self.logs_split.addWidget(self.comfy_panel)
        self.logs_split.setStretchFactor(0, 1)
        self.logs_split.setStretchFactor(1, 1)
        self.logs_split.setSizes([560, 560])
        self.panels = [self.llama_panel, self.comfy_panel]
        for pnl in self.panels:
            pnl.state_changed.connect(self._update_title)

        self.vsplit.addWidget(self.logs_split)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 2)
        self.vsplit.setSizes([520, 300])

    def _build_menu_bar(self):
        """菜单栏：设置（主题）/ 其他（关于）。"""
        mb = self.menuBar()

        settings_menu = mb.addMenu("设置")
        theme_action = settings_menu.addAction("主题")
        theme_action.triggered.connect(self._choose_theme)

        other_menu = mb.addMenu("其他")
        about_action = other_menu.addAction("关于")
        about_action.triggered.connect(self._show_about)

    def _choose_theme(self):
        """菜单：设置 → 主题。确认后立即应用并持久化到会话状态。"""
        dlg = ThemeDialog(self, current=self._theme)
        if dlg.exec() != QDialog.Accepted:
            return
        theme = normalize_theme(dlg.selected_theme())
        if theme == self._theme:
            return
        self._theme = theme
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)
        self._save_session()  # 立即持久化，重启后保持

    def _show_about(self):
        QMessageBox.about(
            self, f"关于 {BASE_TITLE}",
            f"<h3>AI Server Runner</h3>"
            f"<p>简介：llama-server / ComfyUI 图形控制面板，"
            f"提供双服务进程管理、日志查看、GPU 显存监控、"
            f"参数可视化编辑与预设配置管理。</p>"
            f"<p>作者：WindJ<br>版本：v{__version__}</p>")

    def _build_left_config(self):
        left = QWidget()
        outer = QVBoxLayout(left)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # ---------------- llama.cpp 设置面板 ----------------
        llama_set = QGroupBox("llama.cpp 设置")
        grid = QGridLayout(llama_set)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        # 工作目录
        lbl = QLabel("工作目录：")
        lbl.setToolTip("llama-server 运行目录，同时也是预设配置文件的保存位置。")
        grid.addWidget(lbl, 0, 0)
        self.workdir_edit = QLineEdit(DEFAULT_WORKDIR)
        grid.addWidget(self.workdir_edit, 0, 1)
        btn = self._browse_btn(grid, 0, 2, self.browse_workdir)

        # 可执行文件
        lbl = QLabel("程序：")
        lbl.setToolTip("llama-server 可执行文件；可为相对路径。")
        grid.addWidget(lbl, 1, 0)
        self.exe_edit = QLineEdit(DEFAULT_EXE)
        grid.addWidget(self.exe_edit, 1, 1)
        self._browse_btn(grid, 1, 2, self.browse_exe)

        # 模型文件
        lbl = QLabel("模型文件：")
        lbl.setToolTip("GGUF 模型文件完整路径。")
        grid.addWidget(lbl, 2, 0)
        self.model_edit = QLineEdit(DEFAULT_MODEL)
        grid.addWidget(self.model_edit, 2, 1)
        mbtns = QWidget()
        ml = QHBoxLayout(mbtns)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(4)
        mb = QPushButton("浏览…")
        mb.setFixedWidth(64)
        mb.clicked.connect(self.browse_model)
        ml.addWidget(mb)
        lib_btn = QPushButton("模型库")
        lib_btn.setFixedWidth(64)
        lib_btn.setToolTip("打开模型目录浏览器：扫描 .gguf、显示量化/上下文/层数、"
                           "预估显存，双击回填路径。")
        lib_btn.clicked.connect(self.open_model_library)
        ml.addWidget(lib_btn)
        grid.addWidget(mbtns, 2, 2)

        # 其它参数
        lbl = QLabel("其它参数：\n(每行一个)")
        lbl.setToolTip("每行一个参数。\n可点击「可视化编辑」用表单方式配置常用参数。")
        grid.addWidget(lbl, 3, 0, Qt.AlignTop)
        self.args_edit = QPlainTextEdit()
        self.args_edit.setFont(self._mono_font(10))
        self.args_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.args_edit.setPlainText(DEFAULT_EXTRA_ARGS)
        grid.addWidget(self.args_edit, 3, 1, 1, 2)
        grid.setRowStretch(3, 1)

        # 可视化编辑按钮行
        vis_row = QWidget()
        vl = QHBoxLayout(vis_row)
        vl.setContentsMargins(0, 0, 0, 0)
        vis_btn = QPushButton("⚙ 可视化编辑参数")
        vis_btn.setToolTip("用表单方式编辑「其它参数」中的每个参数，"
                           "自动同步回此文本框。")
        vis_btn.clicked.connect(self.open_param_editor)
        vl.addWidget(vis_btn)
        vl.addStretch(1)
        grid.addWidget(vis_row, 4, 0, 1, 3)

        outer.addWidget(llama_set, 1)  # 参数区吸收多余纵向空间

        # ComfyUI 设置
        comfy_set = QGroupBox("ComfyUI 设置")
        cl = QGridLayout(comfy_set)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setHorizontalSpacing(8)
        cl.setVerticalSpacing(6)
        cl.setColumnStretch(1, 1)

        lbl = QLabel("Python：")
        cl.addWidget(lbl, 0, 0)
        self.comfy_python_edit = QLineEdit(DEFAULT_COMFY_PYTHON)
        cl.addWidget(self.comfy_python_edit, 0, 1)
        self._browse_btn(cl, 0, 2, self.browse_comfy_python)

        lbl = QLabel("主程序：")
        cl.addWidget(lbl, 1, 0)
        self.comfy_main_edit = QLineEdit(DEFAULT_COMFY_MAIN)
        cl.addWidget(self.comfy_main_edit, 1, 1)
        self._browse_btn(cl, 1, 2, self.browse_comfy_main)

        lbl = QLabel("参数：")
        lbl.setToolTip("ComfyUI 启动参数，单行书写。")
        cl.addWidget(lbl, 2, 0)
        self.comfy_args_edit = QLineEdit(DEFAULT_COMFY_ARGS)
        cl.addWidget(self.comfy_args_edit, 2, 1, 1, 2)

        outer.addWidget(comfy_set)
        return left

    def _build_right_presets(self):
        right = QGroupBox("预设配置")
        right.setMinimumWidth(340)
        lay = QVBoxLayout(right)
        lay.setContentsMargins(10, 12, 10, 8)
        lay.setSpacing(6)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选："))
        self.preset_filter_edit = QLineEdit()
        self.preset_filter_edit.setClearButtonEnabled(True)
        self.preset_filter_edit.textChanged.connect(self._refresh_preset_list)
        filter_row.addWidget(self.preset_filter_edit, 1)
        lay.addLayout(filter_row)

        self.preset_tree = QTreeWidget()
        self.preset_tree.setColumnCount(2)
        self.preset_tree.setHeaderLabels(["名称", "模型文件"])
        self.preset_tree.setRootIsDecorated(False)
        self.preset_tree.setIndentation(0)
        self.preset_tree.setUniformRowHeights(True)
        self.preset_tree.setAlternatingRowColors(True)
        self.preset_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.preset_tree.setColumnWidth(0, 120)
        self.preset_tree.header().setStretchLastSection(True)
        self.preset_tree.itemSelectionChanged.connect(self._on_preset_select)
        self.preset_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preset_tree.customContextMenuRequested.connect(
            self._show_tree_menu)
        lay.addWidget(self.preset_tree, 1)

        # 快捷键（仅当树获得焦点时生效）
        for seq, fn in ((QKeySequence.Delete, self.delete_selected_preset),
                        (QKeySequence("Ctrl+Up"),
                         lambda: self.move_selected_preset(-1)),
                        (QKeySequence("Ctrl+Down"),
                         lambda: self.move_selected_preset(1))):
            sc = QShortcut(seq, self.preset_tree)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_save = QPushButton("保存")
        self.btn_save.setToolTip(
            "选中条目时询问是否覆盖该预设；选择否或未选中时另存为新预设。")
        self.btn_save.clicked.connect(self.save_preset)
        btn_reset = QPushButton("重置输入")
        btn_reset.clicked.connect(self.reset_inputs)
        btn_row.addWidget(self.btn_save, 1)
        btn_row.addWidget(btn_reset, 1)
        lay.addLayout(btn_row)

        self.preset_btns = (self.btn_save,)

        footer = QLabel(f"配置文件：{PRESET_FILENAME}（保存在工作目录中）")
        footer.setStyleSheet("color: #78818f; font-size: 8pt;")
        lay.addWidget(footer)
        return right

    # ------------------------------------------------------------- 小工具
    @staticmethod
    def _mono_font(size):
        from PySide6.QtGui import QFont
        return QFont("Consolas", size)

    def _browse_btn(self, grid, row, col, fn):
        btn = QPushButton("浏览…")
        btn.setFixedWidth(64)
        btn.clicked.connect(fn)
        grid.addWidget(btn, row, col)
        return btn

    # ------------------------------------------------------------- 文件选择
    def browse_workdir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择工作目录", self.workdir_edit.text() or ".")
        if path:
            self.workdir_edit.setText(os.path.normpath(path))

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 llama-server.exe",
            self.workdir_edit.text() or ".",
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.exe_edit.setText(os.path.normpath(path))

    def browse_model(self):
        init = os.path.dirname(self.model_edit.text()) \
            or self.workdir_edit.text() or "."
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 GGUF 模型", init,
            "GGUF 模型 (*.gguf);;所有文件 (*.*)")
        if path:
            self.model_edit.setText(os.path.normpath(path))

    def browse_comfy_python(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Python 解释器",
            os.path.dirname(self.comfy_python_edit.text()) or ".",
            "Python 解释器 (python*.exe);;所有文件 (*.*)")
        if path:
            self.comfy_python_edit.setText(os.path.normpath(path))

    def browse_comfy_main(self):
        init = os.path.dirname(self.comfy_main_edit.text()) or "."
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ComfyUI main.py", init,
            "Python 脚本 (*.py);;所有文件 (*.*)")
        if path:
            self.comfy_main_edit.setText(os.path.normpath(path))

    # ==================== 模型库 / 参数编辑器 入口 ====================
    def open_model_library(self):
        """打开模型目录浏览器。"""
        initial = os.path.dirname(self.model_edit.text()) or DEFAULT_WORKDIR
        ModelLibraryDialog(
            self,
            on_select=lambda p: self.model_edit.setText(p),
            initial_dir=initial,
            current_model=self.model_edit.text()).show()

    def open_param_editor(self):
        """打开可视化参数编辑器。"""
        ParamEditorDialog(self, args_text=self.args_edit).show()

    # ============================ 预设：加载 / 刷新 ============================
    def _reload_presets(self):
        workdir = self.workdir_edit.text().strip()
        path = None
        if workdir and os.path.isdir(workdir):
            path = os.path.join(workdir, PRESET_FILENAME)

        self.presets = PresetStore(path)
        self._current_preset_index = None
        self._set_presets_available(bool(path))
        self._refresh_preset_list()

        if path != self._current_preset_path:
            self._current_preset_path = path
            if path:
                self.llama_panel.append_log(
                    f"[GUI] 预设配置：{path}（共 {len(self.presets.items)} 项）")
            else:
                self.llama_panel.append_log("[GUI] 工作目录无效，预设暂不可用。")
        for w in self.presets.warnings:
            self.llama_panel.append_log(f"[GUI] 预设：{w}")

    def _set_presets_available(self, available: bool):
        for btn in self.preset_btns:
            btn.setEnabled(available)

    def _refresh_preset_list(self):
        self._suppress_select = True
        try:
            self.preset_tree.clear()
            kw = self.preset_filter_edit.text().strip().lower()
            for i, p in enumerate(self.presets.items):
                name = p["name"] or "(未命名)"
                model_name = os.path.basename(p["model"]) if p["model"] else "-"
                if kw and (kw not in name.lower()
                           and kw not in (p["model"] or "").lower()):
                    continue
                it = QTreeWidgetItem([name, model_name])
                it.setData(0, Qt.UserRole, i)
                self.preset_tree.addTopLevelItem(it)
        finally:
            self._suppress_select = False

    def _selected_index(self):
        it = self.preset_tree.currentItem()
        if it is None:
            return None
        idx = it.data(0, Qt.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self.presets.items):
            return idx
        return None

    def _select_index(self, idx):
        if idx is None:
            return
        for i in range(self.preset_tree.topLevelItemCount()):
            it = self.preset_tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) == idx:
                self._suppress_select = True
                try:
                    self.preset_tree.setCurrentItem(it)
                    self.preset_tree.scrollToItem(it)
                finally:
                    self._suppress_select = False
                return

    def _select_preset_by_name(self, name):
        idx = self.presets.index_of(name)
        if idx >= 0:
            self._select_index(idx)
            self._current_preset_index = idx

    def _save_presets(self):
        ok, info = self.presets.save()
        if not ok:
            QMessageBox.critical(self, "保存失败", info)
            return False
        return True

    def _snapshot_inputs(self):
        self._input_snapshot = self._current_inputs()

    def _current_inputs(self):
        return (self.model_edit.text(),
                self.args_edit.toPlainText(),
                self.comfy_python_edit.text(),
                self.comfy_main_edit.text(),
                self.comfy_args_edit.text())

    def _inputs_dirty(self):
        if self._input_snapshot is None:
            return False
        return self._input_snapshot != self._current_inputs()

    def _current_comfy_config(self):
        return {
            "python": self.comfy_python_edit.text().strip(),
            "main": self.comfy_main_edit.text().strip(),
            "args": self.comfy_args_edit.text().strip(),
        }

    def _on_preset_select(self):
        if self._suppress_select:
            return
        idx = self._selected_index()
        if idx is None:
            return
        self._apply_preset(idx)

    def _apply_preset(self, idx):
        if not (0 <= idx < len(self.presets.items)):
            return
        if idx != self._current_preset_index and self._inputs_dirty():
            ret = QMessageBox.question(
                self, "切换预设",
                "当前输入尚未保存，切换预设将丢弃这些修改。\n\n是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                self._select_index(self._current_preset_index)
                return
        p = self.presets.items[idx]
        self.model_edit.setText(p["model"])
        self.args_edit.setPlainText(p["args"])
        comfy = p.get("comfy")
        if comfy:
            self.comfy_python_edit.setText(comfy.get("python", ""))
            self.comfy_main_edit.setText(comfy.get("main", ""))
            self.comfy_args_edit.setText(comfy.get("args", ""))
        self._current_preset_index = idx
        self._snapshot_inputs()

    def save_preset(self):
        """统一保存入口：有选中条目时先询问是否覆盖，否则另存为新预设。"""
        workdir = self.workdir_edit.text().strip()
        if not workdir or not os.path.isdir(workdir):
            QMessageBox.warning(self, "提示", "请先设置有效的工作目录。")
            return
        idx = self._selected_index()
        if idx is not None:
            name = self.presets.items[idx]["name"] or "(未命名)"
            ret = QMessageBox.question(
                self, "保存预设",
                f"是否覆盖当前选中的预设「{name}」？\n\n"
                f"选择「No」将把当前输入另存为新预设。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                self._overwrite_preset_at(idx)
                return
        self._save_preset_as_new()

    def _save_preset_as_new(self):
        model = self.model_edit.text().strip()
        args = self.args_edit.toPlainText().rstrip("\n")
        default_name = os.path.splitext(os.path.basename(model))[0] \
            if model else "新预设"
        name, ok = QInputDialog.getText(
            self, "保存预设", "请输入预设名称：", text=default_name)
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "提示", "预设名称不能为空。")
            return
        self.presets.add_or_update(
            name, model, args, self._current_comfy_config())
        if not self._save_presets():
            return
        self._refresh_preset_list()
        self._select_preset_by_name(name)
        self._snapshot_inputs()

    def _overwrite_preset_at(self, idx):
        """用当前输入覆盖指定预设（不含确认框，确认由调用方负责）。"""
        p = self.presets.items[idx]
        model = self.model_edit.text().strip()
        args = self.args_edit.toPlainText().rstrip("\n")
        old = (p["model"], p["args"], p.get("comfy"))
        p["model"] = model
        p["args"] = args
        p["comfy"] = self._current_comfy_config()
        if not self._save_presets():
            p["model"], p["args"] = old[0], old[1]
            if old[2] is None:
                p.pop("comfy", None)
            else:
                p["comfy"] = old[2]
            return
        self._refresh_preset_list()
        self._select_index(idx)
        self._current_preset_index = idx
        self._snapshot_inputs()

    def move_selected_preset(self, offset):
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = self.presets.move(idx, offset)
        if new_idx == idx:
            return
        if not self._save_presets():
            self.presets.move(new_idx, -offset)
            return
        self._refresh_preset_list()
        self._select_index(new_idx)
        self._current_preset_index = new_idx

    def rename_selected_preset(self):
        idx = self._selected_index()
        if idx is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一个预设。")
            return
        old_name = self.presets.items[idx]["name"] or ""
        new_name, ok = QInputDialog.getText(
            self, "重命名预设", "请输入新的预设名称：", text=old_name)
        if not ok:
            return
        ok, info = self.presets.rename(idx, new_name)
        if not ok:
            QMessageBox.warning(self, "重命名失败", info)
            return
        if not self._save_presets():
            self.presets.items[idx]["name"] = old_name
            return
        self._refresh_preset_list()
        self._select_index(idx)
        self._current_preset_index = idx

    def delete_selected_preset(self):
        idx = self._selected_index()
        if idx is None:
            return
        name = self.presets.items[idx]["name"] or "(未命名)"
        ret = QMessageBox.question(
            self, "删除预设", f"确定要删除预设「{name}」吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        removed = self.presets.remove_at(idx)
        if not self._save_presets():
            # 保存失败则回滚内存列表，保持与磁盘文件一致
            if removed is not None:
                self.presets.items.insert(idx, removed)
            return
        if self._current_preset_index is not None:
            if self._current_preset_index == idx:
                self._current_preset_index = None
            elif self._current_preset_index > idx:
                self._current_preset_index -= 1
        self._refresh_preset_list()
        remaining = len(self.presets.items)
        if remaining:
            new_sel = min(idx, remaining - 1)
            self._select_index(new_sel)

    def reset_inputs(self):
        self.model_edit.setText("")
        self.args_edit.setPlainText("")
        self._suppress_select = True
        try:
            self.preset_tree.clearSelection()
        finally:
            self._suppress_select = False
        self._current_preset_index = None
        self._snapshot_inputs()

    def _show_tree_menu(self, pos):
        it = self.preset_tree.itemAt(pos)
        if it is None:
            return
        idx = it.data(0, Qt.UserRole)
        if not isinstance(idx, int):
            return
        self._suppress_select = True
        try:
            self.preset_tree.setCurrentItem(it)
        finally:
            self._suppress_select = False
        menu = QMenu(self)
        menu.addAction("重命名…", self.rename_selected_preset)
        menu.addAction("删除", self.delete_selected_preset)
        menu.addSeparator()
        menu.addAction("↑ 上移", lambda: self.move_selected_preset(-1))
        menu.addAction("↓ 下移", lambda: self.move_selected_preset(1))
        menu.exec(self.preset_tree.mapToGlobal(pos))

    # ==========================================================================
    #                           启动命令构造与地址解析
    # ==========================================================================
    def _build_llama_command(self):
        workdir = self.workdir_edit.text().strip()
        if not workdir or not os.path.isdir(workdir):
            QMessageBox.critical(self, "错误", f"工作目录不存在：\n{workdir}")
            return None
        exe = self.exe_edit.text().strip()
        if not exe:
            QMessageBox.critical(self, "错误", "请填写可执行文件。")
            return None
        exe_path = exe if os.path.isabs(exe) else os.path.join(workdir, exe)
        exe_path = os.path.normpath(exe_path)
        if not os.path.isfile(exe_path):
            QMessageBox.critical(self, "错误", f"找不到可执行文件：\n{exe_path}")
            return None

        model = self.model_edit.text().strip()
        if model and not os.path.isfile(model):
            ret = QMessageBox.question(
                self, "提示", f"模型文件不存在：\n{model}\n\n仍然继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return None
        if not model and not self._args_have_model():
            QMessageBox.critical(self, "错误", "模型文件为空。")
            return None

        args = [ln.strip() for ln in self.args_edit.toPlainText().splitlines()
                if ln.strip()]
        cmd = [exe_path]
        if model:
            cmd += ["--model", model]
        cmd += args
        return cmd, workdir, None

    def _args_have_model(self):
        for ln in self.args_edit.toPlainText().splitlines():
            s = ln.strip()
            if re.match(r"^--?model(=|$)", s):
                return True
        return False

    def _build_comfy_command(self):
        python = self.comfy_python_edit.text().strip()
        if not python or not os.path.isfile(python):
            QMessageBox.critical(self, "错误", f"找不到 Python 解释器：\n{python}")
            return None
        main_py = self.comfy_main_edit.text().strip()
        if not main_py or not os.path.isfile(main_py):
            ret = QMessageBox.question(
                self, "提示", f"ComfyUI 主程序不存在：\n{main_py}\n\n仍然继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return None

        extra = self.comfy_args_edit.text().strip()
        try:
            extra_args = win_cmdline_split(extra) if extra else []
        except ValueError:
            QMessageBox.critical(self, "错误", "ComfyUI 参数格式不正确。")
            return None

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        cmd = [python, "-X", "utf8", "-u", main_py] + extra_args
        workdir = os.path.dirname(main_py) or None
        return cmd, workdir, env

    @staticmethod
    def _display_host(h):
        return "127.0.0.1" if h in ("0.0.0.0", "::", "", "*") else h

    @staticmethod
    def _extract_flag(tokens, flag, default):
        for i, t in enumerate(tokens):
            if t == flag:
                if i + 1 < len(tokens):
                    return tokens[i + 1].strip('"')
                return default
            if t.startswith(flag + "="):
                return t[len(flag) + 1:].strip('"')
        return default

    def _llama_tokens(self):
        return [ln.strip() for ln in self.args_edit.toPlainText().splitlines()
                if ln.strip()]

    def _llama_log_url(self):
        """返回 llama-server 本次运行日志中广播的监听地址（规范化的 URL）。

        服务启动后会输出类似：
            main: server is listening on http://127.0.0.1:8080 - starting the main loop
        该地址反映服务端实际监听情况（含端口被占用后改用其他端口的场景）。
        """
        raw = self.llama_panel.last_listen_url
        if not raw:
            return None
        try:
            p = urlparse(raw)
            if p.scheme not in ("http", "https") or not p.hostname:
                return None
            host = self._display_host(p.hostname)
            host_part = f"[{host}]" if ":" in host else host
            netloc = host_part + (f":{p.port}" if p.port else "")
            return f"{p.scheme}://{netloc}/"
        except ValueError:
            return None

    def _llama_page_url(self):
        # 优先采用 llama-server 启动后日志里广播的实际监听地址；
        # 解析不到（尚未输出 / 启动失败）时回退到参数框解析。
        url = self._llama_log_url()
        if url:
            return url
        tokens = self._llama_tokens()
        port = self._extract_flag(tokens, "--port", DEFAULT_LLAMA_PORT)
        host = self._extract_flag(tokens, "--host", "127.0.0.1")
        return f"http://{self._display_host(host)}:{port}/"

    def _llama_probe(self):
        return self._llama_page_url().rstrip("/") + "/health", 200

    def _comfy_tokens(self):
        try:
            return win_cmdline_split(self.comfy_args_edit.text().strip())
        except ValueError:
            return []

    def _comfy_page_url(self):
        tokens = self._comfy_tokens()
        port = self._extract_flag(tokens, "--port", DEFAULT_COMFY_PORT)
        host = self._extract_flag(tokens, "--listen", "127.0.0.1")
        return f"http://{self._display_host(host)}:{port}/"

    def _comfy_probe(self):
        return self._comfy_page_url(), None

    # ============================ 标题状态摘要 ============================
    def _update_title(self):
        """窗口标题附带各服务运行状态摘要。"""
        if self._closing:
            return
        if self.panels:
            info = " | ".join(f"{p.name} {p.state_text}" for p in self.panels)
            self.setWindowTitle(f"{BASE_TITLE}  —  {info}")
        else:
            self.setWindowTitle(BASE_TITLE)

    # ============================ 会话状态持久化 ============================
    def _load_session(self):
        """启动时恢复上次会话的输入与窗口尺寸（llama_gui_state.json）。

        优先读取新版程序目录下的状态文件；不存在时回退读取
        旧版 tkinter 程序（RunLlamaServerGUI.py）留下的状态文件，
        实现配置无缝迁移。"""
        path = None
        for cand in (self._state_path, self._legacy_state_path):
            if cand and os.path.isfile(cand):
                path = cand
                break
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        # 批量恢复输入时屏蔽信号，避免触发预设重复重载
        for key, edit in (("workdir", self.workdir_edit),
                          ("exe", self.exe_edit),
                          ("model", self.model_edit)):
            v = data.get(key)
            if isinstance(v, str) and v:
                edit.blockSignals(True)
                edit.setText(v)
                edit.blockSignals(False)
        args = data.get("args")
        if isinstance(args, str):
            self.args_edit.setPlainText(args)
        comfy = data.get("comfy")
        if isinstance(comfy, dict):
            if isinstance(comfy.get("python"), str) and comfy["python"]:
                self.comfy_python_edit.setText(comfy["python"])
            if isinstance(comfy.get("main"), str) and comfy["main"]:
                self.comfy_main_edit.setText(comfy["main"])
            if isinstance(comfy.get("args"), str):
                self.comfy_args_edit.setText(comfy["args"])
        win = data.get("window")
        if isinstance(win, dict):
            try:
                # 不小于窗口最小尺寸
                w = max(int(win.get("w") or 0), MIN_W)
                h = max(int(win.get("h") or 0), MIN_H)
                self.resize(w, h)
            except (TypeError, ValueError):
                pass
        spl = data.get("splitters")
        if isinstance(spl, dict):
            try:
                v = spl.get("v")
                if isinstance(v, list) and len(v) == 2:
                    self.vsplit.setSizes([int(x) for x in v])
                h = spl.get("h")
                if isinstance(h, list) and len(h) == 2:
                    self.hsplit.setSizes([int(x) for x in h])
                lg = spl.get("logs")
                if isinstance(lg, list) and len(lg) == 2:
                    self.logs_split.setSizes([int(x) for x in lg])
            except (TypeError, ValueError):
                pass
        # 恢复主题（main.py 已在启动时应用过；此处兜底 run() 等直接构造场景）
        theme = normalize_theme(data.get("theme"))
        if theme != self._theme:
            self._theme = theme
            app = QApplication.instance()
            if app:
                apply_theme(app, theme)

    def _save_session(self):
        """退出前保存当前输入与窗口尺寸，供下次启动恢复（原子写入）。"""
        data = {
            "version": 2,
            "theme": self._theme,
            "workdir": self.workdir_edit.text(),
            "exe": self.exe_edit.text(),
            "model": self.model_edit.text(),
            "args": self.args_edit.toPlainText().rstrip("\n"),
            "comfy": {
                "python": self.comfy_python_edit.text(),
                "main": self.comfy_main_edit.text(),
                "args": self.comfy_args_edit.text(),
            },
        }
        try:
            data["window"] = {"w": self.width(), "h": self.height()}
        except Exception:
            pass
        try:
            data["splitters"] = {
                "v": self.vsplit.sizes(),
                "h": self.hsplit.sizes(),
                "logs": self.logs_split.sizes(),
            }
        except Exception:
            pass
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._state_path)
        except OSError:
            pass

    # ============================ 退出 ============================
    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        running = [p.name for p in self.panels if p.is_running()]
        if running:
            msg = ("以下服务仍在运行：\n\n  · " + "\n  · ".join(running) +
                   "\n\n确定要停止它们并退出吗？")
            ret = QMessageBox.question(
                self, "退出", msg, QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok)
            if ret != QMessageBox.Ok:
                event.ignore()
                return

        self._closing = True
        self._save_session()
        self._workdir_timer.stop()
        self.gpu_bar.stop()  # 停止 GPU 监控线程

        self.setWindowTitle(BASE_TITLE + "（正在退出…）")

        running_panels = [p for p in self.panels if p.is_running()]
        if not running_panels:
            event.accept()
            return

        event.ignore()

        def worker():
            for pnl in running_panels:
                try:
                    pnl.shutdown_tree()
                except Exception:
                    pass
            self._close_finished.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _final_close(self):
        self.close()  # 此时 _closing=True，closeEvent 直接放行


def run():
    import sys
    from PySide6.QtWidgets import QApplication

    from .theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()
