# 项目、动态与通知功能契约

本机与云端共用 Workspace 投影；云端继续按设备路由。移动端设计源位于 `design/mobile`，正式页面通过 `mobile.css` 和 `mobile-ui.js` 复用设计组件，760px 以下加载移动样式，桌面样式独立加载。`?mobile=1` 可在电脑上直接查看 430px 宽的正式移动界面。现有 API 与原生写入门禁继续有效。

## 数据与交互

- 项目归属先读取 Codex 原生项目 ID，再读取无项目标记、桌面项目分配和已保存的项目根目录；不能仅因会话有 cwd 就创建项目。无项目会话合并为“最近”，保留各会话实际 cwd；其分组 ID 为 SHA-256 空字符串。已确认归属的项目按 `SHA-256("native-project:" + 原生项目 ID)` 在设备范围内分组，显示原生项目名并保留全部 rootPaths；不同项目共享目录也不合并，项目改名及根目录重排不改变分组 ID。无明确归属时，目录仅在唯一对应某个已保存项目时映射到该项目；无法唯一对应的目录保留路径分组，不猜测原生归属。旧客户端缓存的目录 ID 仅在唯一对应某个原生项目时允许创建会话，否则拒绝；该兼容入口限于旧缓存创建请求，列表始终返回新 ID。统计读取完整目录索引，不以当前分页计算总数。未加载的原生状态明确计入 unknown。
- 为指定项目创建任务时，控制会话优先选择“最近”无项目分组，再查其他项目，各组按最近更新时间排序。未加载会话通过 Codex 桌面链接打开并读取实时状态（可能切换桌面当前会话），仅明确空闲且无待处理审批、输入或未确认请求时借用。每组有独立的查找时间预算，最近分组不可用不会阻止检查其他分组；底层读取仍受 IPC 超时限制。新任务的目标项目独立校验，不改变借用会话的项目归属；结果仍核对原生工具返回和目标项目。
- 动态按当前 reader 的四类通知偏好展示有未读通知的会话，同一会话去重；新消息、任务完成、执行失败、需要确认任一开启类别命中即可进入动态。读后移出，但开启通知的待确认或失败状态仍保留。未读按会话统计；阅读不会解决原生审批或输入请求。
- 后台采集独立于网页在线状态。message、done、failed 来自原生完整轮次，approval 来自原生待确认请求；不将 token patch 或 Journal 完成当作新消息。首次历史终态建立基线，已有待确认请求仍可通知。持久 eventId 去重跨重连与重启生效。
- 已读游标在历史渲染后推进至捕获的 readSequence；并发到达的新事件保留未读。接收原生 `thread-read-state-changed` 的明确 `hasUnreadTurn=false` 事件时，先投影已收到的会话快照，再将当时的事件上限持久保存为 `native:codex` 已读游标。所有 reader 的有效已读位置取自身与原生游标的较大值，通过 workspaceRevision 推送刷新；后续新事件仍未读，缓存标记与断线期间未收到的事件不推测为已读。不会写回原生 hasUnreadTurn。reader 为 local 或 binding:<id>，同一绑定共用偏好和读游标；不提供独立手机账号身份。
- 四类通知偏好持久保存，保存后通过 workspaceRevision 刷新动态；关闭类别会隐藏对应动态，不删除事件或未读记录，重新开启会恢复仍未读或仍待处理的会话。APNs 开发实现复用这些事件和读游标，未配置 Apple 密钥和签名时仍只有应用内动态，详见 APNS.md。
- 草稿与附件按设备和会话保存在页面内存，切换会话可恢复，刷新页面不保证保留。前台更新保留输入和既有时间线滚动行为。
- compose 由服务端读取最新原生态裁决：idle 发消息、running 补充、waiting 加入原生队列，未知状态拒绝。图片仅支持已确认 idle 的现有会话；新建、编辑和运行中图片能力不宣称支持。无内容且运行中时输入区提供停止。

## API

路径均相对于设备 API；云端使用既有设备代理与绑定授权。

