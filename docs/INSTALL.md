# 安装与首次使用

ConnectNow 0.2 面向 macOS。安装包包含 Python 和控制台，用户不需要安装 Python、Node、npm 或 pip。Codex App 必须已安装、登录并运行；目前内部 IPC 记录的验证版本为 26.901.51231。其他版本需通过隔离会话重新验收。

## 普通用户：Mac 应用

1. 选择与你的 Mac 架构匹配的 `ConnectNow-版本-macos-arm64.dmg`（Apple Silicon）或 `x86_64.dmg`（Intel，需在对应环境构建）。
2. 打开 DMG，将 `ConnectNow.app` 拖入 Applications。
3. 双击 ConnectNow。程序启动用户级本地服务，自动在默认浏览器打开已配对的控制台。
4. 点击「开启桥接」。选择已在 Codex App 打开的会话，即可查看记录和继续任务。
5. 要创建新任务，先在 Codex App 建立一个专用空闲控制会话，再到网页「设为控制会话」。此条件不会被安装包消除。

重复双击会复用已有服务并打开页面。关闭网页后 API 仍运行。停止服务：展开页面右下角「云端接入与本地服务」，点击「停止本地服务」；已被 Codex 接收的任务继续执行。应用是启动器，没有菜单栏常驻图标，也不默认配置开机自启。

当前本机构建产物仅作开发/内部验收：PyInstaller 使用 ad-hoc 签名，尚未完成 Apple Developer ID 签名、公证及其他干净设备验收。对外分发前必须完成这些步骤；不要要求用户关闭系统安全保护。没有提供的架构包不能视为已支持。

## 开发者：独立 CLI

解压对应的 `ConnectNow-版本-macos-架构-cli.tar.gz`，保留整个文件夹，不能只复制其中的可执行文件。进入文件夹后运行：

```sh
sh ./install.sh
"$HOME/.local/bin/connectnow" start
```

安装不使用 sudo，也不会修改 shell 配置。如 `~/.local/bin` 已在 PATH 中，可直接使用 `connectnow`。也可以不安装，直接执行解压目录中的 `./connectnow start`。

```sh
connectnow start             # 后台启动并打开本地控制台
connectnow start --no-open   # 仅启动 API
connectnow open              # 重新打开已配对页面
connectnow status            # 查看服务实例与桥接状态
connectnow doctor            # 检查平台、数据目录和 IPC socket
connectnow stop              # 认证后停止服务，不根据旧 PID 杀进程
```

端口默认为 8769。被其他程序占用时会报错，不会静默切换地址。可以显式选择 `connectnow start --port 8770`。重复启动复用现有实例，端口参数不会更改正在运行的服务；调整需先 stop。

## Python 包与源码

面向已有 Python 3.10+ 的开发者，本项目也提供 wheel；包名为 `connectnow-local`，命令仍为 `connectnow`。当前没有发布到 PyPI，不能假设公共仓库中同名包属于本项目。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /实际下载路径/connectnow_local-0.2.0-py3-none-any.whl
.venv/bin/connectnow start
```

源码根目录无需安装依赖即可运行：

```sh
python3 -m connectnow start
# 或前台运行，Ctrl+C 停止：
python3 -m connectnow serve
```

`python3 -m connectnow.server` 仍是前台入口，但不再向日志输出配对 Token。使用 `python3 -m connectnow open` 打开控制台。不要直接双击 example.html。

## 数据、升级与恢复

所有入口默认使用 `~/Library/Application Support/ConnectNow`。可用环境变量 `CONNECTNOW_HOME` 或命令后的 `--state-dir` 指定另一目录。该目录包含本机 Token、投递幂等日志、云端配置和服务日志，权限为当前用户私有；不要随安装包分发。

升级先 stop，再替换应用/CLI 程序，保留同一个数据目录。CLI 安装器遇到已有安装会拒绝覆盖；可以选用 `CONNECTNOW_INSTALL_DIR` 与 `CONNECTNOW_BIN_DIR` 安装到新位置，验证后自行调整 PATH。不要并行启动多个数据目录来控制同一批会话。

旧源码版本使用项目 `.runtime`，本版本不会自动搬迁或删除该目录。已有投递记录的用户：先停止旧服务，再使用 `connectnow start --state-dir /旧项目/.runtime`，之后所有命令都带同一参数或设置 `CONNECTNOW_HOME`。不要为了重试未知任务改用空目录，否则会失去原有幂等记录。

卸载应用或 CLI 不会删除用户数据。更换云端网关前先断开旧绑定。源码与安装包回退均应保留原 Token、jobs.sqlite 与云端授权配置；已在 Codex 执行的任务不能通过卸载撤销。

## 常见问题

- **无法启动**：检查 `server.log` 和 `connectnow doctor`；桌面启动器启动失败时会打开本机错误说明页。
- **尚未桥接 / socket 不存在**：打开并登录 Codex App，再点击开启桥接。
- **列表有会话但无法操作**：先在 Codex App 打开它，等待 owner 可用。
- **创建结果待确认**：在 App 核对原请求，不换 requestId 重发。
- **页面提示认证失败**：用 `connectnow open` 打开当前实例的新配对页面。
- **云端连接后没有会话**：云端绑定与本地桥接是两个开关；开启本地桥接后再订阅。
