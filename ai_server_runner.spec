# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— AI Server Runner（单文件 exe，尽量减小体积）。

用法：双击 build_exe.bat，或手动执行：
    python -m PyInstaller --clean --noconfirm ai_server_runner.spec
输出：dist/AI Server Runner.exe（单文件，可直接拷走使用）

体积优化手段：
  1. excludes 排除程序用不到的标准库 / 第三方大模块
  2. 删除 Qt 自带的翻译文件（约 4~6 MB，界面文案是硬编码中文用不到）
  3. 删除用不到的 Qt 图像格式插件（png/bmp 由 QtGui 内置，无需外部插件；
     仅保留 gif / ico / jpeg；qpdf、qtiff、qwebp、qsvg 等均较占体积）
  4. 若命令行能找到 UPX（upx.exe 在 PATH 中），自动压缩依赖 DLL/pyd，
     可再缩小约 30%~50%；vcruntime / Python 运行时已排除以防启动异常
"""

import os

# 程序图标 + gpu-smi 库捆绑的原生查询程序。
# gpu_smi/bin/gpu-smi.exe 是 wheel 里的数据文件，打包器默认只收集 .py，
# 缺了它打包后就会报「GPU 监控不可用：未查询到 GPU」，必须手动带上。
_datas = [("app_icon.ico", ".")]
try:
    import gpu_smi
    _gs_bin = os.path.join(os.path.dirname(gpu_smi.__file__),
                           "bin", "gpu-smi.exe")
    if os.path.isfile(_gs_bin):
        _datas.append((_gs_bin, "gpu_smi/bin"))
except ImportError:
    pass  # 构建环境未装 gpu-smi：按原行为打包（运行时会提示未安装）

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ---- 标准库中确定用不到的部分（程序仅用 json/os/re/sys/threading/
        #      subprocess/ctypes/queue/struct/tempfile/datetime/webbrowser/
        #      urllib 等小模块，勿在此列入可能被 PySide6 或 gpu_smi 依赖的库）----
        "tkinter", "unittest", "test", "pydoc_data", "lib2to3", "curses",
        "pdb", "doctest", "sqlite3", "xml", "xmlrpc", "distutils",
        "setuptools", "pip", "pkg_resources", "wheel",
        # ---- 未安装 / 未使用的第三方库，防止环境里恰好装了被误打包 ----
        "PyQt5", "PyQt6", "matplotlib", "numpy", "scipy", "PIL",
    ],
    noarchive=False,
)


def _norm(p):
    return p.replace("\\", "/").lower()


def _keep(entry):
    """返回 False 表示从包里剔除该文件。"""
    p = _norm(entry[0])
    if "pyside6/translations/" in p:          # Qt 翻译
        return False
    if "iconengines/" in p and "qsvg" in p:   # SVG 图标引擎（未用 SVG 图标）
        return False
    if "imageformats/" in p:                  # 图像格式插件：仅保留常用三种
        name = p.rsplit("/", 1)[-1]
        return name.startswith(("qgif", "qico", "qjpeg"))
    return True


a.datas = [x for x in a.datas if _keep(x)]
a.binaries = [x for x in a.binaries if _keep(x)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AI Server Runner",
    debug=False,
    icon="app_icon.ico",  # exe 文件图标（资源管理器 / 任务栏显示）
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # UPX 压缩这些 DLL 容易导致启动崩溃 / 杀毒软件误报，排除掉
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "python3*.dll",
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
