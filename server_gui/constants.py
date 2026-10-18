"""全局默认配置、正则与 llama-server 参数 Schema。"""

import os
import sys

# ============================ 默认配置（对应原 bat） ============================
DEFAULT_WORKDIR = r"D:\Software\llama.cpp_rocm10"
DEFAULT_EXE = "llama-server.exe"
DEFAULT_MODEL = (
    r"D:\Data\LLM Models\Heretic\Qwen3.8-27B-Heretic-Ara-iq4_xs-3.0-mtp"
    r"\Qwen3.8-27B-Heretic-Ara-iq4_xs-3.0-mtp.gguf"
)

# 除 --model 外的其它参数，每行一个（这样带空格的参数值不会被拆错）
DEFAULT_EXTRA_ARGS = "\n".join([
    "-ngl", "99",
    "-c", "80000",
    "-fa", "on",
    "-np", "1",
    "--spec-type", "draft-mtp",
    "--reasoning-budget", "16384",
    "--reasoning-budget-message",
    # 与 bat 保持一致：这里是「字面量」的 \n\n。
    r"\n\n[Reasoning budget exhausted. Stop thinking and move next immediately.]",
])

DEFAULT_LLAMA_PORT = "8080"

# ============================ ComfyUI 默认配置 ============================
DEFAULT_COMFY_PYTHON = r"D:\Software\miniconda\envs\rocm\pythonw.exe"
DEFAULT_COMFY_MAIN = r"D:\Data\Self_Project\ComfyUI\main.py"
DEFAULT_COMFY_ARGS = "--enable-manager --listen 127.0.0.1 --port 8188"
DEFAULT_COMFY_PORT = "8188"

# 预设配置文件名（保存在工作目录中）
PRESET_FILENAME = "llama_gui_presets.json"

# 会话状态文件名（记录上次输入与窗口尺寸）
STATE_FILENAME = "llama_gui_state.json"


def program_dir():
    """程序所在目录（持久化文件 llama_gui_state.json 的存放位置）。

    源码方式运行时为 main.py 所在目录；PyInstaller 打包后 __file__ 指向
    每次启动都不同的临时解压目录（_MEIxxxx），因此改用 exe 自身所在
    目录，保证状态文件跟随着 exe、重启后仍能恢复。
    """
    if getattr(sys, "frozen", False):  # PyInstaller 打包环境
        return os.path.dirname(os.path.abspath(sys.executable))
    # 源码运行：constants.py 位于 <项目>/server_gui/ 下，上一级即项目目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 主窗口标题
BASE_TITLE = "llama-server / ComfyUI 控制面板"

# 子进程输出编码。若 llama-server 输出乱码，可改为 "mbcs"（Windows 系统编码）
LOG_ENCODING = "utf-8"
LOG_ERRORS = "replace"

import re

ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')

# 日志行错误关键字（命中即红字高亮）
LOG_ERR_RE = re.compile(
    r"\b(?:error|fatal|failed|abort|exception)\b|"
    r"out ?of ?memory|hiperror|cudaerror|outofmemory",
    re.IGNORECASE)

# 崩溃特征 → 人话诊断（进程异常退出时按顺序匹配第一条命中项）
CRASH_DIAGNOSES = [
    (re.compile(r"out of (?:device )?memory|hipErrorOutOfMemory|"
                r"cudaErrorMemoryAllocation|failed to allocate", re.I),
     "疑似显存不足（OOM）：可降低 -ngl 层数 / 调小 -c 上下文，"
     "或更换更小量化模型。"),
    (re.compile(r"(?:failed|error|unable)[^\n]{0,60}"
                r"(?:load|loading)[^\n]{0,20}model|"
                r"invalid model (?:file|magic)|corrupt", re.I),
     "疑似模型加载失败：请检查模型路径与文件完整性"
     "（多分片 GGUF 需指向第一个分片）。"),
    (re.compile(r"address already in use|only one usage of each socket|"
                r"(?:failed|error)[^\n]{0,30}bind", re.I),
     "疑似端口被占用：请更换 --port，或结束占用该端口的进程。"),
    (re.compile(r"hipErrorNoDevice|no CUDA|hipblas|rocblas|"
                r"failed to init", re.I),
     "疑似 GPU / 驱动初始化失败：请检查显卡驱动与 ROCm 环境是否匹配。"),
]

# llama-server 启动成功时在日志中广播监听地址：
#   main: server is listening on http://127.0.0.1:8080 - starting the main loop
LLAMA_LISTEN_RE = re.compile(
    r"listening on\s+(https?://[^\s\"']+)", re.IGNORECASE)

# GPU 监控采集间隔（秒）
GPU_POLL_INTERVAL = 1.5
