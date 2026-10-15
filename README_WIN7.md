# M2507 上位机：Windows 7 SP1 64 位修复与 Conda 打包

**如果安装依赖时遇到 `SSLEOFError`：下载最新版完整仓库 ZIP，在现有 Conda 环境中运行
`install_deps_win7.bat`。仓库已附带 Windows x64 离线 wheel，不再要求 pip 连接 PyPI。**
具体步骤和错误原因见 [pip TLS 错误解决方法](PIP_TLS_FIX.md)。

## 1. 截图故障的原因

截图报错发生在 PyInstaller 启动器加载 `python39.dll` 时，Python 源码尚未执行。
Python 3.9 官方支持 Windows 8.1 及以上，不支持 Windows 7。
因此，即使 EXE 在 Windows 10/11 上正常，也不能直接用于 Windows 7。

必须用兼容解释器重新打包整个程序。修改源码或重新运行原来的 Python 3.9 打包命令，
均不能解决这个加载阶段的问题。不要把 `python38.dll` 改名成 `python39.dll`，
也不要从第三方 DLL 下载站下载系统 DLL；二者不能互换。
`_MEI...` 是 PyInstaller 单文件版的正常解压目录，本身不是故障原因。

本方案针对用户确认的 **Windows 7 SP1 x64**，使用以下兼容基线：

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.8.10，64 位 | 支持 Win7 的 Python 3.8 系列；固定到有官方 Windows 安装包的版本 |
| pyserial | 3.5 | 唯一第三方运行依赖 |
| Tk | Conda 包 8.6.10 | Tkinter 的原生界面库 |
| vs2015_runtime | Conda 包 14.27.29016 | 限制构建环境的 VC 运行库，避免自动选入过新的版本 |
| PyInstaller | 4.10 | 旧版兼容打包基线，仅构建时需要 |
| pyinstaller-hooks-contrib | 2022.3 | 与旧版打包器配套的构建钩子 |

PyInstaller 4.10 文档对 Win7 的表述是“should work too, but is not supported”。
这里使用它作为保守兼容基线，不把它描述为 Win7 的官方支持保证。
最终 EXE 必须按下文在实际 Win7 目标机验收。

## 2. 已修复的源码问题

修复文件为 `M2507_dual_core_ota_scrollable.py`，保持原文件名及界面，不改固件协议、
Core0/Core1 定义、长度/CRC 小端格式、分包默认值或发送节流。

- 升级线程不再读取 Tkinter 变量或调用 `root.after`；启动时固定分包大小，弹窗交由主线程处理。
- 停止请求使用 `threading.Event`。旧线程结束前保持任务占用状态，防止再次启动导致两个线程共用串口。
- 升级期间锁定固件选择、目标核及串口开关，保证信息帧与后续固件数据一致。
- 接收缓存跨等待阶段保留；CRC 和 Flash 两个 ACK 连续到达时不再丢失后一个。错误帧按接收顺序处理。
- 超时使用单调时钟，避免系统时间校准影响等待；发送不完整时明确报错。
- 无控制台版的启动及界面回调异常写入 `%LOCALAPPDATA%\M2507OTA\error.log`，并限制日志大小。
  这份日志只能记录 Python 启动后的异常，不能捕获 `python*.dll` 加载失败。

## 3. 创建独立 Conda 构建环境

在 **64 位 Windows 的 Anaconda Prompt / Miniconda Prompt（cmd）**中，进入本文件所在目录。
不要在安装大量科学计算包的 `base` 环境里直接打包。

```bat
conda create -n m2507_win7 --override-channels -c defaults python=3.8.10 tk=8.6.10 vs2015_runtime=14.27.29016 pip -y
conda activate m2507_win7
install_deps_win7.bat
```

也可用 `conda env create -f environment-win7.yml` 替代第一行创建命令，之后步骤相同。
如果已有同名环境，请使用一个新的环境名称；不要继续使用原来的 Python 3.9 环境。
**如果已经按本说明成功创建了 `m2507_win7`，只需激活它并运行离线安装脚本，无需再次创建环境。**
Conda 的 Python/Tk/VC 环境创建本身仍需要其包缓存或联网；离线 wheel 解决的是环境创建后的 pip 安装。
离线安装脚本会检查环境、验证全部 wheel 的大小和 SHA256，然后通过 `--no-index --require-hashes`
安装锁定依赖，并执行 `pip check` 和完整的构建环境检查。
wheel 共 9 个，约 5.4 MB；来源及官方 PyPI SHA256 保存在 `wheelhouse_win7_x64/manifest.json`。

如果构建机能正常访问 PyPI，也可以使用原有在线安装方式：

```bat
python -m pip install --only-binary=:all: -r requirements-build-win7.txt
python -m pip check
python check_build_env.py
```

`check_build_env.py` 会确认解释器、Conda 运行库、打包器和钩子版本，并实际初始化 Tkinter。
它会报告当前解释器的位数；本次目标应显示 **64-bit**。

版本锁定用于防止无意升级，不要执行无版本限制的 `pip install -U pyinstaller` 或 `conda update --all`。
如需变更某个版本，应重新验收目标 Win7 机器。

可以在现有 Windows 10/11 的 64 位 Conda 机器上执行上述构建步骤，但产物仍须在 Win7 上测试。
若遇到构建机引入的原生 DLL 兼容差异，使用匹配目标的 Win7 SP1 x64 虚拟机构建复核；
此时需要能在 Win7 运行的历史版本 Conda，不能使用最新 Conda 安装器。
目标使用电脑本身不需要安装 Conda。

## 4. 生成 EXE

