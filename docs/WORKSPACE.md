# 项目、动态与通知功能契约

本机与云端共用 Workspace 投影；云端继续按设备路由。移动端交互以官方 Remote 为对齐来源，正式页面由 `mobile.css` 和 `mobile-ui.js` 实现，760px 以下加载移动样式，桌面样式独立加载。`?mobile=1` 可在电脑上直接查看 430px 宽的正式移动界面。现有 API 与原生写入门禁继续有效。

## 数据与交互

- 项目目录统一只读 Codex 原生数据库的 `projects` / `project_roots`；项目归属先读取会话的原生 `project_id`，再读取无项目标记和原生项目根目录；旧 JSON 的 `local-projects` 与 `thread-project-assignments` 不作为项目身份来源；不能仅因会话有 cwd 就创建项目。无项目会话合并为“最近”，保留各会话实际 cwd；其分组 ID 为 SHA-256 空字符串。已确认归属的项目按 `SHA-256("native-project:" + 原生项目 ID)` 在设备范围内分组，显示原生项目名并保留全部 rootPaths；不同项目共享目录也不合并，项目改名及根目录重排不改变分组 ID。无明确归属时，目录唯一对应已保存项目则直接归类；同一根目录被多个项目共享时，按 Codex 侧边栏规则依次优先选择单根目录项目、以该目录为首根的项目、创建时间较早的项目、ID 较大的项目。这只影响展示分类，不写回原生绑定。不同根目录仅因共享 Git 仓库而产生的多项目歧义仍保留路径分组。创建会话仅接受当前列表返回的原生项目分组 ID；目录哈希 ID 无法替代原生项目 ID。统计读取完整目录索引，不以当前分页计算总数。未加载的原生状态明确计入 unknown。
- 为指定项目创建任务时，临时 app-server 按原生项目 ID 和目录创建分页会话，Owner 接管同一进程后通过 IPC 投递原始任务。桌面工作区的项目列表包含尚无会话的原生项目，创建校验复用同一项目目录；创建无需已有会话；任务结束后自动释放进程；仍有客户端订阅时保留 Owner 连接，后续消息按需恢复进程。
- 动态按当前 reader 的四类通知偏好展示有未读通知的会话，同一会话去重；新消息、任务完成、执行失败、需要确认任一开启类别命中即可进入动态。读后移出，但开启通知的待确认或失败状态仍保留。未读按会话统计；阅读不会解决原生审批或输入请求。
- 后台采集独立于网页在线状态。message、done、failed 来自原生完整轮次，approval 来自原生待确认请求；不将 token patch 或 Journal 完成当作新消息。首次历史终态建立基线，已有待确认请求仍可通知。持久 eventId 去重跨重连与重启生效。
- 手机已读游标在历史渲染后推进至捕获的 readSequence。桌面已读以当前账号及本地主机的 `electron-thread-read-state-v1` 持久记录为权威，原生事件触发核对；`native:codex:<identity hash>` 游标按账号隔离。完整刷新主动核对漏收的已读事件，不依赖 owner 默认的 hasUnreadTurn=false。清读只推进连续事件前缀：原生完成时间不得晚于文件快照时间；没有原生完成时间的事件还必须在刷新前已存在，且发现时间早于文件快照。新消息、身份切换、存储损坏、主机不匹配及断线均不能授权清读，不写回 Codex 文件。reader 为 local 或 binding:<id>，同一绑定共用偏好和手机读游标。
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

原生状态后台加载复用现有 realtime loader。125 会话的完整总数与分页有回归覆盖，但大量真实历史的加载容量、长期事件增长和手机实机体验尚未验收。真实模型/思考强度可选列表没有新增来源，页面不能据原型虚构选项。安装包只包含正式页面；已删除不接入后端的旧移动演示。


## 移动端页面

