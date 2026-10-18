"""Windows 进程树管理（Job Object / taskkill）与命令行拆分工具。"""

import ctypes
import os
import subprocess

# ---------------------------------------------------------------------------
# Job Object：把子进程加入「句柄关闭即全灭」的 Job，主程序崩溃也不会留下孤儿进程
# ---------------------------------------------------------------------------
if os.name == "nt":
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        _kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.SetInformationJobObject.restype = ctypes.c_int
        _kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p]
        _kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        _kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.TerminateJobObject.restype = ctypes.c_int
        _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        _kernel32.CloseHandle.restype = ctypes.c_int
    except Exception:
        _kernel32 = None
else:
    _kernel32 = None

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _create_kill_on_close_job():
    """创建「最后一个句柄关闭时终止全部成员进程」的 Job 对象。"""
    if _kernel32 is None:
        return None
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info)):
        _kernel32.CloseHandle(job)
        return None
    return job


def _assign_to_job(job, proc):
    if not job:
        return False
    try:
        return bool(_kernel32.AssignProcessToJobObject(job, int(proc._handle)))
    except Exception:
        return False


def _terminate_job_tree(job, exit_code=1):
    if job and _kernel32:
        try:
            _kernel32.TerminateJobObject(job, exit_code)
        except Exception:
            pass


def _close_job_handle(job):
    if job and _kernel32:
        try:
            _kernel32.CloseHandle(job)
        except Exception:
            pass


def win_cmdline_split(s: str):
    """按 Windows 命令行规则把字符串拆分为参数列表。"""
    argv, buf = [], []
    has_arg = False
    in_quotes = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            j = i
            while j < n and s[j] == "\\":
                j += 1
            nbs = j - i
            if j < n and s[j] == '"':
                buf.append("\\" * (nbs // 2))
                if nbs % 2:
                    buf.append('"')
                else:
                    in_quotes = not in_quotes
                    has_arg = True
                i = j + 1
            else:
                buf.append("\\" * nbs)
                i = j
            continue
        if c == '"':
            in_quotes = not in_quotes
            has_arg = True
            i += 1
            continue
        if c in " \t" and not in_quotes:
            if has_arg or buf:
                argv.append("".join(buf))
                buf = []
                has_arg = False
            i += 1
            continue
        buf.append(c)
        has_arg = True
        i += 1
    if has_arg or buf:
        argv.append("".join(buf))
    if in_quotes:
        raise ValueError("引号未闭合")
    return argv


def kill_tree_by_pid(pid: int):
    """Job 不可用时的兜底：taskkill 强杀进程树。"""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    except Exception:
        pass
