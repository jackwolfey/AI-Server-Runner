"""GPU 显存实时监控条（基于第三方库 gpu-smi）。

数据获取策略（双保险，防库版本字段名差异）：
- 显存占用率：官方 API gpu.usage_ratio（0~1）；
- 已用/总显存：优先解析 gpu.summary() 文本（格式稳定：VRAM used/total MB），
  对象属性名兜底；
- 设备名：优先对象属性，summary 兜底；
- 占用显存最高的进程：解析 summary 中的 top 字段。
所有查询都在工作线程执行，结果经 Qt 信号送回主线程更新 UI；
多卡时监控第 1 块。gpu-smi 未安装 / 查询不到 GPU 时显示不可用提示。
依赖：pip install gpu-smi
"""

import re
import threading

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar,
                               QSizePolicy)

from .constants import GPU_POLL_INTERVAL

# ---- gpu.summary() 文本解析正则（属性名不匹配时的兜底数据源） ----
_SUM_NAME_RE = re.compile(r"^\s*\[\d+\]\s*([^|]+?)\s*\|")
_SUM_VRAM_RE = re.compile(r"VRAM\s*(\d+)\s*/\s*(\d+)\s*MB", re.IGNORECASE)
_SUM_TOP_RE = re.compile(r"top:\s*(\S+)\s+(\d+)\s*MB", re.IGNORECASE)

# ---- 对象属性名候选（不同版本字段名可能不同，逐个探测） ----
_ATTR_NAME = ("name", "gpu_name", "device_name", "model")
_ATTR_VRAM_USED = ("vram_used", "mem_used", "memory_used", "used_vram")
_ATTR_VRAM_TOTAL = ("vram_total", "mem_total", "memory_total", "total_vram")


def _probe_attr(obj, names):
    """依次尝试属性名，返回第一个非空且不可调用的值。"""
    for n in names:
        try:
            v = getattr(obj, n, None)
        except Exception:
            v = None
        if v is not None and not callable(v):
            return v
    return None


