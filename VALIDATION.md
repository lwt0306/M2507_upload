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
本次没有修改下位机协议，也没有提交或推送 Git 更改。
