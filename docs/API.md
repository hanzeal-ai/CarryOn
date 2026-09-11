# HTTP API

Base URL：`http://127.0.0.1:8769/api`。UTF-8 JSON，普通请求体最多 100,000 字节；会话消息及云端转发消息请求最多 900,000 字节。

每个请求都需要 `Authorization: Bearer <Token>`，POST 另需 `Content-Type: application/json`。Token 保存在状态目录的 `token` 文件（默认 `~/Library/Application Support/ConnectNow/token`）；普通启动日志不输出 Token，`connectnow open` 自动配对页面。所有调用方共享一个桥接开关、控制会话选择和请求日志；当前不是多租户 API。

## 路由

| 方法 | 路径 | 输入 | 返回 |
|---|---|---|---|
| GET | `/status` | 无 | `enabled, controllerId, protocol, testedDesktopVersion` |
| POST | `/bridge` | `{"enabled":true}` 或 `false` | 同 status |
| GET | `/threads` | query：`search`、`limit` 1–100、`offset` ≥0 | `{threads:[{id,title,cwd,updated_at,created_at,history_mode}],nextOffset}` |
| POST | `/controller` | `{"threadId":"UUID"}` | 同 status，需目标已加载且空闲 |
| GET | `/threads/{id}/history` | 无 | `{thread,messages,timeline,runtime,status,metadata,pendingRequests,coverage,truncated,source}`；原生快照提供扩展字段 |
| POST | `/threads` | `{"requestId":"唯一ID","prompt":"新任务文案"}` | HTTP 202 + Job |
| POST | `/threads/{id}/messages` | `{"requestId":"唯一ID","prompt":"后续任务"}` | HTTP 202 + Job |
| GET | `/jobs` | 无 | `{jobs:[Job,...]}`，最近 100 个 |
| GET | `/jobs/{requestId}` | 无 | Job；查询时刷新执行证据 |
| POST | `/jobs/{requestId}/acknowledge` | `{"confirmed":true}` | 仅 uncertain 可用，人工核对后变为 acknowledged，不重发 |

桥接关闭时，`/status`、`/bridge` 及下述本地服务管理接口可用。列表排除已归档与明确标记的内部子 agent，但历史版本不一定标记完整。`nextOffset` 是下一页起点；返回条数小于 limit 表示结束。时间为 Unix 秒。UUID 为小写标准 UUID。

消息示例：

```json
{"id":"消息ID","role":"assistant","text":"你好","phase":"final_answer","turnId":"轮次ID","textTruncated":false}
```

`phase`、`time`、`turnId` 可缺省；`source` 为 `desktop-snapshot` 或 `local-rollout`。`messages` 保留旧版兼容字段，仍最多 200 条、每条 24,000 字符，`messagesTruncated` 表示条数裁切；新页面使用 `timeline`。

### 原生时间线扩展

`timeline` 按原生轮次/条目顺序返回全部已加载展示记录，不另做文字截断。每条结构为：

```json
{
  "id":"turn-id:item-id",
  "nativeId":"item-id",
  "turnId":"turn-id",
  "type":"commandExecution",
  "title":"执行命令",
  "status":"completed",
  "durationMs":1200,
  "text":"git status --short",
  "data":{"command":"git status --short","cwd":"/project","aggregatedOutput":"原始输出","exitCode":0,"status":"completed","durationMs":1200},
  "supported":true
}
```

- `turn` 分隔记录含开始时间、状态、耗时、模型等；`commandExecution` 含原始命令与输出；`mcpToolCall` / `dynamicToolCall` 含参数、结果和状态；`fileChange` 含文件路径与 diff。
- `reasoning.data.summary` 仅为原生展示摘要；不返回 raw content、加密内容或系统/开发者指令。思考中状态根据原生活动轮次及最后条目推导，并非额外的模型信号。
- `contextCompaction.status` 为 inProgress/completed，`data.source` 为原生来源（若提供）。没有百分比或压缩正文时不会编造。
- `status` 为统一的原生状态投影 `{state,label}`，侧边栏与空闲操作门禁使用同一解释。待审批或待输入标志即使与 `idle` 同时出现，也禁止发送、压缩和编辑；旧 rollout 不提供该字段，不能据此推断可操作。
- `runtime` 原样返回原生线程状态；`metadata` 包含可用的模型、推理设置、Token 用量和 Git 信息；`pendingRequests` 提供请求标识与类型；`controls` 提供本页操作需要的轮次、设置和可回应请求。
- `coverage` 标记未适配事件类型、摘要/附件范围和 websocket-events 更新机制。未知事件只返回类型与状态，不盲目导出内部字段。
- `truncated` 表示原生快照历史未完整加载；不等同于页面按 120 条渐进渲染。32 MiB 的 IPC 帧上限仍生效。
- 旧 rollout 回退不提供 timeline，调用方应明确显示“仅文字历史”。

