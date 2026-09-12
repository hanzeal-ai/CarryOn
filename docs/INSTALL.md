# 安装与首次使用

CarryOn 0.2 面向 macOS。安装包包含 Python 和控制台，用户不需要安装 Python、Node、npm 或 pip。Codex App 必须已安装、登录并运行；目前内部 IPC 记录的验证版本为 26.901.51231。其他版本需通过隔离会话重新验收。

## 普通用户：Mac 应用

1. 选择与你的 Mac 架构匹配的 `CarryOn-版本-macos-arm64.dmg`（Apple Silicon）或 `x86_64.dmg`（Intel，需在对应环境构建）。
2. 打开 DMG，将 `CarryOn.app` 拖入 Applications。
3. 双击 CarryOn，打开独立的桌面配置窗口（macOS 13+）。点击「启动服务」，或查看 CLI 已启动的同一服务。
4. 在桌面端打开「连接本机 Codex」，使用「打开会话页面」查看记录和继续任务。
5. 要创建新任务，先在 Codex App 建立专用空闲控制会话，在桌面端填写其 ID，点击「设为控制会话」，或使用 `carryon controller set --thread-id 会话ID`。

桌面端直接配置云端连接、每个绑定的远程控制权限、桥接、待机和控制会话。它调用与独立 CLI 相同的命令和服务，不保存另一份配置。默认数据目录相同，CLI 改动会在桌面端刷新显示；使用 CLI 自定义数据目录时，在桌面端选择同一目录。

关闭窗口不停止服务，停止服务使用桌面端按钮或 `carryon stop`。本地网页只用于会话交互，不承担配置。没有默认开机自启。

当前本机构建产物仅作开发/内部验收：PyInstaller 使用 ad-hoc 签名，尚未完成 Apple Developer ID 签名、公证及其他干净设备验收。对外分发前必须完成这些步骤；不要要求用户关闭系统安全保护。没有提供的架构包不能视为已支持。

## 开发者：独立 CLI

解压对应的 `CarryOn-版本-macos-架构-cli.tar.gz`，保留整个文件夹，不能只复制其中的可执行文件。进入文件夹后运行：

```sh
sh ./install.sh
"$HOME/.local/bin/carryon" start
```

安装不使用 sudo，也不会修改 shell 配置。如 `~/.local/bin` 已在 PATH 中，可直接使用 `carryon`。也可以不安装，直接执行解压目录中的 `./carryon start`。

```sh
carryon start             # 后台启动并打开本地控制台
carryon start --no-open   # 仅启动 API
carryon open              # 重新打开已配对页面
carryon status            # 查看服务实例与桥接状态
carryon doctor            # 检查平台、数据目录和 IPC socket
carryon stop              # 认证后停止服务，不根据旧 PID 杀进程
```

端口默认为 8769。被其他程序占用时会报错，不会静默切换地址。可以显式选择 `carryon start --port 8770`。重复启动复用现有实例，端口参数不会更改正在运行的服务；调整需先 stop。

## Python 包与源码

面向已有 Python 3.10+ 的开发者，本项目也提供 wheel；包名为 `carryon-local`，命令为 `carryon`。当前没有发布到 PyPI，不能假设公共仓库中同名包属于本项目。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /实际下载路径/carryon_local-0.2.0-py3-none-any.whl
.venv/bin/carryon start
```

源码根目录无需安装依赖即可运行：

```sh
python3 -m carryon start
# 或前台运行，Ctrl+C 停止：
python3 -m carryon serve
```

`python3 -m carryon.server` 仍是前台入口，但不再向日志输出配对 Token。使用 `python3 -m carryon open` 打开控制台。不要直接双击 example.html。

## 数据、升级与恢复

所有入口默认使用 `~/Library/Application Support/CarryOn`。可用环境变量 `CARRYON_HOME` 或命令后的 `--state-dir` 指定另一目录。该目录包含本机 Token、投递幂等日志、云端配置和服务日志，权限为当前用户私有；不要随安装包分发。

升级先 stop，再替换应用/CLI 程序，保留同一个数据目录。CLI 安装器遇到已有安装会拒绝覆盖；可以选用 `CARRYON_INSTALL_DIR` 与 `CARRYON_BIN_DIR` 安装到新位置，验证后自行调整 PATH。不要并行启动多个数据目录来控制同一批会话。

旧源码版本使用项目 `.runtime`，本版本不会自动搬迁或删除该目录。已有投递记录的用户：先停止旧服务，再使用 `carryon start --state-dir /旧项目/.runtime`，之后所有命令都带同一参数或设置 `CARRYON_HOME`。不要为了重试未知任务改用空目录，否则会失去原有幂等记录。

卸载应用或 CLI 不会删除用户数据。可以同时绑定多个云端；移除某个绑定使用其绑定 ID，不影响其他绑定。源码与安装包回退均应保留原 Token、jobs.sqlite 与云端授权配置；已在 Codex 执行的任务不能通过卸载撤销。

## 常见问题

- **无法启动**：检查 `server.log` 和 `carryon doctor`；桌面端会显示命令返回的错误。
- **尚未桥接 / socket 不存在**：打开并登录 Codex App，再在桌面端开启桥接或执行 `carryon bridge on`。
- **列表有会话但无法操作**：先在 Codex App 打开它，等待 owner 可用。
- **创建结果待确认**：在 App 核对原请求，不换 requestId 重发。
- **页面提示认证失败**：用 `carryon open` 打开当前实例的新配对页面。
- **云端连接后没有会话**：云端绑定与本地桥接是两个开关；开启本地桥接后再订阅。

CLI 自更新与移除命令见[更新与卸载](CLI_MAINTENANCE.md)。`update` 保留旧程序、绑定和数据；`uninstall` 只移除 CLI 命令入口，保留共享后台与桌面端。

### 桌面多工作区

左侧「添加工作区」可创建或接入不同数据目录。CLI 启动的本机服务自动显示；选中工作区后可启动、前台运行、打开会话、停止、诊断及连接云端。前台服务退出应用时停止，后台服务继续运行。详细命令及共享配置规则见 [CONFIGURATION.md](CONFIGURATION.md)。
