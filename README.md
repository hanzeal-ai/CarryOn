# CarryOn

**换个设备，接着做。** · Switch devices. Carry on.

CarryOn 让你在另一台设备上继续处理 Mac 上的 AI 工作。它连接本机 Codex App、Codex CLI 或独立 app-server，通过浏览器控制台、iOS 客户端或自己的云端控制台查看会话、发送任务和处理审批，并提供 HTTP / WebSocket API。

[快速开始](#快速开始) · [开发与验证](#开发与验证) · [文档](#文档) · [反馈与贡献](#反馈与贡献)

## 功能

- 查看原生会话、文字与工具时间线、任务队列及运行状态。
- 继续已有会话，或为指定项目及无项目场景创建任务。
- 处理停止、补充、编辑、设置、审批和输入请求。
- 管理多个本地工作区，并将工作区绑定到不同云端。
- 通过持久化请求标识防止重复投递；结果未知时不自动重发。
- CarryOn CLI 与 CarryOn macOS 应用共享本机服务和配置。

## 项目状态与运行条件

项目处于发布前阶段。当前本机服务面向 macOS，按工作区类型连接 Codex App、Codex CLI daemon 或独立 app-server；远程设备通过浏览器或 iOS 客户端访问。Codex 内部协议的验证范围见[验证记录](docs/VALIDATION.md)。

独立安装包自带 Python，终端用户无需安装 Node.js 或 Python。项目尚未发布到 PyPI，请使用本仓库实际构建的安装包。本机构建产物的正式分发仍需完成签名、公证及目标设备验收。

## 快速开始

### 使用安装包

按照[安装指南](docs/INSTALL.md)安装 CarryOn.app 或独立 CLI。桌面端首次打开进入初始化向导；CLI 使用：

```sh
carryon init
carryon start
carryon status
carryon open
```

`init` 首次绑定工作区时，需要在已登录的 CarryOn iOS App 中扫码确认。向同一工作区添加连接时，可在电脑端选择已有绑定、核对账号和权限并确认，无需手机再次扫码。绑定后可自动启动服务。日常使用 `start` 启动、`open` 打开本地控制台，结束时运行 `carryon stop`。关闭网页不会停止服务。

### 连接 Codex CLI

在使用目标 `CODEX_HOME` 的终端启动 Codex daemon，然后注册 CLI 连接：

```sh
codex app-server daemon start
carryon services create --backend codex-cli --name "Codex CLI" --codex-home "$HOME/.codex"
```

非交互执行会返回连接 `directory`；交互执行可选择已有工作区绑定，或首次扫码绑定。之后使用
`carryon init --state-dir <directory>`、`carryon start --state-dir <directory>`。
同机同一 Codex Home 的桌面端与 CLI 连接会归入同一个工作区。手机工作区列表显示两种连接，
首页可以切换。首次扫码绑定一次；添加连接时在电脑端确认沿用已有账号和工作区权限。
只有展示分组相同不会自动授权，消息和审批仍路由到所选连接。

注册普通账号需要一次性邀请码。在桌面「注册邀请码」中点击「授权本机」，
将链接交给云端管理员；管理员打开链接、核对本机指纹并输入管理员账号密码确认后，
授权立即生效，返回电脑点击「生成邀请码」即可。该操作会替换原有的邀请码生成电脑。
CLI 可运行 `carryon invate --authorize` 生成同一授权链接；尚未绑定工作区时使用
`carryon invate --authorize --url https://你的云端地址`。确认后运行 `carryon invate`
（未绑定时同样带 `--url`）生成邀请码。云端和桌面/CLI 均需升级到支持此流程的版本；
首次升级完成后，日常授权不需要登录服务器或重启服务。

CLI 连接默认连接该 home 下的 `app-server-control/app-server-control.sock`。
已有显式 Unix WebSocket 服务时，可在创建工作区时指定 `--cli-socket /绝对路径/server.sock`，
并让 Codex CLI 连接同一端点。服务运行期间不要切换其 CODEX_HOME。

CarryOn 只附加 CLI 运行时，不启动或停止它。关闭手机、CarryOn 或 CLI 终端后，任务继续由 daemon 执行；
停止 daemon 本身不在此保证内。重连重新订阅历史与待审批请求，未确认写入不会自动重发。
CLI 工作区不依赖 Codex 桌面端；已验证版本为 Codex CLI 0.155.1。CLI 后端当前不提供临时聊天入口。
恢复订阅使用原生 `thread/resume`；外部客户端并发卸载会话时，存在重新加载并继续活动目标的原生竞态，见[架构边界](docs/ARCHITECTURE.md)。
若尚无托管安装，请先按 `codex app-server daemon bootstrap --help` 完成 Codex 自身的 daemon 安装，或使用显式 Unix 监听端点。

### 从源码运行本机服务

需要 Git、Python 3.10+，以及对应工作区使用的 Codex 运行时。在终端执行：

```sh
git clone https://github.com/hanzeal-ai/CarryOn.git
cd CarryOn
python3 -m carryon start
python3 -m carryon status
python3 -m carryon open
```

停止服务：

```sh
python3 -m carryon stop
```

默认状态目录为 `~/Library/Application Support/CarryOn`，可通过 `CARRYON_HOME` 或命令的 `--state-dir` 选项指定。更多工作区、权限和诊断操作见[配置说明](docs/CONFIGURATION.md)。

## 云端与权限

远程使用前，需要将本机工作区绑定到云端。自托管使用 `carryon init --url HTTPS地址`，配置步骤见[多云端绑定指南](docs/MULTI_CLOUD.md)。

远程权限默认只读；投递、编辑、设置和审批需要明确授权。云端不能开启已经关闭的本地桥接。CarryOn 不替换 Codex 原生 socket，也不修改其数据库；已经被 Codex 接收的任务不会因关闭桥接而撤销。

## 项目结构

| 路径                           | 职责                                            |
| ------------------------------ | ----------------------------------------------- |
| `carryon/`                     | 本机服务、CLI、原生协议适配、请求记录及云端连接 |
| `desktop/`                     | macOS 桌面应用与本机工作区管理                  |
| `iOS/`                         | iOS 客户端与 Swift 测试                         |
| 根目录 HTML / JS / CSS、`web/` | 控制台页面、连接客户端及 Web 构建资源           |
| `tests/`                       | Python 与 JavaScript 测试                       |
| `deployment/`                  | 云端部署配置与运维说明                          |

## 开发与验证

在仓库根目录运行：

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_*.js
swift test --package-path iOS
```

Node.js 用于 Web 开发与测试；Swift 测试和桌面构建需要对应的 Apple 开发工具。安装包构建、依赖准备及平台验证见[开发指南](docs/DEVELOPMENT.md)和 [iOS 说明](iOS/README.md)。

## 文档

| 场景                 | 文档                                                                                               |
| -------------------- | -------------------------------------------------------------------------------------------------- |
| 安装、首次连接与排错 | [快速开始](docs/QUICKSTART.md)、[安装指南](docs/INSTALL.md)                                        |
| 初始化与工作区授权   | [绑定流程](docs/ONBOARDING.md)、[配置说明](docs/CONFIGURATION.md)                                  |
| 云端控制台与自托管   | [控制台指南](docs/CONSOLE.md)、[云端接入](docs/CLOUD.md)、[多云端绑定](docs/MULTI_CLOUD.md)        |
| API 集成             | [HTTP / WebSocket API](docs/API.md)                                                                |
| 构建、更新与部署     | [开发指南](docs/DEVELOPMENT.md)、[应用更新](docs/APP_UPDATES.md)、[部署指南](deployment/README.md) |
| 已验证范围与限制     | [验证记录](docs/VALIDATION.md)                                                                     |

## 反馈与贡献

通过 [Issues](https://github.com/hanzeal-ai/CarryOn/issues)反馈问题时，请提供系统、CarryOn 与 Codex 版本、复现步骤、预期结果和实际结果。分享日志前请移除令牌、设备凭证和私人会话内容。

提交改动前，请阅读受影响模块的文档，保持改动范围清晰，运行相关检查，并在 Pull Request 中说明行为变化与验证结果。不要提交本机状态目录或生成的安装包。

## 许可证

仓库尚未提供 `LICENSE` 文件，当前没有明确授予开源使用、修改或再分发的许可。许可证确定后应以仓库中的正式许可证文件为准。