- 会话首页按项目分组，项目内按全部/待处理/进行中筛选；动态按通知偏好展示未读通知及待处理会话，并独立提供连接申请入口。底部导航为会话、动态、设置，聊天返回进入来源。
- 设置页集中展示工作区卡片、切换、连接申请、移除、待机、通知和退出。在线信息来自设备目录与连接状态，不提供远程提升权限。
- 聊天、新建和编辑复用输入区呈现。新建与编辑使用原稿的全屏页面，新建通过项目卡片进入选择页；新建/编辑图片按钮禁用。模型浮层仅展示当前已知值，无权威目录时引导在 Codex App 调整。
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
- 新建工作区使用 `app-server`，Home 为 `<CarryOn 工作区目录>/codex`，路径随登记保存。
  自定义 Home 经过真实路径解析，不能与其他已登记工作区共用。服务独占 Home 锁，
  通过 stdio 管理自己的 app-server；关闭、重连只处理自己创建的进程。
- 新建工作区仅写入最小审批与沙盒配置，并在自己的 Codex Home 中独立登录。
  不复制默认工作区的凭据、模型配置、会话或历史。
- 独立工作区可以从“最近”直接创建首个会话，不需要控制会话。无项目任务的工作目录为
  `<CarryOn 工作区目录>/tasks/<请求ID>`。创建和首轮发送均记录投递状态；结果未知时不自动重发。
- 后端在 `controls.supportedOperations` 声明已适配的操作。当前独立工作区支持发送、
  补充指令、停止、继续、压缩、原生队列、设置与审批/问题响应。队列由原生自动执行，
  中断后的剩余项通过原生 queue/start 继续；不维护另一套后台调度。能力按当前快照显示。
  新建会话支持图片与首轮模型/思考强度设置。
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

会话列表的未读筛选按当前 reader 在分页前计算；动态中待处理项优先，显式清空已读的语义保持不变。iOS 首页同屏展示项目与最近会话，顶部菜单保留全部列表、搜索、动态和设置入口。

iOS 全局“显示不活跃会话”默认关闭，持久保存于当前手机并跨工作区生效。会话/项目列表传 availableOnly=true：保留原生完整快照状态为 idle/running/waiting 的会话，以及尚未取得快照、仍在检测或探测失败的会话；确认未加载（原生 notLoaded 或 IPC no-client-found）后才隐藏。available 字段仍只表示已取得可用完整快照，检测中不代表可发送。过滤在项目聚合与分页前执行；动态的 availableOnly 仍只保留已确认可用会话，通知与已读语义不变。开启后传 false 显示全部；API 省略参数显示全部。

列表可见会话优先探测，后台按上次尝试顺序轮转，总并发上限 4；失败的 30 秒重试间隔不会让尚未探测的会话长期排在队尾。HTTP 与实时订阅共用原生快照及探测结果，结果变化会刷新工作区版本。项目、会话及动态列表 GET 的 `sync=full` 发起当前工作区完整同步，`syncId=<id>` 查询同一任务；返回 `sync.state=running/completed/failed`。iOS 下拉刷新等待终态才结束，失败显示错误。同步重读完整目录与项目配置，对目录内所有会话重新读取原生状态（最多 4 并发，不按列表分页截断），更新动态、统计和桌面已读游标；确定无原生 owner 的会话标为未加载，不恢复任务、不发送消息。已有历史快照也重读。独立 app-server 工作区只读会话元数据并保留订阅历史，不套用桌面账号已读数据。手动和后台目录读取串行；旧客户端的 refreshStatuses=true 保留目录同步和缺失状态探测入口，iOS 同时传 sync=full 使用完整流程。


## 工作区与多个执行连接

工作区组织连接，并在电脑端明确确认加入后统一管理成员权限；连接是执行、审批和传输凭证边界。当前本机登记按解析后的 Codex Home 将
`desktop-ipc` 和 `codex-cli` 归入一个工作区；独立 `app-server` 保留独立工作区。
同一工作区可浏览同一项目的不同来源会话，不新增或复制 Codex 项目目录，不修改原生项目归属。
分组不证明实时运行时相同，不合并同 ID 会话的运行状态、审批或写入队列。