文本和工具输出是数据，外部页面应使用安全文本节点展示，不要直接插入 HTML；复制保留原始字符。截图/音频等附件当前仅保留引用或结构化信息，不提供任意本机文件读取接口。

## 异步请求与幂等

`requestId` 是调用方生成的 8–100 位字母、数字、`_`、`-`，推荐 UUID。文案去除首尾空白后不能为空，提交值最多 16,000 字符。

```json
{
  "id":"external-create-0001",
  "kind":"create",
  "threadId":"控制会话UUID",
  "state":"completed",
  "created":1789097059.44,
  "updated":1789097070.10,
  "turnId":"控制会话轮次UUID",
  "createdThreadId":"新会话UUID",
  "evidence":"native-create-thread-result",
  "error":null
}
```

Job 还可能包含 fingerprint、clientMessageId、expectedTitle；调用方不要依赖这些内部字段。`turnId` 和 `createdThreadId` 只有得到证据后才返回。

| state | 意义 |
|---|---|
| preparing | 已登记，正在检查目标 |
| dispatching | 已持久记录投递意图，准备/正在写 socket |
| accepted | Codex 返回了本轮 ID，尚未确认结束 |
| completed | 继续任务的该轮完成，或新建任务的原生创建结果已核验 |
| failed | 检查/路由失败，或目标报告执行失败；查看 error 与 App |
| interrupted | Codex 该轮被中断 |
| uncertain | 超时、断开或证据不足，可能已经执行；禁止自动补发 |
| acknowledged | 用户核对后解除后续发送阻塞，不代表成功 |

调用成功的 HTTP 202 仅表示登记。网页通过 WebSocket 接收后续状态，外部 HTTP 客户端也可查询 `/jobs/{id}`。创建还依赖控制会话执行一次模型回合，耗时包含模型与工具执行，不保证秒级完成。

相同 ID + 相同类型/目标/文案返回原 Job；相同 ID 不同内容返回 409。每个目标同时最多一个 preparing/dispatching/accepted/uncertain 请求。创建的目标为当时选择的控制会话；重试期间不要切换控制会话。

请求日志持久化在 `.runtime/jobs.sqlite`。重启时 preparing/dispatching 标记 uncertain；不会主动重发。已知 turnId 的 uncertain 可通过只读证据重新核验。核验写入会比较完整的读取版本；并发人工确认或更新发生后，旧结果不会覆盖当前状态。同一请求的并发查询复用正在进行的核验，可能先返回当前已保存状态。不要删除日志来“解决”不确定状态，否则会丢失幂等保护。创建通过原生工具调用参数、返回 ID 和数据库创建时间核验，模型输出的 ID 本身不是成功证据。

## Python 外部调用

```python
import json, pathlib, urllib.request, uuid

token = pathlib.Path('/Users/sanmws/Documents/ConnectNow/.runtime/token').read_text().strip()
def call(path, body=None):
    request = urllib.request.Request(
        'http://127.0.0.1:8769/api' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

call('/bridge', {'enabled': True})
call('/controller', {'threadId': '替换为已加载的空闲控制会话UUID'})
request_id = str(uuid.uuid4())  # 在调用前保存；网络失败仍使用这个 ID。
job = call('/threads', {'requestId': request_id, 'prompt': '仅回复你好'})
print(job)
print(call('/jobs/' + request_id))
```

完整命令行客户端见 `examples/client.py`，不会自动重试或自动批准。

## 云端接入边界

本服务只绑定 loopback，验证 Host，并拒绝浏览器跨站请求、跨域预检和 iframe。外部后台进程可以使用 Bearer Token 调用；云端浏览器不能直接跨域访问本服务。

