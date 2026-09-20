# 账号与工作区改造检查点

## 当前任务契约

按最终用户流程覆盖 CLI、macOS、云端和原生 iOS：产品地址集中配置；首次唯一 IPC 默认工作区读取真实 CODEX_HOME；新增名称工作区使用独立 app-server；用户账号与 Codex 模型账号分离；扫码绑定与定向申请均由手机确认；账号登录二维码独立认证；断网保留授权，明确失效才恢复；本地删除保留文件；手机注册、密码登录、扫码登录、修改密码与 Apple 密码集成配置。

风险 R2，授权仅本地实现和验证。未授权提交、推送、PR、部署、真实用户授权变更、真实数据删除或生产扫码确认。

## 原始目录边界

原始 `/Users/sanmws/Documents/CarryOn` 有未提交恢复、目录展示、删除工作区以及 iOS 额度/文案改动。已只读查看差异，选择整合必要恢复前置（onboarding、cloud_manager、binding_recovery、paths、services、对应桌面与测试）。未整合额度圆环、项目状态文案或不相关产物；未改写原始目录。

## 实施状态

产品地址唯一来源是 `carryon/product.json`。旧已确认账号立即授权、旧 link/pairing 引擎及其 CLI、桌面、Web、iOS 入口已删除。被替换引擎的测试由账户确认绑定、恢复测试与原有 HTTP/WS 多云权限测试覆盖；正常注销、推送撤销和实时流清理保留。

新增 app-server 使用私有 stdio、独立 HOME 和目录；真实双进程隔离探测通过。临时文件认证下实际模型 turn 已完成，会话持久化路径在隔离目录，源认证 mtime 未变。模型执行在临时测试目录完成，没有操作用户工作区或生产绑定。app-server 不支持的公共队列编辑明确返回不支持。

## 已有证据

- `/tmp/carryon-isolated-turn.log`：真实隔离模型执行及持久化。
- `/tmp/carryon-desktop-smoke.log`：原生 Swift 模型通过真实 CLI 创建两个 app-server 工作区，验证独立启动、模型账号分离、定向删除及文件保留。
- `/tmp/carryon-auth-final.log`：54 项认证相关测试通过。
- 最终 Python 回归：410 项，1 项跳过，结果 OK；`/tmp/carryon-python-final3.log`。
- JavaScript 回归：38 项通过；`/tmp/carryon-node.log`。
- Swift 回归：73 项通过；`/tmp/carryon-swift-test.log`。
- macOS 桌面可执行文件编译成功：`/tmp/CarryOnProduct`；日志 `/tmp/carryon-desktop-final.log`（既有 onChange 弃用警告）。
- 最终 iOS Simulator 与 iPhoneOS SDK 未签名构建均成功；日志 `/tmp/carryon-ios-final.log`、`/tmp/carryon-ios-device-build.log`。两个 app 产物均包含统一来源的 `product.json`。
- 最终 `git diff --check` 通过；正式域名在活动实现中只出现于 `carryon/product.json`。

## 审查和后续门禁

用户指定 GPT-5.5 独立审查，最终结论为接受。审查要求修复的正常 logout 清理和 app-server 创建回执提前完成问题均已修正；详见 `docs/reviews/2026-09-15-onboarding.md`。

用户最终要求只进行常规测试与构建，不再试机；收到要求后没有启动、安装或操作设备进行验证。上述真实隔离模型与桌面 smoke 是此前证据。正式域名服务、设备签名、Apple 关联文件线上响应、iPhone 密码保存/自动填充、真机扫码和生产绑定未验证；不将编译成功表述为这些流程验收通过。未制作发布安装包，未提交或部署。

已知限制：app-server 公共协议没有原生队列编辑接口；请求会明确失败。既有 `doctor` 仍诊断 IPC socket，不能用于判断 app-server 工作区健康；应使用工作区服务状态。

## 恢复

停止本次本地测试进程即可回到基线。现有用户目录未迁移或删除。未来部署前需由负责人备份云端 users/sessions/binding-invites 和设备注册表；含多用户授权的数据不得交由旧单管理员程序公开服务。任何生产发布或真实扫码确认另行由用户执行。

## 后续修复：App 流式显示

用户报告原有 IPC 会话在 App 中隔几秒显示一段。静态检查发现 `ConversationView.refreshMessages` 会在整理消息期间收到新 revision 时丢弃已完成结果；持续增量可能使显示一直追赶而不发布。本次 R1 修复取消这一丢弃条件，将原有串行刷新调度提取为 `ConversationRefreshQueue`：当前刷新完成后处理最新待刷新请求，中间请求合并，不添加逐字动画。

会话、工作区、登录 epoch 和页面生命周期仍控制异步结果是否可显示；列表事务实际写入时再检查一次，离开后返回页面会请求刷新。只在本工作区修改，未安装或发布。

验证：`swift test --package-path iOS`，75 项通过，含持续增量中间显示、待处理合并、显示事务串行和空闲后继续更新的两项新增测试；日志 `/tmp/carryon-stream-refresh-tests.log`。生命周期隔离由代码检查及构建验证，未进行设备运行验证。已安装 App 的实际延迟可能还包含传输或渲染耗时，不能据此宣称端到端延迟已经测量或全部消除。

最终 iOS Simulator 构建通过（`xcodebuild -project iOS/CarryOn.xcodeproj -scheme CarryOn -configuration Debug -sdk iphonesimulator -derivedDataPath /tmp/carryon-product-ios CODE_SIGNING_ALLOWED=NO build`）；日志 `/tmp/carryon-stream-refresh-build.log`。最终差异格式检查通过。

用户指定的 GPT-5.5 独立复审结论为接受，无阻断问题。审查者读取实际差异及 ExyteChat 事务实现，确认当前刷新不被新请求取消、最新待处理请求合并、两次异步隔离检查有效；独立复现两项聚焦测试及 iOS Simulator 构建通过。未将静态检查表述为真机视觉验证。
