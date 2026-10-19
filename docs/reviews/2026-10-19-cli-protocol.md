# Codex CLI 与 CarryOn 同会话协议验证

本文前半记录最初的协议探针；正式适配已经完成，当前实现及验收见 [CLI 正式适配验收](2026-10-19-cli-adaptation.md)。末尾补充官方桌面端与 CLI 的同步边界核查。

## 结论与边界

2026-10-19，使用本机 `codex-cli 0.155.1`，真实 CLI TUI 与 CarryOn 现有 RPC、事件、快照、审批组件能够通过独立 app-server 同时操作同一个会话。双向实时输出、交叉审批、客户端断开后继续执行、全部客户端离线期间的待审批恢复均通过。

初验阶段只增加协议实验脚本，当时尚未实现或发布 CarryOn 的 CLI 后端。风险范围为 R1：临时 Home、临时工作目录、本地确定性模型夹具、临时文件命令。生产接入涉及远程执行和审批，仍按 R2 完成独立审查、恢复方案和端到端验收。

验证拓扑：

```text
真实 Codex CLI TUI ──────┐
                       ├── Unix socket / WebSocket ── 独立 Codex app-server
CarryOn 协议实验适配器 ──┘                                  │
                                                   本机 HTTP 模型夹具
```

CLI 使用 `codex resume --remote unix://<socket> <threadId>` 加入会话。实验适配器只替换连接与关闭行为，复用 `carryon.app_server.app_server.AppServer` 的 RPC、事件投影、历史恢复和审批回复，以及既有 WebSocket 帧编解码。没有建立桌面 IPC 连接；实验 app-server 由测试协调器独立启动，CLI 和 CarryOn 连接端都不拥有它的进程生命周期。

## 已验证结果

最终证据目录：`.runtime/cli-protocol-probe/run-06/`。`report.json` 中 9 项检查全部通过，原始消息包含单调时钟时间戳、发送/接收方向、会话 ID、轮次 ID 和审批 ID。

| 场景 | 检查与结果 |
| --- | --- |
| CLI → CarryOn 实时同步 | CLI 发起任务；模型暂缓结束响应时，CarryOn 已收到文本增量，生产快照中轮次仍为 `inProgress` |
| CarryOn → CLI 实时同步 | CarryOn 发起任务；完成事件前，真实 CLI 终端已经显示首段文本 |
| 同会话多客户端 | 第二个协议客户端恢复同一已加载会话，成功订阅历史与后续事件 |
| CLI 发起、CarryOn 批准 | 两个协议客户端收到同一审批 ID，CLI 出现审批选项；CarryOn 回复后，原生命令执行并完成 |
| CarryOn 发起、CLI 批准 | 在真实 TUI 的审批选项出现后确认；CarryOn 收到 `serverRequest/resolved`，清除待处理请求 |
| CarryOn 断开 | 断开 CarryOn 连接后，CLI 和观察端收到任务完成；CarryOn 重连恢复同一轮次的完成历史 |
| CLI 断开 | CLI 发起任务后终止该 TUI 进程，app-server 保持运行，CarryOn 收到任务完成 |
| 全部客户端断开 | 在流式输出中关闭全部客户端，再放行模型响应；新连接仅用历史读取、在任何 `thread/resume` 之前确认原轮次已完成 |
| 待审批时全部断开 | 关闭最后一个连接后，新客户端恢复会话，收到原审批 ID，生产快照恢复待处理请求；批准后命令完成 |

交叉审批场景还向已处理请求发送了另一订阅端的迟到回复；标记文件只有一条记录，没有再次执行命令。这证明此次串行迟到回复的行为，不等于已经穷举同时回复的所有竞争条件。

审批使用真实引擎的 `item/commandExecution/requestApproval`，批准的命令只向本次临时目录追加一条标记。模型输出由夹具生成，未调用真实推理服务。原生初始化可能访问公共插件目录；本实验并非完整离线测试。

## 协议发现