如果已经配置本机到可信云端的 SSH，可在本机另行建立反向私有转发：

```sh
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:8769:127.0.0.1:8769 user@your-server
```

云端后台随后调用其 `http://127.0.0.1:8769/api`，附带 Token。需要保持 SSH 连接；示例未在真实云端执行。SSH 服务端应保持远端转发仅监听 loopback。云端网页走自有后台的登录和授权，再调用此通道；不要把本机 Token 放入公开网页。

桥接关闭后云端继续/新建请求返回 403；持 Token 者仍可调用 `/bridge` 重新开启。若产品需要“只有本机按钮才能授权云端”，还需拆分本地授权与外部投递权限，本版本不声称具备这个能力。

## 错误处理

- 400：参数、UUID、历史格式或会话目录不符合预期。
- 401：Token 无效。
- 403：桥接关闭、Host/Origin 不允许。
- 404：请求不存在或路由不存在。
- 409：目标运行中、请求冲突、IPC owner 不存在或协议不匹配。
- 503：无法连接本机 Codex socket。
- 500：服务或本地数据格式异常，不能视为任务未执行。

响应一般为 `{"error":"说明"}`；IPC 错误另含 `uncertain`。POST 发生网络中断后查询原 requestId，切勿生成新 ID 自动再发。


## WebSocket 实时同步

连接同源 `/api/stream`（本机为 `ws://127.0.0.1:8769/api/stream`）。服务仍仅监听 loopback，沿用 Host/Origin 校验。第一帧必须在 5 秒内发送：

```json
{"type":"auth","token":"配对 Token"}
```

Token 不放在 URL。随后发送订阅，`subscription` 是客户端生成的标识，切换时更换；`threadId: null` 取消当前会话选择：

```json
{"type":"subscribe","threadId":"会话 UUID","threadIds":["侧边栏会话 UUID"],"subscription":"客户端唯一标识"}
```

服务推送 `type: "update"`，包含 `status`、`threadId`、`subscription`；开启桥接时还有 `jobs`，选中会话时含 `history` 或 `error`。`history` 沿用 HTTP 历史响应。网页按订阅标识丢弃旧选择的响应。消息创建、发送与人工核对继续使用现有 HTTP 接口，不通过实时连接自动重发。

`threadIds` 可省略，最多 100 个 UUID；即使 `threadId: null`，仍可订阅侧边栏状态。开启桥接时响应包含 `threadStatuses: {"UUID":{"state":"running","label":"执行中"}}`。状态有 running、idle、waiting、notLoaded、error、loading、unknown，分别表示执行中、空闲、待处理、未加载、运行异常、检测中、状态未知。

状态取自原生 threadRuntimeStatus 和待处理请求，不从更新时间、最后一条消息或 ConnectNow 投递日志推断。同一桥接的页面订阅共享原生 watch 与后台发现，关闭一个页面不会撤销其他页面仍需的 watch。请求核验由共享后台执行，WS 写线程只读取保存的请求状态。首次后台读取快照，最多同时进行 4 个 owner 查询；后续原生事件通过同一 WS 推送。未加载/暂不可查的会话每 30 秒重试发现。首次查找需要时间，不保证所有会话立即就绪；关闭桥接停止订阅，网页断线时立即将徽标置为状态未知。

页面默认订阅当前搜索结果的前 100 条；超过时明确提示订阅范围，可通过搜索缩小范围。数量统计只针对这些列表会话，不代表整个 Codex 的全局运行总数。

本地 IPC 接收 `snapshot` 与 `patches`（版本 11）；补丁必须匹配 owner、会话和 `baseRevision`。重复旧版本忽略，版本缺口或无法应用的补丁触发重新同步。原生隐藏推理依然不投影到网页。

最多 16 个实时连接；请求消息最大 100 KB，响应最大 32 MiB。空闲时发送 Ping 保活。客户端断线后可退避重连、重新认证和订阅，恢复的是当前快照，不是断线事件回放。仅有旧 rollout 的会话仍属于降级文件历史，不具备原生实时事件保证。

### 临时聊天抽屉（只读）

