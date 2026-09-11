# 项目、动态与通知功能契约

本机与云端共用 Workspace 投影；云端继续按设备路由。移动端设计源位于 `design/mobile`，正式页面通过 `mobile.css` 和 `mobile-ui.js` 复用设计组件，760px 以下加载移动样式，桌面样式独立加载。`?mobile=1` 可在电脑上直接查看 430px 宽的正式移动界面。现有 API 与原生写入门禁继续有效。

## 数据与交互

- 项目归属先读取 Codex 原生项目 ID，再读取无项目标记、桌面项目分配和已保存的项目根目录；不能仅因会话有 cwd 就创建项目。无项目会话合并为“最近”，保留各会话实际 cwd；其分组 ID 为 SHA-256 空字符串。已有项目仍按完整 cwd 的 SHA-256 在设备范围内分组，同名目录不合并。统计读取完整目录索引，不以当前分页计算总数。未加载的原生状态明确计入 unknown。
- 动态展示去重后的待处理会话。未读按会话统计；阅读不会解决原生审批或输入请求。
- 后台采集独立于网页在线状态。message、done、failed 来自原生完整轮次，approval 来自原生待确认请求；不将 token patch 或 Journal 完成当作新消息。首次历史终态建立基线，已有待确认请求仍可通知。持久 eventId 去重跨重连与重启生效。
- 已读游标在历史渲染后推进至捕获的 readSequence；并发到达的新事件保留未读。接收原生 `thread-read-state-changed` 的明确 `hasUnreadTurn=false` 事件时，先投影已收到的会话快照，再将当时的事件上限持久保存为 `native:codex` 已读游标。所有 reader 的有效已读位置取自身与原生游标的较大值，通过 workspaceRevision 推送刷新；后续新事件仍未读，缓存标记与断线期间未收到的事件不推测为已读。不会写回原生 hasUnreadTurn。reader 为 local 或 binding:<id>，同一绑定共用偏好和读游标；不提供独立手机账号身份。
- 四类通知偏好持久保存；静音不删除动态或未读。当前仅完成事件、偏好和读游标，尚无系统或锁屏推送。首发 PWA/原生平台待确定，订阅注册、投递与点击恢复均未实现。
- 草稿与附件按设备和会话保存在页面内存，切换会话可恢复，刷新页面不保证保留。前台更新保留输入和既有时间线滚动行为。
- compose 由服务端读取最新原生态裁决：idle 发消息、running 补充、waiting 加入原生队列，未知状态拒绝。图片仅支持已确认 idle 的现有会话；新建、编辑和运行中图片能力不宣称支持。无内容且运行中时输入区提供停止。

## API

路径均相对于设备 API；云端使用既有设备代理与绑定授权。

| 方法与路径 | 契约 |
|---|---|
| GET /api/projects | limit/offset/search；projects、total、nextOffset；项目含 id/name/cwd/total/waiting/running/unread/unknown |
| GET /api/projects/{id}/threads | 项目会话分页；filter=all/waiting/running，支持 search |
| GET /api/activity | 待处理会话分页，不是通知事件流水 |
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

- 会话首页按项目分组，项目内按全部/待处理/进行中筛选；动态展示待处理会话，并独立提供连接申请入口。底部导航为会话、动态、设置，聊天返回进入来源。
- 设置页集中展示工作区卡片、切换、连接申请、移除、待机、通知和退出。在线信息来自设备目录与连接状态，不提供远程提升权限。
- 聊天、新建和编辑复用输入区呈现。新建与编辑使用原稿的全屏页面，新建通过控制会话卡片进入选择页；新建/编辑图片按钮禁用。模型浮层仅展示当前已知值，无权威目录时引导在 Codex App 调整。
- 移动端问题内嵌聊天。右上角按原稿展示平铺的会话操作分组，移动端隐藏显示选项及重复停止、补充、加入队列入口；原生队列内容直接显示在聊天中。桌面宽度恢复原有控件位置。
- 手机返回列表或设置后，后台聊天更新不推进已读；重新显示聊天后随历史更新确认已读。切换工作区先保存当前会话内存草稿，再清理视图。
- 分发包含正式移动资源，不加载原型脚本或模拟数据。桌面浏览器的移动尺寸验证不能替代手机实机键盘、安全区和系统推送验收。

### Codex 已读同步验证（2026-09-12）

本次复用 notification_readers 表新增 `native:codex` reader，不改表结构、不写 Codex 数据。IPC 已读事件仅处理当前连接及目录内会话；消费者继续使用现有 workspaceRevision 刷新机制。若恢复旧实现，仅移除本次事件接入与有效游标计算，保留 Journal 数据及其他并行改动。

`PYTHONPATH=tests python3 -m unittest test_console_socket.ConsoleSocketTests.test_native_read_pushes_revision_and_clears_remote_projection test_workspace test_ipc test_realtime test_full_ipc`：45 项通过。真实 socket 测试覆盖已读事件触发 WS 修订更新、授权远程项目查询清除未读，另覆盖多 reader、重启持久化、新事件、迟到旧连接、非法协议事件与待处理状态保留。原生消息源使用测试夹具，未验证真实 Codex 阅读操作和 iOS 真机显示，未部署。共享已读状态变更按 R2 保留独立审查门禁；侧边会话禁止子代理，本次仅完成实施自检，发布前仍需独立审查和端到端验收。