本机 `services.json` 保留每条服务登记，增加 `workspaceId/workspaceName`。
登记/启动时在已有目录锁内补齐分组，保留既有端口、Home、socket、凭证、投递日志和绑定。
先注册 CLI 再注册桌面端时保留原分组 ID；桌面连接换 Home 时重新归组。
被移除的登记不参与分组，不隐式复活。服务进程启动时取得展示描述，不热切换执行端点。

连接在认证 hello 中提供 `workspace: {id, name, backend}`；Console 校验设备凭证后持久保存，
在目录中按绑定所有者命名空间化 ID，过滤不可见连接。目录即使离线也可显示已有分组。
该展示元数据不授予访问权；共用授权需经过电脑端预览与明确确认。
请求、实时订阅、读游标、审批和移除仍使用原 device ID，权限从工作区的单一成员记录读取。
缺少元数据的旧服务单独展示，不能按名称、主机名或会话 ID 猜测合并。

iOS 工作区列表按组显示各连接的在线状态和当前选择；首页提供当前组的连接切换。
切换先保存草稿，再取消旧订阅、清理旧状态，向所选连接重新读取。
草稿、缓存、未知提交记录和审批目标仍按服务地址/device ID/thread ID 隔离，旧目标不能投到新连接。
手机前台只订阅当前选中连接；电脑上的多个连接可以同时在线，任务不会因切换或手机断线停止。
移除操作撤销所选连接，不移除整组或停止原生任务。

### 升级与恢复

部署新版本机服务、Console 和 iOS 后，重启各本机连接使 hello 重新发布元数据。
旧 iOS 可以忽略分组字段并继续按独立连接显示；共享绑定要求 Console 支持 `workspaceAuthority`。回退时保留 `services.json`、
`devices.json` 与各连接状态目录；不删除凭证、Journal 或原生历史，不通过重发不确定写入恢复。
本次实现与隔离验证见 `docs/reviews/2026-10-19-workspace-connections.md`。


### 一次绑定、多个连接的授权契约

第一次扫码建立工作区账号授权。添加同机同 Home 的新连接时，`carryon init` 和 CarryOn
桌面端初始化页提供“使用已有工作区绑定”；电脑端先读取当前成员及权限，再明确确认。
本机校验来源登记与目标工作区相同、云端绑定有效、凭证及远程操作开关未改变。
云端使用来源连接 token 认证，确认请求必须携带预览 revision；成员变更后必须重新预览。
请求来自浏览器 Origin 时拒绝。新连接得到独立 device ID/token，不复制任何成员列表。

`devices.json` 中 `workspaceAuthority` 指向唯一成员权威记录，未加入的旧连接继续使用自身
members。授权变更与读取共用同一解析逻辑；撤销查看权限会关闭该账号在全部关联连接的订阅。
删除权威记录所在的连接时，在同一次原子保存中把成员和加入请求记录转移到剩余连接；
被删除的凭证失效，其他连接继续运行。既有独立扫码的连接不按名称或目录自动合并权限。

本机加入请求保存在 `shared-connection.json`，先保存 request ID 再请求云端。
响应丢失、进程重启、安装凭证失败后重试原 request ID；状态接口和 CLI/桌面界面提供继续确认入口。
云端幂等返回原连接凭证；已移除连接的旧加入请求拒绝重放。成功记录不阻止以后明确绑定其他云端。
多云端的地址、凭证和成员权威分别处理，某一云端的待恢复请求不覆盖其他已完成绑定。

回退到不识别 `workspaceAuthority` 的旧服务端会使新增连接失去授权读取能力（子记录没有 members），
不能通过复制旧权限“兼容”。回退前保留 devices.json 与各连接目录，恢复支持该契约的版本后核对。
实施与验证记录见 `docs/reviews/2026-10-19-shared-binding.md`。