在现有 subscribe 消息中添加 `includeSideChats: true`，并设置主会话 `threadId`。服务返回 `sideChats: {chats,scanning,error,scope}`，每个 chat 含 `id,parentId,title,state,label`。首次异步扫描 App 的 client-thread-bindings-v1 候选记录，必须再由原生快照证实 ephemeral/sideConversation 为 true 且 forkedFromId 匹配主会话。候选最多 100 条，未找到不代表不存在；扫描后最早 30 秒可再次启动。

选择临时聊天时，在同一订阅附上 `sideThreadId`，服务返回独立的 `sideHistory`、`sideThreadId` 或 `sideError`；主会话的 history 不变。sideHistory 沿用完整时间线格式并附 parentId。关闭抽屉传 `includeSideChats:false, sideThreadId:null`；取消桥接后不返回这些数据。

外部程序可使用同等鉴权的只读 HTTP 接口：

- `GET /api/side-chats?parentId=主会话UUID`：触发/查看发现结果。
- `GET /api/side-chats/临时聊天UUID/history?parentId=主会话UUID`：必须先发现并核验父子关系；每次读取再次检查原生关联。

不提供临时聊天创建或发送接口，不修改 App 布局、侧聊天生命周期或 Codex 数据库。未知父子关系拒绝访问；临时聊天过期时不退回另一会话的历史。


## 会话操作 API

`POST /api/threads/{threadId}/operations`（Bearer Token，同源/桥接门禁与其他接口相同）。只支持目录中的普通本机会话；侧边临时聊天仍只读。返回 HTTP 202 和持久化 job，使用 `/api/jobs/{requestId}` 或现有 WS jobs 跟踪结果。

```json
{"requestId":"unique-operation-001","action":"interrupt","expectedTurnId":"当前执行轮次 ID"}
```

| action | 额外字段 | 条件 |
|---|---|---|
| interrupt | expectedTurnId | 当前 active 轮次，使用原生 user-stop / v4 |
| steer | expectedTurnId、prompt | 当前 active 轮次，纯文本补充 |
| compact | 无 | 空闲，无待处理请求 |
| settings | settings: 原生设置对象 | 空闲或执行中，至少一个字段；影响后续轮次 |
| edit | turnId、prompt、confirmed: true | 空闲，必须是最后一轮；替换并重新执行 |
| clear-queue | confirmed: true、queueFingerprint | 清空当前会话全部原生排队消息 |
| command-approval | nativeRequestId、requestFingerprint、decision | 支持全部原生决定（包括对象），遵守 availableDecisions |
| file-approval | 同上 | 同上 |
| permissions-approval | nativeRequestId、requestFingerprint、decision | decision: accept/decline + scope，或 response 对象；支持 turn/session 和 strictAutoReview，授权不超出原请求范围 |
| user-input | nativeRequestId、requestFingerprint、answers | answers 为 questionId → 字符串数组，必须覆盖当前全部问题 |
| mcp-response | nativeRequestId、requestFingerprint、response | response: {action: accept/decline/cancel, content?: object/null}；原生安全校验继续生效 |

设置支持 `approvalPolicy`、`approvalsReviewer`、`collaborationMode`、`cwd`、`effort`、`model`、`multiAgentMode`、`permissions`、`personality`、`sandboxPolicy`、`serviceTier`、`summary` 以及桌面层 `activePermissionProfile`。字段省略保持不变，null 按原生语义处理。模型、effort、serviceTier 的实际可用值由 App 决定；不在 ConnectNow 中硬编码模型能力。`multiAgentMode` 在当前原生 schema 标为 deprecated/ignored，接入不代表该字段仍生效。

契约保存于 `connectnow/native_contracts.json`，来自本机 App 所带 codex 的 `app-server generate-json-schema --experimental`；activePermissionProfile 来自桌面 j9t/N9t 处理逻辑。仅接受已知字段，嵌套结构、枚举和必填项均校验；`permissions` 或 `activePermissionProfile` 与 `sandboxPolicy` 不可同时指定。cwd 使用绝对路径。ConnectNow 不自行猜测权限配置 ID。


`GET /api/threads/{id}/history` 和 WS history 中新增 `controls`：activeTurnId、lastTurnId、lastUserText、settings、requests。每个可回应请求包含 id（保留原生数字/字符串类型）、action、method、fingerprint、params、decisions（可提交的完整审批值）。回应必须原样携带 id 和 fingerprint，后端重新获取原生快照，校验请求仍存在、方法匹配、内容未变。未适配的请求继续使用 Codex App。