- `app-server --listen unix://<path>` 在 Unix socket 上使用 WebSocket 握手。实测将 `app-server proxy --sock` 直接指向这个监听端点，会因握手不匹配失败；不能据此推断它与托管 daemon 的控制 socket 相同。
- `thread/resume` 可加入同一运行时中已加载的会话；等待中的审批会在新订阅时重放，并保留原请求 ID。
- `serverRequest/resolved` 用于各端清理已处理请求。重新连接后应以原生重放和快照重建状态，不能保留旧连接的待确认列表直接重发。
- CLI 对未结束的文本行存在渲染缓冲。最终夹具用换行结束首段，并在发出结束事件前检查终端显示，避免将文本渲染缓冲误判为协议不同步。
- 本机运行时拒绝配置 `approval_policy="untrusted"`，尽管导出的 Schema 仍包含该枚举。最终使用 `on-request` 和显式请求审批的无害夹具命令。
- TUI 的命令运行提示可能早于审批选项出现。最终脚本等待本轮完整审批选项再确认，避免输入被错误加入消息队列。

## 正式适配的结构约束

CLI、桌面端、app-server 保持独立的接入与生命周期边界。共享协议、会话数据和纯组件不改变这一点。

| 边界 | 责任 |
| --- | --- |
| CLI 接入 | 发现/配置目标服务，建立客户端连接，订阅和控制会话；断开只释放自己的连接 |
| 桌面接入 | 处理桌面 IPC、桌面 Owner 和桌面专有能力；CLI 接入不经过此链路 |
| app-server 运行时管理 | 管理 CarryOn 明确拥有的独立进程及其启停；连接外部服务时不获得进程所有权 |
| 公共协议组件 | JSON-RPC、消息 Schema、会话投影、历史分页、审批和错误类型；不隐含桌面连接或进程管理 |
| CarryOn 业务层 | 继续负责工作区隔离、远程授权、请求记录、能力投影及客户端 API |

初验时 `AppServer` 同时包含 stdio 子进程生命周期与协议处理；正式适配现已沿上述边界拆分。本次测试用子类替换传输仅用于验证，不能直接作为最终模块结构。初验发现的共享错误和事件类型 `desktop_ipc` 路径依赖现已迁入公共模块，CLI 适配器不依赖桌面适配器。

## 复现与证据

在 macOS、已安装目标 Codex CLI 和 Python 的环境中执行，输出目录必须尚不存在：

```sh
python3 tests/run_cli_protocol_probe.py \
  --codex /opt/homebrew/bin/codex \
  --output .runtime/cli-protocol-probe/reproduce-01
```

脚本创建独立临时 Home、工作目录和监听 socket，真实 TUI 运行在 PTY 中；结束时关闭本次客户端、服务器和本地模型服务，并清理临时数据。保留以下证据：

- `report.json`：版本、会话与轮次 ID、检查结果、模型夹具调用及限制。
- `*-wire.jsonl`：各协议客户端的原始发送/接收消息。
- `cli-terminal.log`：真实 CLI TUI 输出，包含 ANSI 控制序列。
- `server-stdout.log`、`server-stderr.log`：独立服务日志。
- `manifest.json`：最终脚本哈希、仓库基线及运行环境，随本次最终证据单独生成。

脚本语法检查通过。未修改产品实现，不需要通过全仓测试来证明本次协议实验；本报告也不声明产品回归或发布验收完成。

尚未验证：未显式连接该共享服务的普通 CLI 会话自动发现、托管 daemon 的管理与控制 socket、CLI 正常退出命令与各种系统信号的差异、app-server 自身退出后的执行恢复、其他版本、真实模型推理、CarryOn HTTP/云端/iOS 完整链路、设置/队列/归档等其他操作，以及文件/权限/MCP 等其他审批类型。

## 恢复

本次没有修改现有服务配置、用户 Codex Home 或用户会话，没有启动或重启用户的托管 daemon，也没有部署。撤销仅需移除本次新增的实验脚本和本报告；保留证据目录供核验。后续正式适配应单独建立连接故障、版本不匹配和授权撤销的恢复与验收方案。


## 官方桌面端与 CLI 同步边界核查

目标以官方当前行为为准：共享的聊天历史保持可见，独立执行服务的运行状态和审批分别管理；不预设“所有内容同步”或“所有内容隔离”。

### 官方契约与安装包证据

