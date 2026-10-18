"""受管子进程面板（llama-server / ComfyUI 共用）。

每个面板包含：按钮工具栏（启动/停止/清空日志/导出日志/打开页面/自动打开）
+ 状态标签 + 日志视图。子进程通过 Job Object 管理（主程序退出即全树终止），
输出经后台线程读取、QTimer 统一泵入 UI，避免高频日志卡界面。
"""

import queue
import subprocess
import threading
import webbrowser
from collections import deque
from datetime import datetime

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .constants import (ANSI_RE, CRASH_DIAGNOSES, LOG_ENCODING, LOG_ERRORS,
                        LOG_ERR_RE, LLAMA_LISTEN_RE)
from .winprocess import (_assign_to_job, _close_job_handle,
                         _create_kill_on_close_job, _terminate_job_tree,
                         kill_tree_by_pid)

from urllib.request import ProxyHandler, build_opener
import urllib.error


def _http_probe(url, expect_code=None, timeout=1.5):
    """轻量 HTTP 探测：返回 True 表示服务已就绪。"""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return True if expect_code is None else code == expect_code
    except urllib.error.HTTPError as e:
        return expect_code is None or e.code == expect_code
    except Exception:
        return False


class ProcessPanel(QWidget):
    """管理一个子进程的通用组件（按钮栏 + 日志区）。"""

    state_changed = Signal()
    _probe_done = Signal(bool)

    def __init__(self, app, *, name, build_command, page_url_fn,
                 ready_probe_fn=None, open_label="打开页面", stop_grace=8,
                 parent=None):
        super().__init__(parent)
        self.app = app
        self.name = name
        self.build_command = build_command
        self.page_url_fn = page_url_fn
        self.ready_probe_fn = ready_probe_fn
        self.stop_grace = stop_grace

        self.proc = None
        self.job = None
        self._q = queue.Queue()          # ("log", line) / ("exit", rc) / ("stopped", rc)
        self._stop_flow = False
        self._probing = False
        self.state_text = "已停止"
        self.last_listen_url = None      # 本次运行日志中捕获的监听地址（原始 URL）
        self._recent = deque(maxlen=600) # 最近日志行（崩溃诊断用）
        self._run_lines = []             # 本次运行的全部日志行

        self.TXT_STOPPED = f"● {name} 已停止"
        self.TXT_RUNNING = f"● {name} 运行中"
        self.TXT_READY = f"● {name} 运行中（就绪）"
        self.TXT_STOPPING = f"● {name} 正在停止…"

        self._err_fmt = QTextCharFormat()
        self._err_fmt.setForeground(QColor("#ff7b72"))

        # ---------------- 工具栏 ----------------
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 4)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.start_btn = QPushButton(f"▶ 启动 {name}")
        self.start_btn.setProperty("accent", True)
        self.start_btn.setToolTip("启动服务（先校验路径与参数）。")
        self.start_btn.clicked.connect(self.start)
        bar.addWidget(self.start_btn)

        self.stop_btn = QPushButton(f"■ 停止 {name}")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("先尝试优雅终止，超时后强制结束整个进程树。")
        self.stop_btn.clicked.connect(self.stop)
        bar.addWidget(self.stop_btn)

        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.clear_log)
        bar.addWidget(clear_btn)

        export_btn = QPushButton("导出日志")
        export_btn.setToolTip("把当前日志内容另存为 .log 文件。")
        export_btn.clicked.connect(self.export_log)
        bar.addWidget(export_btn)

        self.open_btn = QPushButton(open_label)
        self.open_btn.setEnabled(False)
        self.open_btn.setToolTip("用浏览器打开服务页面。")
        self.open_btn.clicked.connect(self._open_page)
        bar.addWidget(self.open_btn)

        self.auto_open_cb = QCheckBox("就绪后自动打开")
        bar.addWidget(self.auto_open_cb)

        bar.addStretch(1)
        self.status_lbl = QLabel(self.TXT_STOPPED)
        self.status_lbl.setStyleSheet("font-weight: 700; font-size: 10pt;")
        bar.addWidget(self.status_lbl)
        lay.addLayout(bar)

        # ---------------- 日志区 ----------------
        log_group = QGroupBox(f"{name} 日志")
        lg = QVBoxLayout(log_group)
        lg.setContentsMargins(8, 8, 8, 8)
        self.log = QPlainTextEdit()
        self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log.document().setMaximumBlockCount(5000)
        lg.addWidget(self.log)
        lay.addWidget(log_group, 1)

        # 日志泵：后台线程写队列，UI 定时批量取（与原版 pump 一致）
        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(100)
        self._pump_timer.timeout.connect(self.pump)
        self._pump_timer.start()

        # 就绪探测定时器
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(1500)
        self._probe_timer.timeout.connect(self._ready_poll_tick)
        self._probe_done.connect(self._on_probe_done)

    # ------------------------------------------------------------ 状态
    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    # ------------------------------------------------------------ 启动
    def start(self):
        if self.is_running() or self._stop_flow:
            return
        # 先禁用启动按钮，防止快速连点拉起两个进程
        self.start_btn.setEnabled(False)
        try:
            built = self.build_command()
        except Exception as e:
            self.start_btn.setEnabled(True)
            QMessageBox.critical(self.window(), "错误", f"构造启动命令时出错：{e}")
            return
        if not built:
            self.start_btn.setEnabled(True)
            return
        cmd, cwd, env = built

        self.append_log("=" * 70)
        self.append_log(f"[GUI] 启动 {self.name}，命令：")
        self.append_log("  " + subprocess.list2cmdline(cmd))
        if cwd:
            self.append_log(f"[GUI] 工作目录：{cwd}")

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(
            subprocess, "CREATE_NO_WINDOW") else 0
        job = _create_kill_on_close_job()
        if job is None:
            self.append_log("[GUI] 警告：Job Object 不可用。")

        try:
            self.proc = subprocess.Popen(
                cmd, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, encoding=LOG_ENCODING, errors=LOG_ERRORS,
                bufsize=1, creationflags=creationflags, env=env)
        except Exception as e:
            self.proc = None
            _close_job_handle(job)
            self.start_btn.setEnabled(True)
            self.append_log(f"[GUI] 启动失败：{e}")
            QMessageBox.critical(self.window(), "启动失败", str(e))
            return

        # 本次运行日志起点：重置监听地址捕获与运行行缓存
        self._run_lines = []
        self.last_listen_url = None
        if job is not None and not _assign_to_job(job, self.proc):
            self.append_log("[GUI] 警告：进程未能加入 Job Object。")
        self.job = job

        self._stop_flow = False
        self.set_running(True)
        self.append_log(f"[GUI] {self.name} 已启动（PID：{self.proc.pid}）。")

        threading.Thread(target=self._reader_thread, args=(self.proc,),
                         daemon=True).start()

        if self.ready_probe_fn is not None:
            self._probe_timer.start()

    # ------------------------------------------------------------ 停止
    def stop(self):
        p = self.proc
        if p is None or p.poll() is not None:
            return
        self._stop_flow = True
        self._set_stopping_ui()
        self.append_log("[GUI] 正在停止服务…")
        threading.Thread(target=self._stop_worker, args=(p,), daemon=True).start()

    def _set_stopping_ui(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText(self.TXT_STOPPING)
        self.status_lbl.setStyleSheet(
            "font-weight: 700; font-size: 10pt; color: #f0a04b;")
        self.state_text = "停止中"
        self.state_changed.emit()

    def _stop_worker(self, p):
        try:
            p.terminate()
            try:
                p.wait(timeout=self.stop_grace)
            except subprocess.TimeoutExpired:
                self._q.put(("log", "[GUI] 强制结束进程树…"))
                self._kill_tree(p)
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass
        except Exception as e:
            self._q.put(("log", f"[GUI] terminate 失败（{e}）。"))
            self._kill_tree(p)
        if self.job:
            _terminate_job_tree(self.job)
        self._q.put(("stopped", p.poll()))

    def _kill_tree(self, p):
        if self.job:
            _terminate_job_tree(self.job)
            return
        kill_tree_by_pid(p.pid)

    def shutdown_tree(self):
        """应用退出时的强制清理（后台线程调用）。"""
        p = self.proc
        if p is None:
            return
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._kill_tree(p)
        except Exception:
            try:
                self._kill_tree(p)
            except Exception:
                pass
        if self.job:
            _terminate_job_tree(self.job)
        self._close_job()
        self.proc = None

    # ------------------------------------------------------------ 输出读取
    def _reader_thread(self, proc):
        try:
            for line in proc.stdout:
                self._q.put(("log", line.rstrip("\r\n")))
        except Exception as e:
            self._q.put(("log", f"[GUI] 读取输出出错：{e}"))
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                rc = proc.wait()
            except Exception:
                rc = -1
            self._q.put(("exit", rc))

    def pump(self):
        """把队列中的日志批量写入视图，并按序处理 exit / stopped 事件。"""
        logs = []
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                logs.append(payload)
                continue
            self._insert_logs(logs)
            logs = []
            if kind == "exit":
                self._on_exit(payload)
            elif kind == "stopped":
                self._on_stopped(payload)
        self._insert_logs(logs)

    def _on_exit(self, rc):
        if self.proc is None:
            return
        was_stopping = self._stop_flow
        self._stop_flow = False
        self._finalize()
        if was_stopping:
            self.append_log(f"[GUI] {self.name} 已停止。")
        elif rc:
            # 非用户操作导致的异常退出：红字提示 + 日志特征诊断 + 弹窗
            self.append_log(f"[GUI] ⚠ {self.name} 异常退出，返回码：{rc}", tag="err")
            diag = self._diagnose_log()
            if diag:
                self.append_log(f"[GUI] 诊断：{diag}", tag="err")
            if not self.app._closing:
                QMessageBox.warning(
                    self.window(), f"{self.name} 异常退出",
                    f"{self.name} 异常退出（返回码 {rc}）。"
                    + (f"\n\n{diag}" if diag else "\n\n详情请查看日志面板。"))
        else:
            self.append_log(f"[GUI] {self.name} 已退出，返回码：{rc}")

    def _diagnose_log(self):
        """在最近日志中查找常见崩溃特征，返回诊断文案（未命中返回 None）。"""
        text = "\n".join(list(self._recent)[-300:])
        for pat, hint in CRASH_DIAGNOSES:
            if pat.search(text):
                return hint
        return None

    def _on_stopped(self, rc):
        self._stop_flow = False
        if self.proc is None:
            return
        self._finalize()
        self.append_log(f"[GUI] {self.name} 已停止。")

    def _finalize(self):
        self.proc = None
        self._close_job()
        self._probe_timer.stop()
        self.set_running(False)

    def _close_job(self):
        if self.job:
            _close_job_handle(self.job)
            self.job = None

    # ------------------------------------------------------------ 就绪探测
    def _ready_poll_tick(self):
        if self.app._closing or self.proc is None or self._probing:
            return
        target = None
        if self.ready_probe_fn is not None:
            try:
                target = self.ready_probe_fn()
            except Exception:
                target = None
        if not target:
            return
        url, code = target
        self._probing = True

        def worker():
            ok = False
            try:
                ok = _http_probe(url, code)
            except Exception:
                ok = False
            self._probe_done.emit(ok)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(bool)
    def _on_probe_done(self, ok):
        self._probing = False
        if not ok:
            return
        if self.app._closing or self.proc is None:
            return
        self._probe_timer.stop()
        self.set_running(True, ready=True)
        self.append_log(f"[GUI] {self.name} 已就绪。")
        if self.auto_open_cb.isChecked():
            try:
                webbrowser.open(self.page_url_fn())
            except Exception:
                pass

    # ------------------------------------------------------------ 打开页面
    def _open_page(self):
        try:
            url = self.page_url_fn()
        except Exception as e:
            QMessageBox.critical(self.window(), "错误", f"无法生成页面地址：{e}")
            return
        webbrowser.open(url)

    # ------------------------------------------------------------ 日志
    def _insert_logs(self, lines, tag=None):
        if not lines:
            return
        sb = self.log.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 2
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        plain = QTextCharFormat()
        for ln in lines:
            clean = ANSI_RE.sub("", ln)
            # 显式 tag 优先；否则命中错误关键字的行红字高亮
            if tag == "err" or (tag is None and LOG_ERR_RE.search(clean)):
                cursor.insertText(clean + "\n", self._err_fmt)
            else:
                cursor.insertText(clean + "\n", plain)
            self._recent.append(clean)
            self._run_lines.append(clean)
            m = LLAMA_LISTEN_RE.search(clean)
            if m:
                self.last_listen_url = m.group(1)
        if at_end:
            sb.setValue(sb.maximum())

    def append_log(self, text, tag=None):
        self._insert_logs([text], tag)

    def log_tail(self):
        """返回本次运行开始的日志文本。"""
        return "\n".join(self._run_lines)

    def clear_log(self):
        self.log.clear()

    def export_log(self):
        path, _flt = QFileDialog.getSaveFileName(
            self.window(), "导出日志",
            f"{self.name}_{datetime.now():%Y%m%d_%H%M%S}.log",
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log.toPlainText())
            self.append_log(f"[GUI] 日志已导出：{path}")
        except OSError as e:
            QMessageBox.critical(self.window(), "导出失败", str(e))

    # ------------------------------------------------------------ 状态切换
    def set_running(self, running, ready=False):
        if running:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.open_btn.setEnabled(True)
            if ready:
                self.status_lbl.setText(self.TXT_READY)
                self.status_lbl.setStyleSheet(
                    "font-weight: 700; font-size: 10pt; color: #8fe3a8;")
                self.state_text = "就绪"
            else:
                self.status_lbl.setText(self.TXT_RUNNING)
                self.status_lbl.setStyleSheet(
                    "font-weight: 700; font-size: 10pt; color: #5ad879;")
                self.state_text = "运行中"
        else:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.status_lbl.setText(self.TXT_STOPPED)
            self.status_lbl.setStyleSheet(
                "font-weight: 700; font-size: 10pt; color: #ff6b6b;")
            self.state_text = "已停止"
        self.state_changed.emit()