```json
{"requestId":"answer-operation-001","action":"user-input","nativeRequestId":7,"requestFingerprint":"从 controls.requests 获取","answers":{"question-id":["继续"]}}
```

操作 job 的 kind 为 `operation:<action>`。`completed` 表示原生处理入口已返回，页面显示“原生入口已响应”；不表示新启动的推理、压缩或工具执行已结束，最终运行状态以 WS 为准。`result` 保留原生结果，包括可能的 goalPauseError；`failed` 表示已知失败，`uncertain` 表示可能已投递，禁止自动重发。重试 HTTP 必须复用相同 requestId 和完整内容；内容冲突返回 409。结果待确认时须在 App 核对，再使用原有 acknowledge 接口。

原生 steer、edit 和审批接口没有统一的条件版本写入协议：本地在写入前核验状态，但不能消除 App 在核验与处理间变化的竞态。interrupt 额外向原生传递 expectedTurnId。不要同时在多个界面提交冲突操作。新增适配以桌面 26.901.51231 为依据，尚未逐项完成真实 App 端到端验证。


### 队列管理

`GET /api/threads/{id}/queue` 返回 `{messages, fingerprint, source}`。相同对象也随 HTTP history 和 WS history.queue 返回。先从 Codex 的 queued-follow-ups 持久状态只读加载，随后接收该会话 owner 的原生队列广播。读取失败时不把未知队列当成空队列。

以下操作使用同一个 `/operations` 入口，均须携带刚读取的 `queueFingerprint`：

| action | 额外字段 |
|---|---|
| queue-add | prompt |
| queue-edit | messageId、prompt |
| queue-delete | messageId |
| queue-reorder | messageIds：当前全部消息 ID，按目标顺序排列且每个仅出现一次 |
| queue-resume | messageId：清除原生 pausedReason，交回原生调度器 |
| clear-queue | confirmed: true |

队列可以在执行中或空闲时管理；执行时机由 Codex 原生调度器决定。新增消息使用原生 id/text/context/cwd/createdAt 结构；编辑和重排保留已有附件及其他上下文。存在需原生确认的 untrusted app input 时不会移除标记来绕过确认。

指纹不匹配将拒绝投递；ConnectNow 内的操作串行并且不自动重试。原生接口是整组队列替换，没有原子 CAS：即使写入前再次检查，仍不能完全避免另一 App 窗口恰好同时改队列。不要同时在两个界面编辑队列；有冲突或结果不明应重新读取并人工核对，而不是盲目重放。

```json
{"requestId":"queue-request-001","action":"queue-add","queueFingerprint":"从 queue 接口获取","prompt":"当前任务结束后继续检查测试结果"}
```

### 全部审批选项

命令/文件回应的 `decision` 可以直接使用 controls.requests[].decisions 中的完整值，包括 `acceptForSession`。命令还支持：

```json
{"acceptWithExecpolicyAmendment":{"execpolicy_amendment":["git","status"]}}
```

```json
{"applyNetworkPolicyAmendment":{"network_policy_amendment":{"host":"example.com","action":"allow"}}}
```

对象规则必须与当前原生请求给出的可选规则一致。未提供 availableDecisions 时，使用原生标准决定，加上请求的 proposedExecpolicyAmendment/proposedNetworkPolicyAmendments；不构造额外授权范围。

权限请求支持 `response: {permissions, scope: "turn"|"session", strictAutoReview?: boolean|null}`，可授予原请求的全部或部分权限；也兼容 `decision: "accept"|"decline", scope?: "turn"|"session"` 的简写。

### 通知与订阅恢复

已接入以下消息：

- thread-stream-following-status-requested：向已确认的 owner 重申 following。
- ipc-connection-reset：使快照和队列缓存失效，将在途请求标为结果可能未知，重新获取已订阅会话；不重放操作。
- thread-read-state-changed：更新 hasUnreadTurn，页面标题前显示未读标记。
- thread-archived / thread-unarchived：更新归档提示并触发目录刷新；这是接收通知，不是发起归档接口。
- thread-queued-followups-changed：接收 owner 的消息列表并即时同步。

