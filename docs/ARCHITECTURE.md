# CarryOn 模块边界

`carryon/server.py` 负责装配；`cli.py`、`services.py`、`lifecycle.py` 负责服务入口和进程生命周期。模块按变化原因划分，不保留旧平铺路径的转发模块。

| 目录 | 职责 |
| --- | --- |
| `routes/` | HTTP 路由、绑定作用域、WebSocket 与实时订阅 |
| `sessions/` | 会话目录、历史投影、消息投递、操作、队列与附件 |
| `desktop_ipc/` | 桌面 IPC 连接、帧、事件与状态补丁 |
| `app_server/` | stdio app-server 进程、JSON-RPC、独立工作区适配 |
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
