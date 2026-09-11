# 项目、动态与通知功能契约

本机与云端共用 Workspace 投影；云端继续按设备路由。移动端设计位于 `design/mobile`，本次正式功能仅复用现有页面样式。

## 数据与交互

- 项目 ID 来自完整 cwd 的 SHA-256，并处于设备范围内。同名目录不合并；统计读取完整目录索引，不以当前分页计算总数。未加载的原生状态明确计入 unknown。
- 动态展示去重后的待处理会话。未读按会话统计；阅读不会解决原生审批或输入请求。
- 后台采集独立于网页在线状态。message、done、failed 来自原生完整轮次，approval 来自原生待确认请求；不将 token patch 或 Journal 完成当作新消息。首次历史终态建立基线，已有待确认请求仍可通知。持久 eventId 去重跨重连与重启生效。
- 已读游标在历史渲染后推进至捕获的 readSequence；并发到达的新事件保留未读。不会写回原生 hasUnreadTurn。reader 为 local 或 binding:<id>，同一绑定共用偏好和读游标；不提供独立手机账号身份。
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
