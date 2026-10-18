"""llama-server 参数可视化编辑器（自定义参数模式）。

- 打开时读取主界面「其它参数」文本框，仅把其中已有的参数显示为可编辑行
- 参数名 + 值 两列；值留空表示无值的开关型参数（如 --no-warmup）
- 「＋ 添加参数」弹出对话框：手动填写，或从常见参数中一键添加
- 「应用」时把全部行写回文本框
"""

import re

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)


def _looks_like_flag(line):
    """判断一行是否像参数名（以 -/-- 开头；排除 -1 这类负数字值）。"""
    s = (line or "").strip()
    if not s.startswith("-") or len(s) < 2:
        return False
    return not re.match(r"^-\d+(\.\d+)?$", s)


def _parse_pairs(lines):
    """把多行参数文本解析为 [(参数名, 值|None), ...]。
    规则：
    - 以 -/-- 开头的行是参数名；紧随其后且不像参数名的行视为其值；
    - `--flag=value` 单行形式自动拆分为 参数名 + 值；
    - 孤立值行合并给上一个尚无值的参数，否则保留为 ("", 值)。"""
    pairs = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        m = re.match(r"^(--?[^\s=]+)=(.*)$", ln)
        if m and _looks_like_flag(m.group(1)):
            pairs.append((m.group(1), m.group(2)))
            i += 1
            continue
        if _looks_like_flag(ln):
            value = None
            nxt = lines[i + 1].strip() if i + 1 < n else ""
            if nxt and not _looks_like_flag(nxt):
                value = nxt
                i += 2
            else:
                i += 1
            pairs.append((ln, value))
            continue
        if pairs and pairs[-1][1] is None:
            pairs[-1] = (pairs[-1][0], ln)
        else:
            pairs.append(("", ln))
        i += 1
    return pairs


# 「添加参数」对话框中的常见参数预设：(参数名, 默认值, 说明)。
# 默认值为 None 表示特殊项（--mmproj：通过文件选择窗口指定视觉 GGUF 模型路径）；
# 为空字符串表示无值的开关型参数。
COMMON_PRESET_PARAMS = [
    ("--mmproj", None,
     "视觉投影模型：点击后从本地选择 GGUF 文件并自动填入完整路径"),
    ("--cache-type-k", "q8_0", "KV 缓存 K 量化类型"),
    ("--cache-type-v", "q8_0", "KV 缓存 V 量化类型"),
    ("--spec-type", "draft-mtp", "投机解码草稿类型"),
    ("--jinja", "", "无值开关参数：启用 Jinja 聊天模板"),
    ("--reasoning-budget", "1024", "思考 token 预算"),
]


