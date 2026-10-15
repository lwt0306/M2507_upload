# 解决 pip 的 SSLEOFError 安装失败

截图显示 pip 请求 `https://pypi.org/simple/pyserial/` 时出现：

```text
SSLEOFError: EOF occurred in violation of protocol
Could not find a version that satisfies the requirement pyserial==3.5
```

第一条是实际故障：TLS 连接在读取包索引前被中断。
第二条是请求索引失败后的结果；**pyserial 3.5 确实存在，不需要改包版本**。
仅凭这张截图不能判定是证书过期、代理拦截还是网络连接问题。
这也与之前 `python39.dll` 不支持 Win7 的启动故障属于不同阶段。

## 推荐处理：直接使用仓库附带的离线包

1. [重新下载最新完整仓库 ZIP](https://github.com/lwt0306/M2507_upload/archive/refs/heads/main.zip)。
   解压后应有 `install_deps_win7.bat`、`verify_wheels.py`、
   `requirements-offline-win7.txt` 和 `wheelhouse_win7_x64` 文件夹。
   后者包含 9 个 `.whl` 文件及 `manifest.json`，不是 Git LFS 指针，无需额外下载。
   已使用 Git 克隆的用户可以 `git pull`；从 ZIP 解压的用户直接下载新版 ZIP。
2. 在 Conda Prompt 中进入最新版解压目录。例如沿用截图中的位置：

   ```bat
   cd /d D:\cim_research\m2507_project\M2507_upload-main
   conda activate m2507_win7
   install_deps_win7.bat
   ```

   不必先删除现有环境。脚本先检查 Python 3.8.10、64 位、Conda/Tk/VC 运行库，
   不符合要求会说明原因并停止。
3. 成功后继续构建：

   ```bat
   build_win7.bat debug
   ```

   输出为 `dist\win64\debug\M2507_OTA\M2507_OTA.exe`。
   完整复制 `M2507_OTA` 文件夹到 Win7 SP1 x64 电脑验证。
   确认正常后运行 `build_win7.bat` 生成无控制台文件夹版。

如果换一个目录解压，请将 `cd /d` 后面的路径改为实际位置。
检查终端显示的是新版目录，避免继续运行旧版在线安装命令。

## 离线安装执行的操作

所有 wheel 来自 PyPI 官方 HTTPS 下载，已与官方元数据中的 SHA256 核对。
清单保存在 `wheelhouse_win7_x64/manifest.json`；安装时再次验证文件大小及 SHA256，
并核对清单与 `requirements-offline-win7.txt` 一致。
文件缺失、损坏或锁定清单不一致时停止，不跳过校验。

实际 pip 命令为：

```bat
python verify_wheels.py
python -m pip --isolated --disable-pip-version-check install --no-index --find-links=wheelhouse_win7_x64 --only-binary=:all: --require-hashes --no-cache-dir -r requirements-offline-win7.txt
python -m pip check
python check_build_env.py
```

`--no-index` 使这一步不访问 PyPI 或其他包索引。
`--isolated` 避免用户 pip 配置和环境变量改变安装行为；版本检查也已关闭。
此方案没有更换 Python 版本、没有更改原方案锁定的依赖版本，也没有关闭 TLS 校验。
它解决 pip 安装，不会安装 Conda 自身或补齐尚未创建的 Python/Tk/VC 环境。

安装包总计 9 个，约 5.4 MB，其中 8 个是构建工具及其依赖。
应用运行时的第三方依赖仍只有 pyserial；终端用户运行生成的 EXE 不需要安装这些 wheel。

如果看到 `Missing wheel` 或校验失败，重新获取完整 ZIP；不要只修改哈希值使校验通过。

## 如需进一步恢复在线安装

离线安装不依赖这些检查，可以先完成构建。
若还希望恢复 PyPI 连接，再核对系统日期、网络/HTTPS 代理及组织证书策略。
Python 使用自己的 OpenSSL/CA 配置，不能仅凭 Internet Explorer 的 TLS 选项判断其状态。

以下命令仅显示工具版本或验证 HTTPS，不输出代理凭据：

```bat
python -m pip --version
python -c "import ssl; print(ssl.OPENSSL_VERSION)"
python -c "import urllib.request; print(urllib.request.urlopen('https://pypi.org/simple/pyserial/', timeout=15).status)"
```

若确认组织 HTTPS 代理需要自定义 CA，使用组织提供的可信 PEM 证书链，通过 pip 的
`--cert` 参数指定。不要使用 HTTP 源、`--trusted-host`、关闭证书验证，或为此升级到不支持 Win7 的 Python 3.9+。

离线 wheel 的目标依赖解析、全部 SHA256 和损坏文件拒绝测试已在云端完成；
Windows 批处理及生成 EXE 的目标机运行仍需在你的 Windows 环境执行，详见 `VALIDATION.md`。