- 官方 [CLI `/app` 文档](https://learn.chatgpt.com/docs/developer-commands?surface=cli#continue-in-the-desktop-app-with-app) 将行为描述为在桌面端打开同一份 saved chat；未据此承诺各独立服务实时共享执行状态。
- 官方 [app-server 文档](https://learn.chatgpt.com/docs/app-server) 把 loaded 状态、订阅、待审批重放定义在服务连接和已加载会话上。
- 对应本机 CLI 0.155.1 的官方源码 `codex-rs/tui/src/lib.rs` 中 `maybe_probe_default_daemon_socket` / `start_app_server`：默认端点可用时连接 daemon；失败时退回进程内 app-server。源码取自 `openai/codex` 的 `rust-v0.155.1` tag，保存在 `.runtime/cli-desktop-sync/`。
- 对本机 `/Applications/ChatGPT.app/Contents/Resources/app.asar` 的 `.vite/build` 进行逐成员 SHA-256 校验后提取。`application-network-startup-DB1VeU3v.js` 的 `Ks.connect` 默认使用 stdio；只有显式 `CODEX_APP_SERVER_USE_LOCAL_DAEMON=1` 等多个条件同时满足时，才进入本地 daemon WebSocket 分支。本次没有启用该开关，也没有重启官方客户端。
- 本机桌面端子进程实测命令为内置 codex 的 `app-server --analytics-default-enabled`，默认 CLI daemon socket 当时不存在。这印证本机当前没有共用该 daemon。
- REA 对 36 个已核验提取成员完成静态分析，父证据 ID `ev_378191b1d2f2a42365b0a9af1110824d0f4f34641bef6314f9c2358cb9363c72`。分析为 partial，不能以静态调用候选代替运行验证。整包分析曾因 300 秒超时结束；安装包一个不相关的 unpacked native 模块存在声明哈希差异，实际引用的 JS 成员均另行校验通过。

### 运行验证

真实普通 CLI（未指定 `--remote`）、当前桌面端、相同 CODEX_HOME，使用专用临时目录和无业务内容测试会话。模型响应由 loopback WebSocket 夹具提供，使用本次 CLI 参数 `openai_base_url`，不改全局模型配置。没有记录请求认证头。

- 桌面端原生 `read_thread` 能读取 CLI 创建的同一 thread id、用户消息及完整 seed 回复：历史共用已验证。
- 模型输出首段后被测试门闩暂停，CLI 保持运行；桌面端读取同一 thread 的运行状态仍为 `notLoaded`，当前轮次显示 `interrupted` 且没有首段 assistant delta：当前默认运行状态并不实时统一。
- 桌面 IPC 对该 CLI 会话未发现 owner，无法订阅 CLI 的执行状态。打开会话链接也未使其成为桌面已加载 owner；该结果不能被改写成“两端已完成交叉接管”。
- 共享同一个 daemon 时，CLI ↔ CarryOn 的实时同步、交叉审批及断线继续执行已经在前述 9 项协议检查和手机 25 项检查中验证；它不证明独立桌面服务 ↔ CLI 也有同样行为。

最终受控流实验与读端证据位于 `.runtime/cli-desktop-sync/`：`stream_probe.py`、`stream-held.json`、`desktop-read-during-stream.json`、`desktop-read-after-completion.json`、`stream-result.json`、`summary.json`。检查值 false 表示观测到未同步，不是把负向结果包装为同步通过。

### 限制与产品决策

- 未验证桌面端启用可选共享 daemon 分支后的完整三端交叉审批，也未验证两端同时对同一保存聊天发起写入。当前不能据此宣称官方所有模式都不同步。
- 原生 UI 自动化入口拒绝访问 Codex 应用，因此使用官方线程读取接口和桌面 IPC 做运行观测，没有绕过该限制获取屏幕或操作 UI。
- 用真实模型进行额外对照时，本机默认 `gpt-6.1-sol` 及试用的 `gpt-5.4` 均被 CLI 账号接口拒绝；这不是同步协议结论。最终受控流夹具不依赖该模型访问权限。
- 临时测试信任项已按精确项目路径移除；CLI/夹具进程已退出。本次 8 个测试聊天已归档，保留可恢复的原生记录，不修改或删除用户业务会话。
- CarryOn 当前保留桌面和 CLI 的独立控制入口，不合并其运行状态或审批，不声称共用 home 就实时同步。共享历史可以出现在两端，手机的发送、停止与审批必须随所连接的运行时。未来只有确认官方两端实际共用同一服务，才据原生 thread/turn 身份同步，而不复制执行状态。