| 方法与路径 | 契约 |
|---|---|
| GET /api/projects | limit/offset/search；projects、total、nextOffset；项目含 id/name/cwd/rootPaths/total/waiting/running/unread/unknown；search 匹配原生名称和全部根目录 |
| GET /api/workspace/threads | 全部会话分页；按原生目录 updated_at 倒序、id 倒序打破同时间排序，支持 limit/offset/search/filter，含实时 status、未读与总数 |
| GET /api/projects/{id}/threads | 项目会话分页；filter=all/waiting/running/unread，支持 search |
| GET /api/activity | 按通知偏好筛选的未读通知及待处理会话分页，不是通知事件流水 |
| GET /api/notifications | after/limit；events、nextSequence，事件含 eventId/threadId/projectId/kind/sequence |
| GET/POST /api/notifications/preferences | preferences；POST 必须提交 message/done/failed/approval 四个布尔值 |
| POST /api/notifications/read | threadId、sequence；单调推进，拒绝超过当前会话事件上限 |
| POST /api/threads/{id}/compose | requestId、prompt、images；保留原有原生写入门禁、来源隔离与幂等语义 |
| GET /api/standby | 只读待机状态；不提供远程启停能力 |

只读绑定可更新自己的通知偏好与读游标，不能因此获得原生控制权。实时包中的 workspaceRevision 提示列表刷新；readSequence 仅在历史显示后确认。离线不自动重放写入，不明确的提交继续使用原 requestId。

## 影响、恢复与边界

新增 workspace.py 和 notification-client.js，复用既有 Journal SQLite 连接。jobs.sqlite 中增加 notification_events、notification_baselines、notification_readers、notification_preferences 四表，不迁移或改写原生 Codex 数据。恢复旧程序时保留数据库，旧程序忽略这些表；不要删除 Journal 或通过换空数据目录重发 uncertain 请求。多云端配置恢复见 MULTI_CLOUD.md。

原生状态后台加载复用现有 realtime loader。125 会话的完整总数与分页有回归覆盖，但大量真实历史的加载容量、长期事件增长和手机实机体验尚未验收。真实模型/思考强度可选列表没有新增来源，页面不能据原型虚构选项。安装包包含正式页面，不把 design/mobile 原型当作已接入后端的移动产品。


## 移动端页面

- 会话首页按项目分组，项目内按全部/待处理/进行中筛选；动态按通知偏好展示未读通知及待处理会话，并独立提供连接申请入口。底部导航为会话、动态、设置，聊天返回进入来源。
- 设置页集中展示工作区卡片、切换、连接申请、移除、待机、通知和退出。在线信息来自设备目录与连接状态，不提供远程提升权限。
- 聊天、新建和编辑复用输入区呈现。新建与编辑使用原稿的全屏页面，新建通过控制会话卡片进入选择页；新建/编辑图片按钮禁用。模型浮层仅展示当前已知值，无权威目录时引导在 Codex App 调整。
- 移动端问题内嵌聊天。右上角按原稿展示平铺的会话操作分组，移动端隐藏显示选项及重复停止、补充、加入队列入口；原生队列内容直接显示在聊天中。桌面宽度恢复原有控件位置。
- 手机返回列表或设置后，后台聊天更新不推进已读；重新显示聊天后随历史更新确认已读。切换工作区先保存当前会话内存草稿，再清理视图。
- 分发包含正式移动资源，不加载原型脚本或模拟数据。桌面浏览器的移动尺寸验证不能替代手机实机键盘、安全区和系统推送验收。

### Codex 已读同步验证（2026-09-12）

本次复用 notification_readers 表新增 `native:codex` reader，不改表结构、不写 Codex 数据。IPC 已读事件仅处理当前连接及目录内会话；消费者继续使用现有 workspaceRevision 刷新机制。若恢复旧实现，仅移除本次事件接入与有效游标计算，保留 Journal 数据及其他并行改动。

`PYTHONPATH=tests python3 -m unittest test_console_socket.ConsoleSocketTests.test_native_read_pushes_revision_and_clears_remote_projection test_workspace test_ipc test_realtime test_full_ipc`：45 项通过。真实 socket 测试覆盖已读事件触发 WS 修订更新、授权远程项目查询清除未读，另覆盖多 reader、重启持久化、新事件、迟到旧连接、非法协议事件与待处理状态保留。原生消息源使用测试夹具，未验证真实 Codex 阅读操作和 iOS 真机显示，未部署。共享已读状态变更按 R2 保留独立审查门禁；侧边会话禁止子代理，本次仅完成实施自检，发布前仍需独立审查和端到端验收。

