"""模型目录浏览器：递归扫描 .gguf、解析元数据、估算显存、回填路径。

扫描与 GGUF 解析都在后台线程执行，结果经 Qt 信号逐条送回 UI 插入，
界面不卡顿。筛选仅在已缓存的扫描结果上过滤，不重复访问磁盘。
"""

import os
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTreeWidgetItem, QTreeWidget, QVBoxLayout)

from .constants import DEFAULT_WORKDIR
from .gguf import estimate_vram_gb, extract_gguf_info, parse_gguf_metadata


class ModelLibraryDialog(QDialog):
    """模型目录浏览器主对话框。"""

    _row_ready = Signal(object)   # (path, size, info, vram_total, mtime)
    _scan_done = Signal()

    def __init__(self, parent, on_select, initial_dir=None, current_model=""):
        super().__init__(parent)
        self.setWindowTitle("模型目录浏览器")
        self.resize(1080, 620)
        self.setMinimumSize(860, 480)
        self.setModal(True)
        self.on_select = on_select
        self._stop = threading.Event()
        self._items = []  # (路径, 信息 dict, 大小, 修改时间, 预估显存)
        self._filter_kw = ""

        self._row_ready.connect(self._on_row_ready)
        self._scan_done.connect(self._on_scan_done)

        # ---------------- 顶部：目录选择 + 扫描 ----------------
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("模型根目录："))
        self.dir_edit = QLineEdit(initial_dir or self._guess_root(current_model))
        top.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("浏览…")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse)
        top.addWidget(browse_btn)
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.setFixedWidth(72)
        self.scan_btn.clicked.connect(self.start_scan)
        top.addWidget(self.scan_btn)
        lay.addLayout(top)

        # ---------------- 筛选行 ----------------
        frow = QHBoxLayout()
        frow.addWidget(QLabel("筛选："))
        self.filter_edit = QLineEdit()
        self.filter_edit.setToolTip("按文件名 / 路径关键字实时筛选已扫描的模型。")
        self.filter_edit.textChanged.connect(self._apply_filter)
        frow.addWidget(self.filter_edit, 1)
        lay.addLayout(frow)

        # ---------------- 表格 ----------------
        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels(
            ["文件名", "大小", "量化", "上下文上限", "层数", "参数量",
             "预估显存", "修改时间"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        widths = [(0, 300), (1, 90), (2, 80), (3, 100), (4, 60), (5, 80),
                  (6, 110), (7, 150)]
        for col, w in widths:
            self.tree.setColumnWidth(col, w)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.setContextMenuPolicy(Qt.NoContextMenu)
        self.tree.itemDoubleClicked.connect(lambda *_: self._choose())
        self.tree.setToolTip("双击条目即可选择该模型并回填到主界面。")
        lay.addWidget(self.tree, 1)

        # ---------------- 状态栏 ----------------
        self.status_lbl = QLabel("就绪。点击「扫描」开始。")
        self.status_lbl.setStyleSheet("color: #8a93a6;")
        lay.addWidget(self.status_lbl)

        # ---------------- 底部按钮 ----------------
        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self._close)
        btns.addWidget(close_btn)
        choose_btn = QPushButton("选择并回填")
        choose_btn.setProperty("accent", True)
        choose_btn.clicked.connect(self._choose)
        btns.addWidget(choose_btn)
        lay.addLayout(btns)

        # 自动开始首次扫描
        QTimer.singleShot(200, self.start_scan)

    # ---------------------------------------------------------- 辅助
    @staticmethod
    def _guess_root(current_model):
        if current_model:
            d = os.path.dirname(current_model)
            if d and os.path.isdir(d):
                return d
        return DEFAULT_WORKDIR

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择模型根目录", self.dir_edit.text() or ".")
        if path:
            self.dir_edit.setText(os.path.normpath(path))
            self.start_scan()

    # ---------------------------------------------------------- 扫描
    def start_scan(self):
        root = self.dir_edit.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "提示", "目录无效，请重新选择。")
            return
        self._stop.set()  # 停止上一次扫描
        self._items = []
        self.tree.clear()
        self.status_lbl.setText(f"正在扫描 {root} …")
        self.scan_btn.setEnabled(False)
        self._stop = threading.Event()
        threading.Thread(target=self._scan_worker, args=(root, self._stop),
                         daemon=True, name="gguf-scan").start()

    def _scan_worker(self, root, stop_flag):
        for dirpath, dirnames, filenames in os.walk(root):
            if stop_flag.is_set():
                return
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if stop_flag.is_set():
                    return
                if not fn.lower().endswith(".gguf"):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(path)
                    mtime = datetime.fromtimestamp(os.path.getmtime(path))
                except OSError:
                    continue
                meta = parse_gguf_metadata(path)  # 只读头部，快
                info = extract_gguf_info(meta, size, fn)
                _, _, vram_total = estimate_vram_gb(
                    size, info.get("ctx_limit"), info)
                self._row_ready.emit((path, size, info, vram_total, mtime))
        self._scan_done.emit()

    @Slot(object)
    def _on_row_ready(self, item):
        path, size, info, vram_total, mtime = item
        # 全量缓存；item data = _items 索引，保证筛选后回查仍正确
        idx = len(self._items)
        self._items.append((path, info, size, mtime, vram_total))
        name = os.path.basename(path)
        if self._match_filter(name, path):
            # _make_item 按 _items 的元素顺序解包，此处必须传缓存项而非信号元组
            self.tree.addTopLevelItem(self._make_item(idx, self._items[idx]))

    @Slot()
    def _on_scan_done(self):
        self.scan_btn.setEnabled(True)
        self.status_lbl.setText(
            f"扫描完成，共 {len(self._items)} 个模型。双击条目回填路径。")
        self._apply_filter()

    # ---------------------------------------------------------- 行构造 / 筛选
    def _make_item(self, idx, item):
        path, info, size, mtime, vram_total = item
        it = QTreeWidgetItem([
            os.path.basename(path),
            f"{size / (1024 ** 3):.2f} GB" if size > 1024 ** 3
            else f"{size / (1024 ** 2):.0f} MB",
            str(info.get("quant") or "-"),
            str(info.get("ctx_limit") or "-"),
            str(info.get("n_layers") or "-"),
            str(info.get("params") or "-"),
            f"{vram_total:.1f} GB",
            mtime.strftime("%Y-%m-%d %H:%M"),
        ])
        it.setData(0, Qt.UserRole, idx)
        align_r = int(Qt.AlignRight | Qt.AlignVCenter)
        align_c = int(Qt.AlignCenter | Qt.AlignVCenter)
        it.setTextAlignment(1, align_r)
        it.setTextAlignment(2, align_c)
        it.setTextAlignment(3, align_r)
        it.setTextAlignment(4, align_r)
        it.setTextAlignment(5, align_c)
        it.setTextAlignment(6, align_r)
        it.setTextAlignment(7, align_c)
        return it

    def _match_filter(self, name, path):
        if not self._filter_kw:
            return True
        return (self._filter_kw in name.lower()
                or self._filter_kw in path.lower())

    def _apply_filter(self):
        self._filter_kw = self.filter_edit.text().strip().lower()
        self.tree.clear()
        # size / mtime / vram 均已在扫描时缓存，这里不做任何磁盘访问
        for idx, item in enumerate(self._items):
            path = item[0]
            name = os.path.basename(path)
            if self._match_filter(name, path):
                self.tree.addTopLevelItem(self._make_item(idx, item))

    # ---------------------------------------------------------- 选择 / 关闭
    def _choose(self):
        sel = self.tree.currentItem()
        if sel is None:
            return
        idx = sel.data(0, Qt.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self._items):
            self.on_select(self._items[idx][0])
        self._close()

    def _close(self):
        self._stop.set()
        self.reject()
