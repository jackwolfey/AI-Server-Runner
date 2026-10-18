"""AI Server Runner —— llama-server / ComfyUI 图形控制面板（PySide6 版）。

由 tkinter 版 RunLlamaServerGUI.py 重构而来，功能完整保留：
- 双服务（llama-server / ComfyUI）进程管理、日志、就绪探测、崩溃诊断
- GPU 显存实时监控（gpu-smi）
- 可视化 llama-server 参数编辑器
- 模型目录浏览器（GGUF 元数据扫描）
- 预设配置管理 + 会话状态持久化
"""

__version__ = "1.1.0"
