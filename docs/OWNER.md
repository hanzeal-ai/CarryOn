# 会话 Owner

## 启用与使用

桌面 IPC 工作区默认装配 Owner，支持手机创建和加载会话；独立 app-server 工作区使用自己的执行进程，不装配该模块。升级后需重启 CarryOn 服务加载新代码。

`/api/status` 返回 `supportsSessionLoading: true`。iOS 会话操作菜单对未就绪会话显示“加载会话”，对 CarryOn owner 会话显示“释放手机加载的会话”。直接发送消息时，后端在明确没有 IPC owner 后自动加载会话，再通过原生 IPC 投递；任务自动释放后再次发送同样适用。手动加载只恢复和订阅，不自动执行 `turn/start`。桌面通过现有 IPC follower 协议订阅和控制，不需要修改桌面应用。

```http
POST /api/threads/{threadId}/session
Content-Type: application/json

{"requestId":"session-load-001","action":"load"}
```

释放使用 `action: "release"`。接口返回现有 job 格式（`completed`、`failed` 或 `uncertain`）；请求编号绑定会话及操作，相同编号不同内容拒绝。远程接口沿用账号绑定作用域、工作区 send 能力、会话范围和实时撤权校验，不增加旁路授权。

## 手机创建会话

`POST /api/threads` 校验项目和请求编号后，启动一个共享桌面 `CODEX_HOME` 的临时 app-server，通过 `thread/start` 写入原生 `projectId`，使用项目当前目录和分页历史。创建响应中的会话 ID 直接保存到请求回执。

Owner 接管同一个进程并广播原生状态，再经 `thread-follower-start-turn` → Owner → `turn/start` 投递原始任务。模型、推理强度和权限沿用原生配置，不通过手机覆盖。新建空会话在首轮前尚不能可靠地关闭再恢复，因此创建进程持续到任务结束，由 Owner 自动释放。创建流程不借用其他会话，也不让模型调用创建工具。

相同请求编号和内容返回原回执；内容冲突拒绝。项目改变、撤权、Owner 竞争或通信失败时停止后续写入。已经创建或结果不明的请求保留 `uncertain` 和已知 ID，不自动再建或重发。服务重启不续跑创建请求。

## 执行与竞争边界

- 每个会话使用一个 stdio app-server，共享原有 `CODEX_HOME`；恢复会话的进程锁和日志位于 `owner/{threadId}`，新建会话位于 `owner/creations/{requestId}`。
- 只接管无 IPC owner、具有 paginated 原生历史的会话。原生 active-writer 锁负责跨进程互斥；legacy 历史拒绝接管。已有桌面 owner 时返回 `state: desktop`，不创建执行进程。
- `/compose` 和 `/messages` 共用发送前接管入口，仅明确的 `no-client-found` 触发一次加载并重新获取原生状态；临时聊天、其他错误和未知结果不自动接管或重发。读取历史不触发加载，相同发送请求返回原回执。
- load 前后确认 owner 和授权；无法确认、恢复失败或出现其他 owner 时拒绝或冻结写入。历史读取不等于抢占执行权。
- 支持发现、完整历史、发送、执行中追加、停止、压缩以及命令/文件/权限/问题/MCP 审批回应。模型/权限设置变更、编辑回滚、桌面队列等未列入支持的动作拒绝，手机按 `supportedOperations` 隐藏不支持的操作。
- 开始执行时继承会话设置，不接受任意启动权限覆盖。审批沿用当前原生 request ID、问题集合和权限子集校验。
- 重复 IPC 写请求绑定内容摘要；未知结果保留未知，不自动重放。内存回执在同一 owner 服务进程内跨释放、重新加载保留，执行请求总量上限 1000；达到上限会明确拒绝新增执行请求，不淘汰执行回执后重发。停止和审批不受执行配额阻断，使用本次运行时内有界回执及原生 turn/request ID 复核。服务重启不会恢复 owner 或自动执行请求。
- IPC 断开后保留 app-server，重新连接时复查原生 loaded 状态和其他 owner。app-server 退出会广播 notLoaded；不自动重新执行。
- 任务进入 completed、failed 或 interrupted，且原生状态为空闲、无执行中轮次、无待处理审批、当前 IPC 回复已发送完毕后，自动释放 owner 和原生写锁，允许桌面直接归档。仅加载旧会话不会自动释放。手动释放同样要求空闲且没有待处理审批。关闭远控保留任务；退出 CarryOn 服务会结束它拥有的 app-server。主动退出前应停止或等待任务完成。

## 恢复

回退服务版本前先停止接收新建请求，等待 Owner 会话空闲并释放，再退出 CarryOn。使用本次变更前的源码或安装包恢复服务，保留 CarryOn 请求日志和 Codex 原生数据；未知请求必须按原编号核对，不重新提交。仅恢复与本次变更有关的文件，不覆盖项目其他未提交改动。

Owner 是桌面工作区创建链路的组成部分，不能单独移除模块或通过旧的环境变量关闭。关闭远控保留正在执行的 Owner；退出服务会结束它拥有的 app-server。

## 验证

`python3 -m unittest discover -s tests -p 'test_owner.py' -v` 覆盖声明/释放、竞争、跨会话、权限、回执、崩溃和生命周期；`test_ipc.py` 验证帧传输中的未知结果语义。

`python3 tests/run_owner_regression.py` 使用隔离 CODEX_HOME、已安装真实 Codex app-server 和本地 HTTP 模型测试服务，验证 IPC 发现、canonical history、真实 turn/start、流式完成、重复消息去重、自动释放以及另一 app-server 归档，不访问用户凭证或真实模型 API。

实机验证记录和明确未验证项见 [交付审查](reviews/2026-09-30-owner.md)。

`python3 tests/run_creation_regression.py` 验证无既有会话时从项目 API 创建、原生项目归属、Owner 接管、IPC 投递、流式完成、请求去重、自动释放及另一 app-server 归档。测试使用隔离目录和本地模型服务，不使用真实账号或模型 API。
