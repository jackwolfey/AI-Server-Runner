# AI Server Runner

llama-server / ComfyUI 图形控制面板（PySide6 版），将原本需要手动编辑 bat 的
本地大模型服务启动流程整合为一个桌面程序。

## 功能特性

- **双服务管理**：llama-server 与 ComfyUI 各一个控制面板，可分别启动 / 停止，
  就绪后自动探测服务端口并高亮提示，支持一键打开浏览器
- **实时日志**：ANSI 转义清洗、错误行红色高亮、进程崩溃后自动给出
  人话诊断（OOM / 模型加载失败 / 端口占用 / GPU 初始化失败等）
- **GPU 监控条**：基于 gpu-smi 的显卡占用率与显存实时显示
- **预设配置**：参数方案按名称保存 / 加载，支持右键重命名、删除，以及
  拖动调整顺序（保存在工作目录 `llama_gui_presets.json`）
- **可视化参数编辑器**：主界面参数以表单形式编辑，其余参数逐行手动维护，
  内置常用参数快捷添加（--mmproj、--cache-type-k/v、--jinja 等）
- **模型库**：浏览工作目录内的 GGUF 模型文件，解析元数据（架构、量化、
  上下文长度、分片等），双击即可填入模型路径
- **主题**：深色 / 浅色两套界面主题，选择持久化
- **会话持久化**：窗口尺寸、各输入框内容、上次主题在重启后自动恢复
  （保存在程序同目录 `llama_gui_state.json`）

## 环境要求

- Windows 10 / 11（进程管理部分依赖 Windows API）
- Python 3.10+
- [llama.cpp](https://github.com/ggml-org/llama.cpp) 的 `llama-server.exe`
- 可选：ComfyUI（不使用可忽略对应面板）
- 支持 CUDA / ROCm 的显卡（llama-server 自身的要求，本程序不直接调用 GPU）

## 安装与运行

```bat
pip install -r requirements.txt
python main.py
```

首次启动后在工作目录填入 `llama-server.exe` 路径与模型 gguf 路径即可。
默认配置面向的典型环境（可在界面上修改）：

| 配置项 | 默认值 |
|---|---|
| 工作目录 | `D:\Software\llama.cpp_rocm10` |
| llama-server | `llama-server.exe` |
| 端口 | 8080 |
| ComfyUI python | `D:\Software\miniconda\envs\rocm\pythonw.exe` |

## 打包为 exe

双击 `build_exe.bat`（自动安装 PyInstaller、检测 UPX 并压缩），或手动执行：

```bat
pip install pyinstaller
python -m PyInstaller --clean --noconfirm ai_server_runner.spec
```

产物为单文件 `dist\AI Server Runner.exe`，图标已内置，可直接拷贝使用；
状态文件 `llama_gui_state.json` 会生成在 exe 所在目录。

## 项目结构

```
ai_server_runner/
├── main.py                  # 启动入口（主题加载、窗口图标）
├── server_gui/
│   ├── main_window.py       # 主窗口：布局 / 预设 / 命令构造 / 会话持久化
│   ├── process_panel.py     # 单服务控制面板：进程、日志、就绪探测
│   ├── param_editor.py      # 可视化参数编辑器
│   ├── model_library.py     # 模型库对话框
│   ├── gpu_monitor.py       # GPU 监控条（gpu-smi）
│   ├── presets.py           # 预设配置存取
│   ├── gguf.py              # GGUF 元数据解析
│   ├── theme.py             # 深色 / 浅色主题与主题对话框
│   ├── winprocess.py        # Windows 进程辅助（命令行拆分、Job 对象清理）
│   └── constants.py         # 默认配置、正则、诊断规则
├── app_icon.ico             # 程序图标
├── build_exe.bat            # 一键打包脚本
└── ai_server_runner.spec    # PyInstaller 打包配置（体积优化）
```

## 配置文件

| 文件 | 位置 | 说明 |
|---|---|---|
| `llama_gui_state.json` | 程序（exe）同目录 | 会话状态：窗口尺寸、输入内容、主题。自动生成，勿手动编辑 |
| `llama_gui_presets.json` | 工作目录 | 预设配置，可随工作目录携带、跨机器复制 |

## 已知注意事项

- 若 llama-server 输出乱码，可将 `server_gui/constants.py` 中
  `LOG_ENCODING` 改为 `"mbcs"`
- 打包后的 exe 需放在**可写目录**（如 `D:\Software\...`）才能保存状态文件；
  放入 `C:\Program Files` 等只读目录会导致配置无法持久化

## 作者与版本

- 作者：WindJ
- 当前版本：v1.1.0