class AddParamDialog(QDialog):
    """添加参数对话框：顶部手动填写，下方为常见参数一键添加。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("添加参数")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.pair = None  # (参数名, 值)；None 表示未选择任何项

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # 顶部：手动填写
        manual_btn = QPushButton("✎ 手动填写…")
        manual_btn.setToolTip("添加一行空白参数，自行输入参数名与值。")
        manual_btn.clicked.connect(lambda: self._finish(("", "")))
        lay.addWidget(manual_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        lay.addWidget(sep)

        # 下方：常见参数一键添加
        lay.addWidget(QLabel("常见参数（点击直接添加）："))
        for flag, value, desc in COMMON_PRESET_PARAMS:
            if value is None:      # 特殊项：值通过文件选择获得
                text = f"{flag}（选择视觉模型文件…）"
            elif value:
                text = f"{flag}  {value}"
            else:
                text = flag
            btn = QPushButton(text)
            btn.setToolTip(desc)
            btn.clicked.connect(
                lambda checked=False, f=flag, v=value: self._on_common(f, v))
            lay.addWidget(btn)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

    def _finish(self, pair):
        self.pair = pair
        self.accept()

    def _on_common(self, flag, value):
        if value is None:  # --mmproj：先从本地选择视觉 GGUF 模型文件
            path, _flt = QFileDialog.getOpenFileName(
                self, "选择视觉模型 (mmproj)", "",
                "GGUF 模型 (*.gguf);;所有文件 (*.*)")
            if not path:
                return  # 取消选择 → 对话框保持打开
            value = path
        self._finish((flag, value))


class ParamEditorDialog(QDialog):
    """参数编辑器对话框：全部参数以自定义行形式手动编辑。"""

    def __init__(self, parent, args_text):
        super().__init__(parent)
        self.setWindowTitle("可视化参数编辑器")
        self.resize(660, 560)
        self.setMinimumSize(520, 420)
        self.setModal(True)
        self.args_edit = args_text
        self._rows = []      # 参数行记录

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        hint = QLabel("仅显示当前「其它参数」中已有的参数，可在此直接修改。\n"
                      "值留空表示无值的开关型参数。")
        hint.setStyleSheet("color: #8a93a6;")
        lay.addWidget(hint)

        # ---------------- 参数行区（滚动） ----------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        lay.addWidget(scroll, 1)

        group = QGroupBox("自定义参数（可直接编辑）")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(12, 8, 12, 8)
        gl.setSpacing(4)

        header = QHBoxLayout()
        h1 = QLabel("参数名")
        h1.setFixedWidth(170)
        header.addWidget(h1)
        header.addWidget(QLabel("值（留空 = 无值开关型参数）"))
        header.addStretch(1)
        gl.addLayout(header)

        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(4)
        gl.addLayout(self._rows_lay)
        gl.addStretch(1)

        scroll.setWidget(group)

        # ---------------- 新增按钮 ----------------
        addbar = QHBoxLayout()
        add_btn = QPushButton("＋ 添加参数")
        add_btn.setToolTip("打开添加参数对话框：可手动填写参数，"
                           "或从常见参数中一键添加。")
        add_btn.clicked.connect(self._add_new_param)
        addbar.addWidget(add_btn)
        addbar.addStretch(1)
        lay.addLayout(addbar)

        # ---------------- 底部按钮 ----------------
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        apply_btn = QPushButton("应用到文本框")
        apply_btn.setProperty("accent", True)
        apply_btn.clicked.connect(self._apply)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)

        # 打开时：把「其它参数」现有内容逐项显示为可编辑行
        lines = [ln.strip() for ln in self.args_edit.toPlainText().splitlines()]
        for flag, value in _parse_pairs(lines):
            self._add_param_row(flag, "" if value is None else value)

    # ------------------------------------------------------------ 参数行
    def _add_param_row(self, flag="", value=""):
        """追加一行参数：参数名 / 值 / 删除按钮。"""
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        mono = QFont("Consolas", 9)
        name_edit = QLineEdit(flag)
        name_edit.setFont(mono)
        name_edit.setFixedWidth(170)
        name_edit.setPlaceholderText("--example-flag")
        name_edit.setToolTip("参数名，如 --ctx-size 或 -c（以 - / -- 开头）。")
        value_edit = QLineEdit(value)
        value_edit.setFont(mono)
        value_edit.setToolTip("参数值，留空表示无值的开关型参数。\n"
                              "值作为单独一行写回文本框，可包含空格。")
        del_btn = QPushButton("✕")
        del_btn.setObjectName("rowDeleteBtn")   # 见 theme.py：清零内边距
        del_btn.setProperty("danger", True)     # 红色「危险」样式
        del_btn.setFixedSize(26, 24)
        del_btn.setToolTip("删除这一行参数。")
        del_font = del_btn.font()
        del_font.setPointSize(11)
        del_font.setBold(True)
        del_btn.setFont(del_font)
        rec = {"widget": row, "name_edit": name_edit, "value_edit": value_edit}
        del_btn.clicked.connect(lambda: self._remove_param_row(rec))
        rl.addWidget(name_edit)
        rl.addWidget(value_edit, 1)
        rl.addWidget(del_btn)
        self._rows_lay.addWidget(row)
        self._rows.append(rec)

    def _remove_param_row(self, rec):
        if rec in self._rows:
            self._rows.remove(rec)
        rec["widget"].setParent(None)
        rec["widget"].deleteLater()

    def _add_new_param(self):
        """「＋ 添加参数」：弹出对话框（手动填写或常见参数一键添加）。"""
        dlg = AddParamDialog(self)
        if dlg.exec() != QDialog.Accepted or dlg.pair is None:
            return
        flag, value = dlg.pair
        self._add_param_row(flag, value)
        # 手动填写聚焦参数名；预设参数聚焦值（便于微调默认值）
        last = self._rows[-1]
        (last["name_edit"] if not flag else last["value_edit"]).setFocus()

    # ------------------------------------------------------------ 应用
    def _apply(self):
        """把全部行写回 args_edit（按「参数名一行、值一行」的多行格式）。"""
        out_lines = []
        invalid = []
        for rec in self._rows:
            flag = rec["name_edit"].text().strip()
            value = rec["value_edit"].text().strip()
            if not flag:
                if value:
                    out_lines.append(value)  # 只有值的孤立行：原样写回
                continue
            if (not flag.startswith("-") or len(flag) < 2
                    or re.search(r"\s", flag)):
                invalid.append(flag)
                continue
            out_lines.append(flag)
            if value:
                out_lines.append(value)
        if invalid:
            QMessageBox.warning(
                self, "提示",
                "以下参数名无效（需以 - 或 -- 开头且不含空白），已跳过：\n"
                "  " + "\n  ".join(invalid))
        self.args_edit.setPlainText("\n".join(out_lines))
        self.accept()