### iOS 首页视图

“会话”标题旁可切换项目与会话视图，本机 UserDefaults 保存选择，默认项目视图。项目使用独立文件夹卡片并沿用既有项目排序；会话视图读取完整工作区分页投影，按原生目录最近更新时间倒序，不受通知偏好筛选。气泡图标仅在原生状态为 running 时标绿，状态未知或断线不推测正在执行。

### 会话页其他任务角标

会话页左上角按当前工作区、当前绑定的动态规则统计其他会话，排除正在查看的会话，按会话去重，不计连接申请。`GET /api/activity` 支持 `currentThreadId`，返回全量筛选结果中的 `currentThreadIncluded`，客户端从 total 扣除当前会话；`excludeThreadId` 用于点击角标后的其他会话列表。workspaceRevision 变化时刷新统计，后台目录刷新仍会定期核对。已读完成项移出，待审批项阅读后仍保留；不新增系统推送实现。

## 本机工作区运行边界

工作区登记保存 `backend` 和 `codexHome`。默认目录由 `CARRYON_HOME`（未设置时为
`~/Library/Application Support/CarryOn`）确定；登记后的后端类型在重启时保持。

- 默认工作区使用 `desktop-ipc`，连接 Codex 桌面端的 `CODEX_HOME/ipc/ipc.sock`。
- 新建工作区使用 `app-server`，默认 Home 为 `<CarryOn 工作区目录>/codex-home`。
  自定义 Home 经过真实路径解析，不能与其他已登记工作区共用。服务独占 Home 锁，
  通过 stdio 管理自己的 app-server；关闭、重连只处理自己创建的进程。
- 首次启动仅复制默认 Codex 的 `auth.json` 和模型、供应商配置。
  不导入会话数据库、rollout、项目、插件、hooks 或审批策略；已有文件优先，初始化标记
  防止后续从默认工作区覆盖独立配置。模型配置导入使用运行时自带的 `tomllib`（Python 3.11+）。
- 独立工作区可以从“最近”直接创建首个会话，不需要控制会话。无项目任务的工作目录为
  `<CarryOn 工作区目录>/tasks/<请求ID>`。创建和首轮发送均记录投递状态；结果未知时不自动重发。
- 后端在 `controls.supportedOperations` 声明已适配的操作。当前独立工作区支持发送、
  补充指令、停止、压缩和原生审批/问题响应；桌面专属队列、编辑/重新执行和设置写入
  不展示操作入口，服务端也拒绝调用。模型配置可在独立 Home 内维护。
- 状态列表读取元数据，不批量恢复全部会话；选择会话时才恢复并读取历史，后续通过通知更新。

### 旧共享目录与恢复

旧版本非默认工作区若登记为默认 Codex Home，新版启动时解析为自己的 `codex-home`。
原有桌面会话仍留在默认 Home，不移动、不删除；这个行为不是历史迁移。
运行中的旧服务不会因修改源码而切换后端，必须使用新版服务重启后才生效。
回退程序前保留 `services.json`、工作区 Home 和 CarryOn 状态目录；独立 Home 不应重新连接到
桌面 IPC。启动失败保留配置，查看工作区的 `server.log` 和 Home 内的 `app-server.log`。

验证：`python3 -m unittest discover -s tests -p test_workspace_backends.py`；
`python3 tests/run_appserver_regression.py` 使用已安装 Codex、临时 Home 和本地假模型服务，
验证真实进程隔离、首建、流式历史、重复请求、停止、重启与崩溃恢复，不调用真实模型。

会话列表的未读筛选按当前 reader 在分页前计算；动态中待处理项优先，显式清空已读的语义保持不变。iOS 保留再次点击会话标签切换项目/全部会话的入口。

iOS 全局“显示不活跃会话”默认关闭，持久保存于当前手机并跨工作区生效。列表显式传 availableOnly=true：仅显示原生完整快照状态为 idle/running/waiting 的会话，项目聚合与分页前过滤。开启后传 false，显示全部；未加载会话进入后提示先在桌面 Codex 打开，写权限不变。API 省略参数保持旧行为，通知/直达查询不受列表偏好拦截。
