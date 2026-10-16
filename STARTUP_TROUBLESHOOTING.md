# EXE 命令行闪现后退出，主界面不出现

双击控制台版 EXE 时，进程一退出，Windows 就关闭它的控制台窗口。
因此“闪一下”只说明程序很快退出，不能单凭这一现象确定是 Tcl/Tk、串口模块还是 Windows DLL 的问题。
使用 `--windowed` 隐藏命令行窗口不会修复启动错误。

## 先让已有 EXE 保留报错

下载最新版完整仓库 ZIP，找到 `run_diagnostics.bat`。可将其放到原有 `M2507_OTA.exe` 旁后双击，
也可从已有 cmd 窗口指定原 EXE 的完整路径：

```bat
run_diagnostics.bat "D:\实际发布目录\M2507_OTA.exe"
```

诊断脚本会保存控制台输出、显示退出码并暂停，错误不会随着窗口消失。
旧版 EXE 也能用此脚本诊断；不必等重新打包完成。
如果主界面正常打开，需要关闭主界面后诊断脚本才会显示退出结果。

控制台输出保存到 `%TEMP%\M2507OTA\launch-console.log`。
新版程序另外保存：

- `%LOCALAPPDATA%\M2507OTA\startup.log`：最早的 Python runtime hook、依赖导入和未处理异常。
- `%LOCALAPPDATA%\M2507OTA\error.log`：进入应用启动函数后的界面初始化、回调异常。

`LOCALAPPDATA` 不可写时，启动日志会尝试 `%TEMP%\M2507OTA` 等临时目录。
Python DLL 加载前的原生启动器错误不可能被 Python 日志捕获，应查看诊断脚本的输出或 Windows 错误对话框。

## 本次确认并修复的构建缺口

已经核对 PyInstaller 4.10 官方代码并复现：

1. 构建 hook 无法探测 Tcl/Tk 数据目录时，会输出错误然后返回空数据列表，构建可能仍以成功结束。
2. 内置 Tk runtime hook 在应用源码执行前检查打包目录的 `tcl`、`tk`，缺少时直接抛异常。
3. 原来的 `main()` 日志晚于模块导入和 runtime hook，因此捕获不到这一层失败。

这证明旧流程存在实际防护缺口，**不等同于已经确定你这台电脑的具体报错**；
确定此次原因仍以实际控制台输出或启动日志为准。

新流程增加：

- 用实际 Tk 解释器报告的 `info library`、`tk_library` 取资源路径，验证目录属于当前 Conda 环境。
- 显式收集 `tcl`、`tk`、`tcl8` 数据，Python/Tcl/Tk DLL、固定 VC/UCRT 包拥有的 DLL，
  以及 `_ctypes` 真正导入的 libffi；不复制整个 Conda 环境或无关插件。
- 把当前 Conda 的 `Library/bin`、`DLLs` 加入打包依赖搜索路径，避免依靠未激活环境的 PATH。
- 在最早的自定义 runtime hook 中建立日志，检查必需 Tcl/Tk 资源，并保留 stdout/stderr。
- Tcl 初始化失败且 Tk 错误弹窗无法创建时，改用不依赖 Tk 的 Windows 原生错误弹窗。
- 串口枚举遇到驱动/注册表异常时保留主界面，在通信日志中显示错误，允许修复驱动后刷新。

运行依赖仍只有 pyserial 和 Python/Tk 原生运行库；没有增加 Qt、NumPy、pywin32 等应用依赖。
固定 VC 包去重后约 3.71 MB，一并内置可减少目标机对外部运行库的依赖。

## 重新打包和自检

解压最新版完整 ZIP 到新目录，进入该目录后执行：

```bat
conda activate m2507_win7
build_win7.bat debug
```

如果提示尚未安装构建依赖，先运行 `install_deps_win7.bat`。
没有变更之前锁定的 Python、PyInstaller 或离线 wheel 版本。

只有显示 `Build and isolated frozen-GUI startup passed` 或批处理最后的
`Build and isolated GUI startup check succeeded`，才表示实际 EXE 启动自检通过。
新流程不是仅检查进程号或端口：它会启动刚生成的 EXE，实际创建完整主界面及控件后自动退出，
同时要求退出码为 0 且输出 `M2507_GUI_SELF_TEST_OK`。
测试使用全新的临时配置目录、与 EXE 不同的工作目录，并清除 Conda、Python、Tcl/Tk 环境影响。
自检窗口自动退出是测试设计；不带 `--self-test` 启动时会保留主界面。

自检失败会使构建返回失败，并保存：

```text
build\win64\debug\self-test.stdout.log
build\win64\debug\self-test.stderr.log
build\win64\debug\self-test-profile-*\M2507OTA\startup.log
```

不要把本次构建失败后目录内遗留的旧 EXE 当作新产物。
若提示 Tcl/Tk 在 Conda 环境之外，应重新激活专用环境，检查是否手动设置了指向其他 Python 的
`TCL_LIBRARY`、`TK_LIBRARY`，不要混用另一个环境的资源路径。

构建成功后，输出文件夹仍为：

```text
dist\win64\debug\M2507_OTA\
  M2507_OTA.exe
  run_diagnostics.bat
  ... 所需 DLL 和资源目录 ...
```

完整复制这个文件夹到目标 Win7 SP1 x64 电脑，然后双击其中的 `run_diagnostics.bat` 验证。
验证正常后可运行 `build_win7.bat` 生成无控制台版，或 `build_win7.bat onefile` 生成单 EXE 版。
同目录的诊断 BAT 是辅助工具，不是 EXE 的运行依赖。

## 按实际报错区分原因

| 报错或现象 | 下一步 |
| --- | --- |
| `Tcl data directory ... not found`、缺 `init.tcl` / `tk.tcl` | 使用新版构建流程，并完整复制资源目录 |
| `DLL load failed while importing _tkinter` | 核对同一构建产物的 Tcl/Tk/VC DLL，查看 `startup.log` 的具体模块及系统错误 |
| `DLL load failed while importing _ctypes` | 新流程会显式收集当前 Conda 的 libffi，完整复制新产物后复测 |
| 错误仍指向 `python39.dll` | 正在运行旧版或另一个目录的 EXE；新构建应使用 `python38.dll` |
| `Can't find a usable init.tcl`、Tcl 版本冲突 | 查看资源路径及实际构建环境，避免混入其他 Python/Tcl 安装 |
| 无 Python 启动日志，加载器提示 DLL/入口点缺失 | 查看 `launch-console.log`、Windows 错误对话框；检查 Win7 SP1、KB2533623 及必要运行库更新 |
| 新日志中的其他 Python traceback | 以 traceback 的最后一条异常继续定位，不用猜测或反复升级依赖 |

构建机上的隔离自检通过，不能替代目标 Win7 的实际验证，也不能验证固件真机升级。
如果目标仍未打开界面，请提供 `launch-console.log` 的错误和退出码，或 `startup.log` 最后一个启动段落；
这些内容可以把“闪退”转为具体可复现的错误。
