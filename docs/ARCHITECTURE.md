# CarryOn 模块边界

`carryon/server.py` 负责装配；`cli.py`、`services.py`、`lifecycle.py` 负责服务入口和进程生命周期。模块按变化原因划分，不保留旧平铺路径的转发模块。

| 目录 | 职责 |
| --- | --- |
| `routes/` | HTTP 路由、绑定作用域、WebSocket 与实时订阅 |
| `sessions/` | 会话目录、历史投影、消息投递、操作、队列与附件 |
| `desktop_ipc/` | 桌面 IPC 连接、帧、事件与状态补丁 |
| `app_server/` | CarryOn 拥有的 stdio app-server 进程与独立工作区装配 |
| `codex_cli/` | 附加外部 CLI daemon 的 Unix WebSocket、连接恢复与工作区装配 |
| `codex_protocol/` | 公共 JSON-RPC、会话目录、事件投影、审批确认与协议操作 |
| `owner/` | 会话 owner：恢复、声明、请求转发、状态发布、释放 |
| `workspaces/` | 工作区生命周期、成员能力、项目范围与待机 |
| `accounts/` | 账号客户端、绑定邀请、恢复、成员与初始化 |
| `cloud/` | 出站连接、网关、云端控制台与认证 |
| `notifications/` | 通知与 APNs |

共享的契约校验、错误、模型目录、文件路径和请求日志仍位于包根目录。包发现使用 `carryon.*`，新增目录会随 wheel 打包。

## Owner 数据与调用方向

```text
手机创建 → routes → sessions.creation → 临时 app-server → OwnerManager.adopt
手机加载 → routes → OwnerBridge.session_control → OwnerManager
手机发送/桌面追加 → desktop_ipc → owner.requests → app_server
app_server 原生事件 → owner.state 投影 → desktop_ipc 广播 → 桌面/手机
```

app-server 是执行与会话状态的权威来源；owner 不维护第二套执行状态。owner 的 entries 仅保存运行时生命周期、连接状态、投递回执和已发布快照。`owner/state.py` 构造桌面要求的完整 canonical history，`owner/requests.py` 校验会话和原生待处理请求，`owner/manager.py` 管理竞争、断线和释放，`owner/integration.py` 是桌面工作区 Owner 装配入口。

`desktop_ipc` 仅提供通用 request-handler 回调，不导入 owner；`app_server` 不连接桌面 IPC。关闭远控断开手机控制入口，保留 owner 执行与桌面订阅；服务进程真正退出时关闭 owner 子进程。

使用与删除方式见 [OWNER.md](OWNER.md)。

## CLI 与独立运行时

`CliBridge` 和 `AppServerBridge` 复用 `ProtocolBridge`；`CliClient` 与 `AppServer` 复用
`ProtocolClient`。公共层不导入桌面 IPC 或任一运行时适配器。桌面工作区通过 `OwnerBridge`
装配原有 owner 行为，CLI 不经过该层。

运行时的 `peer` 工厂保持传输与所有权：独立工作区产生自己拥有的 stdio 子进程，CLI 产生连接同一
外部 socket 的独立客户端。分叉与取消归档不能绕过此工厂启动另一类运行时。临时聊天目前仅由桌面/独立工作区提供；CLI 在能力投影与服务端均拒绝创建，避免 socket 关闭被误认为任务结束。

CLI 关闭仅断开 socket；daemon 的启动、升级、登录、退出由 Codex CLI 管理。
每次连接使用新 session_id，旧连接中的写入回执不能授权新连接。已投递但未确认的请求保持 uncertain；
重连通过原生 `thread/resume` 恢复订阅并读取状态，不重发 `turn/start`、审批或其他用户写入。暂时恢复失败的订阅由生命周期继续重试，显式关闭则取消恢复。

CLI 会话先读状态：`notLoaded` 只读持久历史，`active/idle` 才调用 resume 订阅。0.155.1 协议没有原子的 subscribe-if-loaded 或 resume 的 deferGoalContinuation 参数；读状态后若其他客户端卸载会话，resume 仍可能重新加载它并按原生规则继续活动目标。这是跨客户端竞态限制，不能承诺恢复订阅绝对没有执行副作用。


## 与官方跨端体验对齐

“共用历史”与“共用运行时”分别判断，不用客户端名称或 CODEX_HOME 相同推断执行同步。

- 本机 Codex CLI 0.155.1 会优先探测对应 home 的 daemon；不可用时使用进程内 app-server。
- 本次安装的桌面端默认启动自己的 app-server。安装包中的连接选择逻辑存在满足条件时使用本地 daemon 的分支，但不能把该可选分支当作当前默认行为。
- 同一 home 中的保存聊天可跨端读取；官方 `/app` 的契约是打开同一份已保存聊天。该事实不保证实时 delta、运行状态和待审批请求跨独立 app-server 传播。
- CarryOn 的 desktop-ipc 与 codex-cli 连接分别投影实际运行时状态。手机不得仅因 thread id 相同就合并执行状态、转交审批或把一端的 idle 覆盖另一端的 active。
- 手机将同机同一 Codex Home 的两种连接归入一个工作区，保留独立连接入口；不为了制造同步而重启官方客户端、切换其执行服务或写入未公开的环境开关。若未来验证官方客户端确实连接同一服务，应按同一 thread/turn 的原生事件保持同步，不能再人为复制成两份独立任务。

官方依据：[CLI `/app`](https://learn.chatgpt.com/docs/developer-commands?surface=cli#continue-in-the-desktop-app-with-app)、[app-server 会话状态和订阅](https://learn.chatgpt.com/docs/app-server)。本机验证记录见 `docs/reviews/2026-10-19-cli-protocol.md`。
