# ConnectNow

连接你电脑上的 Codex App：通过本地浏览器控制台或自己的云端控制台查看会话、发送任务和使用 HTTP/WebSocket API。

云端 example 已提供同进程控制台后端与设备连接模块，使用方法见 [云端控制台指南](docs/CONSOLE.md)。

**普通用户：安装 ConnectNow.app，双击后自动打开本地控制台。开发者：`connectnow start`。** 安装包自带 Python，运行不需要 npm/pip 依赖。当前支持 macOS 路径，已记录的 Codex 内部 IPC 验证版本为 26.901.51231。

当前版本 0.2.0。本机构建的安装包尚未完成 Developer ID 公证及干净设备验收，正式对外分发前请完成签名、公证和目标平台检查。项目未发布到 PyPI，也未提供公共下载域名；使用本项目实际构建产物。

- [GitHub Actions 与阿里云部署](deployment/README.md)：隔离网关、部署开关和回滚。
- [安装与首次使用](docs/INSTALL.md)：应用、CLI、Python 包、升级、旧数据目录与排错。
- [接入自定义云端控制台](docs/CLOUD.md)：出站 WSS、参考网关、设备凭证、后端示例和协议。
- [本地 HTTP / WebSocket API](docs/API.md)：已有能力、请求状态与幂等契约。
- [开发与安装包构建](docs/DEVELOPMENT.md)：可复现构建和测试命令。
- [验证记录与限制](docs/VALIDATION.md)：证据与未完成门禁。

## 快速使用

```sh
connectnow start
connectnow status
connectnow open
connectnow stop
```

源码开发者在项目根目录使用 `python3 -m connectnow start`。默认数据目录为 `~/Library/Application Support/ConnectNow`，可通过 `CONNECTNOW_HOME` 或命令后的 `--state-dir` 设置。旧源码项目 `.runtime` 不自动迁移，有历史请求时请按安装文档沿用原目录。

在 CLI 执行 `connectnow bridge on`，或在 ConnectNow 桌面端开启桥接。已有会话需先在 Codex App 中打开。创建新任务仍需要一个已加载、空闲且具备原生 create_thread 工具的专用控制会话。

关闭页面不停止服务；使用桌面端「停止服务」或 CLI stop。重复启动复用同一个数据目录下的服务。ConnectNow 不替换原生 socket、不修改 Codex 数据库，已被 Codex 接收的任务不会随桥接关闭而撤销。

CLI 和 macOS 桌面端共用同一数据目录和本机服务，设置双向可见。本地网页仅用于会话交互，不提供本机配置。参见[配置命令与桌面端](docs/CONFIGURATION.md)。

## 云端接入

推荐在 CLI 或桌面端填写云端控制台 HTTPS 地址申请连接，云端收到通知后确认，即可自动登记设备。支持多台本机接入同一云端，以及本机同时绑定多个云端；权限与解除绑定独立管理。见[多云端绑定指南](docs/MULTI_CLOUD.md)。

CLI 提供云端控制台 HTTPS 地址即可申请连接，然后在云端「连接申请」核对确认：

```sh
connectnow cloud connect --url https://你的云端域名/connectnow
connectnow cloud status
connectnow cloud disconnect
```

命令返回表示申请已提交，绑定由本地服务在云端确认后自动完成。无需输入一次性配对码或设备 Token。多实例时每条命令带上对应的 `--state-dir`。

默认只读。允许远程投递、编辑、设置和审批需要桌面端明确勾选远程控制或使用 `--allow-control`。云端不能开启已关闭的本地桥接。参考网关及自定义协议见云端接入文档；本项目不提供云端账号系统或公共托管。

## 当前业务能力

- 原生会话列表、侧边栏状态、文字与工具时间线、队列与详情投影。
- 继续空闲会话；通过专用控制会话创建 projectless 新任务。
- 已验证关联的临时聊天只读展示；没有临时聊天新建或发送入口。
- 按原生契约提供停止、补充、编辑、压缩、设置、队列与审批/输入操作。
- 持久化 requestId 幂等日志，结果未知时不自动重发；创建 ID 依据原生工具结果核验。
- 不保证与 Codex App 像素级一致；附件主要保留引用，旧 rollout 仅提供降级文字历史。

## 主要模块

| 模块 | 职责 |
|---|---|
| `cli.py / paths.py` | 后台启停、配对打开、状态目录与诊断 |
| `server.py / api.py` | 本地 HTTP 鉴权与两种传输共享的 API 路由 |
| `bridge.py / store.py` | 原生控制边界、投递与幂等日志 |
| `cloud.py / cloud_wire.py` | 本机云端授权、主动 WSS 连接 |
| `gateway.py` | 可替换的单进程云端参考网关 |
| `ipc.py / events.py / patches.py` | 桌面协议与事件适配 |
| `realtime.py / thread_status.py` | 共享订阅、后台核验及状态解释 |
| `catalog.py / timeline.py` | 本地目录与历史展示投影 |
| `operations.py / contracts.py / queue.py` | 原生操作、输入校验与队列契约 |
| 根目录 HTML / JS / CSS | 控制台、连接客户端与本地云端绑定界面 |

## 检查

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_client.js
python3 -m compileall -q connectnow examples tests
```

Node 只用于开发测试，终端用户运行独立安装包不需要 Node。

桌面端支持多个本地工作区：自动发现 CLI 服务，并提供启停、前台日志、诊断和云端配置。CLI 查看全部服务用 `connectnow services list`；新建和接入目录见 [配置说明](docs/CONFIGURATION.md)。
