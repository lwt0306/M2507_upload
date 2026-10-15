# 本次验证记录

目标平台：用户确认的 **Windows 7 SP1 64 位**。
执行平台：Linux x86_64 云端，未连接 M2507 硬件。

## 通过的检查

- Python 3.12.14 / Tcl-Tk 9.0 / pyserial 3.5，Xvfb 下运行：
  `python -m unittest discover -s tests -v`，**13 项通过，无跳过**。
  包括实际 Tk 界面的创建、读取中文路径固件、模拟打开串口、完整升级、按钮状态恢复和关闭串口。
- Python 3.8.20 / pyserial 3.5：**12 项协议和任务控制测试通过，1 项 GUI 测试在无 DISPLAY 运行时跳过**。
  这是 Python 3.8 系列的源码运行验证，不等同于 Windows Python 3.8.10 的二进制兼容验证。
- 所有交付 `.py` 文件按 Python 3.8 语法解析通过。
- Python 3.8 测试环境安装了锁定的 PyInstaller 4.10 / hooks 2022.3 等构建依赖，
  `python -m pip check` 通过。
- 使用 Windows x64 / Python 3.8.10 目标条件解析 `requirements-build-win7.txt`，
  9 个锁定包的依赖解析通过，二进制 wheel 可用。
- 从 Anaconda 官方 win-64 元数据确认存在 Python 3.8.10、Tk 8.6.10、
  vs2015_runtime 14.27.29016 包。
- `check_build_env.py` 在当前不符合要求的 Linux 环境返回非零，明确阻止在错误平台、
  错误解释器或非 Conda 环境下打包；这是预期的保护检查。

串口模拟覆盖以下行为：

1. Core0/Core1 信息帧长度、核 ID、固件长度与 CRC32 的小端编码。
2. 128/512/1024 字节分包，接收端核对所有固件字节、总长度和 CRC32。
3. 带噪声及分段到达的 ACK。
4. 同一次接收的 CRC/Flash ACK 保留到下一等待阶段。
5. 四类设备错误帧、错误帧先于成功帧的处理、超时与取消。
6. 不完整串口写入报错。
7. 后台线程不得访问 Tkinter 对象或变量。
8. 停止过程中禁止启动第二个线程，升级期间锁定相关控件。

## 云端旧版 Tk 的限制

另外尝试 Python 3.8.20 自包含 Linux 发行版的 Tcl/Tk 8.6.12 GUI 测试。
补齐该发行版的 Tcl/Tk 库搜索路径后，中文字体渲染触发了原生 XCB 断言并中止进程。
不加载本应用、只执行 `tk.Label(root, text="M2507双核串口固件升级工具", font=("Microsoft YaHei UI", 20, "bold"))`
也能复现，英文标签则可正常创建。

因此，这一组合的中文 GUI 检查记录为**失败，已定位到云端 Linux 图形组件**，不记为通过，
不通过修改应用字体、删掉中文、屏蔽测试或断言来规避。
前述 Python 3.12/Tk 9 的完整 GUI 测试已通过。
XCB 是 Linux 图形组件，Win7 使用另一套图形后端；本次没有据此声称 Win7 通过或失败。

## 未执行的验收

- Windows Conda 环境的实际创建、Win7 x64 EXE 构建和启动。
- Windows 上 `build_win7.bat` 的实际执行及 `onedir` / `onefile` 产物检查。
- 目标 Win7 补丁、VC/UCRT 运行库、USB 转串口驱动及目标机权限检查。
- M2507 真机上电握手、真实串口传输和 Flash 写入/回读。

未提供预编译 EXE。请按 `README_WIN7.md` 在 Windows 构建并完成目标机验收后分发。
下位机通信协议保持不变。

## pip TLS 错误的离线安装补充验证

针对后续报告的 `SSLEOFError`，增加完整的 Windows x64 wheelhouse、哈希锁定文件和
`install_deps_win7.bat`；现有上位机源码及原有依赖版本保持不变。

- 9 个 wheel 全部通过 PyPI 官方 HTTPS 获取，并与官方 JSON 元数据的 SHA256 和文件大小核对；
  总大小 5,381,132 字节。包内 ZIP 完整性及发行版本元数据已检查。
- `verify_wheels.py` 在 Python 3.8.20 上核对全部 wheel 和离线 requirements 一致，通过。
- 新增 4 项测试全部通过：实际离线包可验证，缺失 wheel 被拒绝，等长内容损坏被拒绝，
  manifest 与 requirements 版本不一致被拒绝。
- 使用 pip 23.3.2、`--no-index --require-hashes` 及 Windows x64 / Python 3.8 目标条件，
  从本地 wheelhouse 完成全部 9 包的离线依赖解析和下载。
- 进一步使用 `--platform win_amd64 --target <临时目录> --ignore-installed --no-compile`，
  从本地文件完成安装提取；安装后核对 9 个发行版名称/版本均一致，Windows `runw.exe` 引导程序存在。
  临时目录验证后删除，不污染运行中的 Linux Python 环境。
- 新增/修改的 Python 脚本按 Python 3.8 语法解析通过；Windows 批处理保持 CRLF 换行。

上述安装提取运行于 Linux，验证的是离线文件、依赖解析及安装内容，不是 Windows 原生执行。
当前没有用户电脑的网络/代理配置，不能由截图确定 TLS 中断的具体来源。
此更新让 pip 安装直接使用已校验的本地文件，免去该网络连接，未关闭 TLS 或哈希校验。
Windows 上批处理的实际执行、EXE 构建和 Win7/真机验收仍需在目标环境完成。