def _to_number(v):
    """把属性值（数字或含数字的字符串）转为 float；失败返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"(\d+(?:\.\d+)?)", v)
        if m:
            return float(m.group(1))
    return None


class GpuMonitorBar(QGroupBox):
    """GPU 状态监控条：设备名 + 显存进度条 + 已用/总量 + top 进程。"""

    _sample_ready = Signal(object)   # (name, ratio, used_mb, total_mb, top)
    _sample_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(" GPU 状态", parent)
        self._stop = threading.Event()
        self._vram_total_mb = None  # 缓存总显存，供外部查询

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 8)
        lay.setSpacing(8)

        self.gpu_name_lbl = QLabel("正在检测 GPU…")
        self.gpu_name_lbl.setStyleSheet("font-weight: 700;")
        lay.addWidget(self.gpu_name_lbl)

        self.vram_bar = QProgressBar()
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setValue(0)
        self.vram_bar.setTextVisible(False)
        self.vram_bar.setMinimumWidth(180)
        self.vram_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.vram_bar, 1)

        self.vram_lbl = QLabel("显存 - / -")
        self.vram_lbl.setStyleSheet("font-weight: 700;")
        lay.addWidget(self.vram_lbl)

        self.top_lbl = QLabel("")
        self.top_lbl.setStyleSheet("color: #8a93a6;")
        self.top_lbl.setToolTip(
            "当前占用显存最多的进程及其占用量（来自 gpu-smi top 字段）。")
        lay.addWidget(self.top_lbl)

        self._sample_ready.connect(self._on_sample)
        self._sample_error.connect(self._on_error)
        threading.Thread(target=self._worker, daemon=True,
                         name="gpu-monitor").start()

    # ------------------------------------------------------------ 采样线程
    def _worker(self):
        try:
            import gpu_smi
        except ImportError:
            self._sample_error.emit(
                "未安装第三方库 gpu-smi，请执行：pip install gpu-smi")
            return
        except Exception as e:
            self._sample_error.emit(f"加载 gpu-smi 失败：{e}")
            return
        # 首次采样失败时重试几次：驱动初始化慢等瞬时故障不应永久放弃监控
        data = None
        for _ in range(3):
            if self._stop.is_set():
                return
            data = self._sample(gpu_smi)
            if data is not None:
                break
            self._stop.wait(1.0)
        if data is None:
            self._sample_error.emit(
                "gpu-smi 未查询到 GPU（无独立显卡或驱动异常）")
            return
        self._sample_ready.emit(data)
        while not self._stop.is_set():
            data = self._sample(gpu_smi)
            if data is not None:
                self._sample_ready.emit(data)
            self._stop.wait(GPU_POLL_INTERVAL)

    def _sample(self, gpu_smi):
        """一次采样。返回 (name, ratio, used_mb, total_mb, top)，
        各字段可为 None；查询失败返回 None。"""
        try:
            gpus = gpu_smi.gpus()
        except Exception:
            return None
        if not gpus:
            return None
        gpu = gpus[0]

        # ---- 显存占用率（官方确认的 API）----
        ratio = None
        try:
            r = gpu.usage_ratio
            if isinstance(r, (int, float)) and 0 <= float(r) <= 1:
                ratio = float(r)
        except Exception:
            ratio = None

        # ---- summary 文本（兜底数据源）----
        summary = ""
        try:
            summary = gpu.summary() or ""
        except Exception:
            summary = ""

        # ---- 已用 / 总显存：优先解析 summary，属性兜底 ----
        used_mb = total_mb = None
        m = _SUM_VRAM_RE.search(summary)
        if m:
            used_mb, total_mb = float(m.group(1)), float(m.group(2))
        if total_mb is None:
            total_mb = _to_number(_probe_attr(gpu, _ATTR_VRAM_TOTAL))
        if used_mb is None:
            used_mb = _to_number(_probe_attr(gpu, _ATTR_VRAM_USED))
        # 只有 ratio 和 total 时反推 used
        if used_mb is None and ratio is not None and total_mb:
            used_mb = total_mb * ratio

        # ---- 设备名：优先属性，summary 兜底 ----
        name = _probe_attr(gpu, _ATTR_NAME)
        if not isinstance(name, str) or not name.strip():
            m = _SUM_NAME_RE.search(summary)
            name = m.group(1).strip() if m else None

        # ---- top 进程（仅 summary 提供）----
        top = None
        m = _SUM_TOP_RE.search(summary)
        if m:
            top = (m.group(1), float(m.group(2)))

        return (name, ratio, used_mb, total_mb, top)

    # ------------------------------------------------------------ UI 更新
    @Slot(object)
    def _on_sample(self, item):
        name, ratio, used_mb, total_mb, top = item
        if name:
            self.gpu_name_lbl.setText(str(name))
        if used_mb is not None and total_mb:
            self._vram_total_mb = total_mb
            self.vram_lbl.setText(
                f"显存 {used_mb / 1024:.2f} / {total_mb / 1024:.2f} GB")
            self.vram_bar.setValue(min(int(used_mb / total_mb * 100), 100))
        elif ratio is not None:
            self.vram_lbl.setText(f"显存占用率 {ratio * 100:.1f}%")
            self.vram_bar.setValue(min(int(ratio * 100), 100))
        else:
            self.vram_lbl.setText("显存 -")
            self.vram_bar.setValue(0)
        self.top_lbl.setText(
            f"top: {top[0]} {top[1] / 1024:.1f}GB" if top else "")

    @Slot(str)
    def _on_error(self, msg):
        self.gpu_name_lbl.setText(f"GPU 监控不可用：{msg}")
        self.vram_lbl.setText("显存 - / -")
        self.top_lbl.setText("")
        self.vram_bar.setValue(0)

    # ------------------------------------------------------------ 对外接口
    def get_vram_total_gb(self):
        """返回 GPU 总显存（GB），未知返回 None。供参数编辑器 VRAM 预估使用。"""
        if self._vram_total_mb:
            return self._vram_total_mb / 1024
        return None

    def stop(self):
        self._stop.set()
