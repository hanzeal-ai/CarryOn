# 移动端功能交接

## 权威与修改边界

设计仅修改 design/mobile。正式绑定契约以 docs/MULTI_CLOUD.md 为准：本机输入 HTTPS 云端地址申请，云端管理员核对设备名称、申请时间和两端确认码后确认/拒绝；确认自动登记设备，默认只读。本机后台继续领取凭证，Codex 不可用不丢绑定。多本机与多云端独立绑定，授权/解除在本机逐绑定管理，云端只能撤销本云端设备。移除不保证撤回在途操作。

## 用户已确认的产品契约

| 功能 | 验收条件 |
|---|---|
| 项目 → 会话 | 使用设备/工作区加稳定项目 ID，不能按名称合并；分页不改变汇总总数；同一行同时显示待处理、进行中、未读会话数 |
| 动态 | 直接展示需要处理的会话并去重，阅读不消除审批；解决后移出；连接申请单独分组，不伪装成会话 |
| 未读 | 项目统计未读会话而非 token/事件数；进入会话按已展示序号标读；当前可见会话直接更新内容，保留草稿、附件、焦点、滚动 |
| 通知 | 系统通知，无 App 内仿系统横幅，无模拟通知入口；新消息/完成/失败/需确认分类设置 |
| 统一输入 | 新建、编辑、对话共用附件/模型/发送组件；问题回答只提交文本；停止与发送按执行态和输入内容切换 |
| 自动发送策略 | 运行时补充，是否排队由原生能力与服务端决定；离线不排队重发；未知结果不换 requestId |
| 工作区 | 卡片内切换，绿在线/灰离线/红异常；连接申请核对确认；移除有撤销凭证与在途操作说明；无远程提升权限开关 |

## 正式实现缺口及数据建议

1. 持久事件：eventId/sequence、binding/device/thread/turn/request 标识、type、摘要、occurredAt、dedupKey。新消息按完整消息或轮次产生，不逐 token 推送；完成/失败来自原生终态，不能从 Journal completed 推断。
2. 稳定 reader 主体和按设备/会话的读游标；多手机同步是建议，尚非已确认产品要求。不要把临时 Cookie 作为长期主体。是否写回原生 hasUnreadTurn 尚待契约决定。
3. 通知偏好持久化；静音不删除动态或已读信息。
4. 独立于网页在线的后台事件采集；浏览器订阅会回收，不能充当系统推送常驻源。
5. 推送注册/订阅、安装设备与 reader 绑定、投递去重重试、失效 Token 清理、退出或移除后的撤销；系统通知点击恢复对应设备/项目/会话并重新鉴权。
6. 全量项目聚合+项目会话分页、原生模型/思考强度列表、只读待机状态投影、新建/编辑附图能力。原型的附件入口不能证明原生创建支持图片。

建议 API 资源为 notifications、notification-preferences、read cursors、push-installations；现有设备 streams 可扩展 sequence/未读与聚合更新，不另建第二套会话状态机。接口方法与名字由正式实现任务按现有路由确定。

## 最小产品问题

首发是原生 iOS/Android App，还是 PWA？此选择未最终确认。系统推送适配和授权方式依赖目标平台；可以先完成平台无关事件/偏好/读游标，不能将 HTML 原型视为已支持锁屏通知。

## 原型状态与文件

- mobile.js：项目、会话与工作区卡片。
- features.js：统一输入、操作/请求、工作区切换、连接申请确认/拒绝与移除。
- notifications.js：前台未读、动态和通知偏好界面。
- 全部数据为内存演示，没有真实网络调用、设备凭证、持久已读或推送。
- 连接申请样例有效期五分钟。确认生成只读、等待本机连接的记录；实际状态必须由后台报告。
- 当前只设计云端手机控制台；本机已连接多个云端的授权列表仍由正式本机页面负责，不在手机显示本机向其他云端的秘密或控制权。

已验证：项目聚合/筛选/返回、独立未读与待处理、统一输入、连接申请通知、确认后默认只读登记、设备移除说明、新连接指引。仍需实机键盘、系统推送与真实链路验收。

## 正式实现任务回传的 API 契约（已落盘，非本原型验收结论）

- GET /api/projects：全量聚合后分页，id/name/cwd/total/waiting/running/unread/unknown。
- GET /api/projects/{id}/threads?filter=all|waiting|running。
- GET /api/activity：按会话去重的待处理集合。
- GET /api/notifications?after=sequence。
- GET/POST /api/notifications/preferences：message/done/failed/approval。
- POST /api/notifications/read：threadId、sequence。读游标按本机 local 或云端 binding 隔离持久化；只读绑定可修改自己的偏好与已读，不写回原生 hasUnreadTurn。
- POST /api/threads/{id}/compose：服务端按原生状态选择 message/steer/queue-add，沿用 requestId、指纹与撤销校验。前端不能独立决定路由。

运行中或等待请求的图片明确拒绝，保留草稿；新建附图及动态模型目录暂无已验证原生契约。原型同步禁用不受支持的附件入口，有遗留附件时阻止发送并保留内容；模型浮层显示当前值，不提供硬编码可用模型选择。

未知/未加载计 unknown，不当作空闲。事件初次读取旧历史仅建立基线，不回放为新通知；后台采集独立于页面。正式功能验证仍由实现任务负责；系统推送等待用户选择原生或 PWA。

## 正式契约落盘状态

以 [docs/WORKSPACE.md](../../docs/WORKSPACE.md) 和 [docs/MULTI_CLOUD.md](../../docs/MULTI_CLOUD.md) 为接入权威，验证记录见 [docs/VALIDATION.md](../../docs/VALIDATION.md) 最新节。

实现任务报告并记录：141 Python、15 Node 检查及独立审查通过，未部署；本设计任务只核对文档，未独立复跑正式验收。

补充准确字段：GET /api/projects 使用 limit/offset/search，返回 projects/total/nextOffset；notifications 返回 events/nextSequence；偏好 POST 提交全部四个布尔值；GET /api/standby 仅读取。workspaceRevision 驱动刷新，readSequence 在历史渲染后确认。reader 是 local 或 binding:<id>，同一绑定共用读游标和偏好，不存在独立手机账号。

通知四表、后台采集、compose 与独立内存草稿已由正式实现任务完成，不再作为待实现提案。移动原型仍未接入这些接口。系统推送、真实模型目录、新建/编辑/运行附图、实机键盘与长期容量验收仍不宣称完成。