首次建议生成有控制台的文件夹版，便于查看启动诊断：

```bat
build_win7.bat debug
```

输出为 `dist\win64\debug\M2507_OTA\M2507_OTA.exe`。

验证正常后，生成无控制台文件夹版：

```bat
build_win7.bat
```

输出为 `dist\win64\onedir\M2507_OTA\M2507_OTA.exe`。
将**整个 `M2507_OTA` 文件夹**复制到目标电脑，不能只复制其中的 EXE。
不要删除其中的 Python、Tcl/Tk、VC 运行库或其他已收集文件。

如果必须交付单个 EXE，在文件夹版通过 Win7 验收后运行：

```bat
build_win7.bat onefile
```

输出为 `dist\win64\onefile\M2507_OTA.exe`。
单文件模式仍含有相同运行库，只是启动时解压到临时目录；并不会减少真实运行依赖，
还需要目标用户有可写的临时目录。故障排查时优先使用 `debug` / `onedir`。

脚本会先执行环境检查、依赖一致性检查和现有自动化测试，失败即停止。
它采用 `--noupx`，不依赖 UPX；也不使用 `--collect-all` 收入整个 Conda 环境。
如果手工执行 PyInstaller，必须在这个专用环境里使用 `python -m PyInstaller`，
避免 PATH 中另一个环境的 `pyinstaller.exe` 被调用。

## 5. 尽量减少依赖的方法

正常运行只需 `pyserial==3.5`，其余业务代码均使用标准库。
Tkinter 在 Python/Conda 中提供，不执行 `pip install tkinter`。
不需要 NumPy、Pandas、Matplotlib、Qt、PySide、pywin32、Anaconda 全量包或额外串口库。
构建工具中的 `pywin32-ctypes` 不是完整的 `pywin32` 包，也不是应用直接依赖。

只运行源码而不打包时，在上述 Python/Tk/VC 环境中安装：

```bat
python verify_wheels.py
python -m pip --isolated --disable-pip-version-check install --no-index --find-links=wheelhouse_win7_x64 --only-binary=:all: -r requirements-win7.txt
python M2507_dual_core_ota_scrollable.py
```

PyInstaller、pefile、hooks、setuptools 等锁定包属于构建工具。
不要把整个 Conda 环境复制给终端用户；只分发 PyInstaller 的产物。
保留 Tkinter 和相应原生 DLL 是维持现有图形界面所必需的。

## 6. Win7 SP1 x64 目标机验收与排查

1. 确认目标为 Win7 SP1 64 位，先将完整 `debug` 产物复制到目标电脑并启动。
   不要从旧的 Python 3.9 发布目录混入文件。
2. 确认窗口能打开、滚动，能够选择 Bin 文件，显示长度和 CRC；无串口时应正常显示“未发现串口”。
3. 安装该 USB 转串口芯片的 **Win7 兼容驱动**，确认设备管理器出现 COM 口并能由程序打开。
4. 使用可用于升级测试的设备与对应固件，分别验证 Core0/Core1、设备重启握手、
   完整发送、CRC/Flash 成功确认，以及停止后不能产生并行升级任务。
5. 再测试 `onedir` 无控制台版；如需 `onefile`，也必须单独在目标电脑启动和升级验证。

若仍出现 Python DLL 或运行库加载错误：

- 新产物应使用 `python38.dll`。若错误仍指向 `python39.dll`，说明启动的还是旧 EXE。
- 确认 `debug` / `onedir` 目录完整；文件夹版中缺失 `python38.dll` 表示复制或打包不完整。
- 核对 Win7 的 **KB2533623**（DLL 加载 API）与 **KB2999226**（Universal CRT）或包含它们的后续更新。
  已被汇总更新取代的补丁无需重复安装。Python 3.8 的嵌入式分发文档明确指出 Win7 需要 KB2533623。
- 如提示缺少 VC 运行库，使用微软官方的 **Win7 兼容版本 Visual C++ 2015–2019 x64（14.29 系列）**，
  而非直接下载要求更新 Windows 的最新运行库。环境固定的 14.27 DLL 可减少此类差异，
  但不能替代目标系统的 UCRT/加载 API 补丁。
- 已进入界面后再出错，查看 `%LOCALAPPDATA%\M2507OTA\error.log`；
  串口升级失败的协议细节同时显示在界面通信日志里。

## 7. 验证范围

本次云端为 Linux，已使用真实 Tk 界面和模拟串口设备验证升级过程；详细结果见 `VALIDATION.md`。
这里没有 Windows 构建机或真实 M2507 设备，因此未生成或声称验证 Windows EXE，
也未声称完成实际 Flash 烧写。Windows EXE 必须在 Windows 上构建，不能把 Linux 打包产物改名成 `.exe`。

可在准备好的 Windows 构建环境里重复运行测试：

```bat
python -m unittest discover -s tests -v
```

参考依据：

- [Python 3.9 官方 Windows 文档：需要 Win7 请使用 Python 3.8](https://docs.python.org/3.9/using/windows.html)
- [Python 3.8.10 官方发布页及 Windows 安装包](https://www.python.org/downloads/release/python-3810/)
- [Python 3.8 官方 Windows 文档：Win7 与 KB2533623](https://docs.python.org/3.8/using/windows.html)
- [PyInstaller 4.10 官方要求说明](https://github.com/pyinstaller/pyinstaller/blob/v4.10/doc/requirements.rst)
- [微软 VC 运行库与受支持平台说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

官方文档网页在本次云端部分受网络策略限制；相关 Python/PyInstaller 文档内容已通过其官方 GitHub 源码核对。
