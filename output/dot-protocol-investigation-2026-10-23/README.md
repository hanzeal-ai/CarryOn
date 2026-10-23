# 原生 Dot 接入调查（2026-10-23）

结论：CarryOn 当前的桌面 Unix IPC 和 App Server RPC 没有已确认的原生 Dot 消息投递入口。原生安装包另有云端 Messaging 接口，可作为后续接入验证方向；未证明外部客户端可以成功调用。

## 已观察证据

- 当前安装包：/Applications/ChatGPT.app，版本 26.1016.62342。
- 桌面 IPC 版本表共 26 个方法/事件，涵盖普通会话 owner、follower、stream；没有 Dot/Orbit/Messaging 专用入口。完整表见 evidence.json。
- 同安装包 Codex 可执行文件通过 app-server generate-json-schema --experimental 导出 452 个 schema 文件，ClientRequest 共 172 个方法。未出现 Orbit/Aeon/Messaging room 定义。生成产物在 /tmp/carryon-dot-inspect/appserver-schema。
- account/workspaceMessages/read 的消息类型仅为 headline、announcement、unknown，属于公告读取，不是本需求的通信接口。
- Dot 前端按 profile 的 messaging_room_id 定位消息房间；缺少房间时调用 POST /tbo/{tbo_id}/messaging-room。
- 发送使用 POST /messaging/rooms/{room_id}/messages；请求包含 content、request_id、idempotency_token、reply_to、message_metadata，条件性附带 task_id 和 app_attest_challenge。
- 历史读取使用 GET /messaging/rooms/{room_id}/messages，支持分页及 task_id/reply_root_message_id。
- 实时链路包含 POST /messaging/rooms/{room_id}/live、/celsius/ws/user，以及 subscription_id/revision 校验与重连。
- 主进程通过独立 httpFetch 服务处理云端请求，并校验预期账号与认证账号匹配。此服务与 clientCoordination 分别装配，不能把 Electron 内部服务等同于外部 Unix IPC。

## 可行性与边界

普通会话承接：可利用既有会话创建、投递、结果读取能力；跨 CarryOn 账号的身份映射、权限、收件箱与回执仍需开发。

原生 Dot 承接：找到真实产品代码中的发送与回读路径，有进一步验证价值，但不能只给现有 turn/start 增加一个 Dot ID 就认为完成。还需确认合法认证入口、账号资格、房间获取、完整性校验和完整发送/回复闭环。

CarryOn 账号与原生登录账号不是同一套身份。不能仅凭 @CarryOn账号 就把发送方原生凭据用于访问接收方 Dot。可研究由接收端在其自身授权身份下接入自身 Dot，再由 CarryOn 回传结果；此设计尚未实测。

## 未验证项

未向任何账号或 Dot 发送消息，未创建房间、启动任务、读取私聊、提取认证令牌或修改应用。静态证据不证明当前账号可用性，也不能排除未公开/未导出接口。未做端到端实测。

本次未修改业务代码。evidence.json 保存原生文件摘要、字符偏移与相关代码片段，可复核。