WS update 新增 `catalogRevision` 和 `threadFlags`（仅当前订阅目录），`GET /api/coordination` 返回 `{catalogRevision, resetRevision, threadFlags}`。这些是内存通知投影；重连会失效，归档目录仍以 Codex 数据库为准。队列通知只接受当前 owner；历史 patch 的 owner/版本校验保持不变。套接字实际断开后仍需重新开启桥接，与收到可用连接上的 reset 通知不同。

设置快照可能同时包含命名权限配置及其解析后的 sandboxPolicy；更新请求不能同时发送这两种表示。页面预填“全部设置”时优先保留命名配置并移除重复的 sandboxPolicy。外部调用请发送希望修改的字段；改用显式 sandboxPolicy 时，移除 permissions/activePermissionProfile。

## 本地服务与云端连接管理

这些接口仍需本地 Bearer Token；云端通道禁止访问。自定义云端后端见 [CLOUD.md](CLOUD.md)。

| 方法 | 路径 | 输入 / 返回 |
|---|---|---|
| GET | `/service` | 返回 `instanceId,pid,port,version,codexHome` |
| POST | `/service/stop` | `{}`；响应后停止后台服务 |
| GET | `/cloud` | 返回连接配置和在线状态，不返回 Token |
| POST | `/cloud` | `{enabled:true,url,deviceId,token,control:false,devLocal:false}`；先关闭旧连接再保存并连接 |
| POST | `/cloud` | `{enabled:false}`；断开并清除已保存的连接凭证 |

生产地址必须为 `wss://`。只有显式 `devLocal:true` 才接受 loopback `ws://`。`control:true` 允许全部已支持的远程写操作，包括审批；本地桥接开关仍是前置条件。

## 随消息发送图片

`POST /threads/{id}/messages` 可带 `images` 数组，元素为 `data:image/jpeg;base64,...`（也支持 PNG、WebP）。最多 3 张，每张解码后最多 200 KiB；有图片时 `prompt` 可以是空字符串。HTTP JSON 总体积仍须不超过 900,000 字节。本地和云端使用相同字段，云端必须已获远程控制权限。

example 支持选择或粘贴图片、预览与移除，浏览器将图片转成 JPEG，长边最多 1600 像素并压缩至传输限制以内。透明区域以白色填充；需要保留原始细节时可先裁剪关注区域。图片可单独发送，也可附带文字。新建会话暂不附图，先进入会话后发送。

图片按原生 `UserInput {type: "image", url: dataURL}` 交给 Codex，不接收外部 URL 或本地文件路径，不建立公开图片链接。图片内容参与幂等指纹计算；相同 requestId 对应的文字或图片改变都会被拒绝。浏览器会话存储和 ConnectNow 请求日志不存图片内容，原生会话仍按 Codex 的历史规则保存消息。


### 会话图片回显

原生 `image` 输入保持图片类型，example 直接渲染图片；`localImage` 投影增加 `imageId`。
`GET /api/threads/{id}/images/{imageId}`（临时会话对应 `/api/side-chats/{id}/images/{imageId}?parentId=...`）返回 `{url: "data:image/..."}`。
接口沿用会话读取认证、桥接开关和云端只读权限，只解析该会话原生用户消息中的图片附件，不接受任意文件路径。
本地图片读取限普通文件、8 MB 以内的 PNG/JPEG/WebP/GIF，拒绝符号链接；文件已删除或不可读时页面明确提示，不展示 Base64 或以路径代替图片。图片按可见区域加载，不写入浏览器持久存储。

## 本机配置入口

本机配置由 CLI 和桌面端共享。`POST /api/bridge`、`/api/controller`、`/api/cloud*`、`/api/service*`、`/api/notifications/preferences` 拒绝包含 Origin 或 Sec-Fetch-* 浏览器标记的请求，即使本机 Bearer Token 有效。网页保留会话交互与读取；云端不能选择本机控制会话。

`GET /api/cloud/link/status` 返回当前服务最新申请的安全投影（idle/pending/bound/expired/failed），包含核对码和状态但不含领取秘密或设备 Token。此接口不触发新申请或凭证领取；后台绑定流程仍为唯一执行者。
