# M2507 双核串口固件升级工具

目标系统：**Windows 7 SP1 64 位**。运行时第三方依赖仅 `pyserial==3.5`，界面使用 Tkinter。
使用 Python 3.8.10 和 PyInstaller 4.10 作为兼容构建基线，EXE 需在实际 Win7 目标机验收。

## 快速开始

先[下载并解压最新完整 ZIP](https://github.com/lwt0306/M2507_upload/archive/refs/heads/main.zip)，
进入解压目录。在 Windows Conda Prompt 中创建环境；已经创建成功的环境不用重建：

```bat
conda create -n m2507_win7 --override-channels -c defaults python=3.8.10 tk=8.6.10 vs2015_runtime=14.27.29016 pip -y
conda activate m2507_win7
install_deps_win7.bat
build_win7.bat debug
```

仓库附带 9 个锁定的 Windows x64 wheel（约 5.4 MB），安装脚本验证 SHA256 后离线安装，
**pip 无需访问 PyPI**。Conda 环境的首次创建仍需要其包缓存或网络。
不要只下载 `.py` 文件或复制旧仓库中的几个脚本。

- [pip 安装报 SSLEOFError 的解决步骤](PIP_TLS_FIX.md)
- [EXE 闪退、主界面不出现的修复与日志获取](STARTUP_TROUBLESHOOTING.md)
- [完整 Conda 打包、发布及 Win7 运行库排查说明](README_WIN7.md)
- [测试结果与尚未完成的目标机验收](VALIDATION.md)

目前不提供预编译 Windows EXE；在 Windows 构建后，复制完整的产物文件夹到目标电脑。
构建脚本会实际启动生成的 EXE 并检查完整 GUI；通过后附带 `run_diagnostics.bat`，
目标电脑启动失败时使用它保留控制台输出和退出码。
