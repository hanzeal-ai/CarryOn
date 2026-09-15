# 会话交互修复：实现与验证记录

## 当前范围

- iOS 子会话列表和消息内子 agent 链接使用 CarryOnLogo；名称与图标间距 4pt。
- 主会话及复用它的子会话滚动到顶部自动显示已有的更早记录，再扩大原生历史窗口，保留滚动位置和请求中的状态。失败仍提供重试。
- 消息和产物图片由 RootView 持有预览，图片弹层不再依赖消息单元格生命周期；切换账号/工作区清除预览。
- iOS 新建会话选择项目，后端从该项目的可交互、空闲、没有未确认请求的会话中选取控制目标，不改变全局 controller。原文通过一次 create_thread 工具调用传给新任务。
- 子 agent 详情复用 ConversationView、渲染和发送逻辑；后台子会话的原生只读限制继续由 Subagents.access 决定。

## 权威与影响

风险 R2：新增项目创建 API 参数以及原生投递准备。项目 id 映射读取 Codex 已保存的 local-projects；会话归属复用 Catalog 和 workspace.project_identity；空闲状态取原生快照并在发送前重验，远程权限继续由已有 authorize 回调校验。请求沿用绑定命名空间和持久化幂等账本。候选扫描有 15 秒预算，无法找到时明确返回 409。

iOS 原流程先 POST /api/controller，此接口被远程 API 明确禁止；新流程直接 POST /api/threads，携带 projectId。旧 CLI/Web 消费者未提供 projectId 时保留已有控制会话契约。

新任务结果核对原生工具 prompt、title、projectId、本机来源和实际目录归属。工作树异步创建使用 Codex 的 client-thread-bindings-v1 映射解析，不相信模型输出的占位 id。未接入归档/删除能力。

## 已验证

- 全量 Python 374 项通过，1 项既有跳过：/tmp/carryon-conversation-fixes-python-final.log。
- 项目创建 8 项聚焦测试覆盖跳过忙碌会话、内容传递、重复请求、无候选、待确认请求、权限撤回、发送前状态变化、云端请求隔离、原生结果归属和异步绑定。
- Swift Testing 49 项及 XCTest 4 项通过：/tmp/carryon-conversation-fixes-swift-final.log。
- 原工作区 iOS Simulator 完整构建通过：/tmp/carryon-conversation-fixes-build-final.log。
- 最终 diff --check 通过。无新增依赖、数据库迁移或用户数据修改。

## 未验证与门禁

- tests/fixtures/ios_conversation_interactions.swift 提供实际 ConversationView 的自动加载、图片弹层在消息替换后保持和关闭回归入口。隔离包构建通过，但新模拟器停在 CoreLocation 数据迁移；已有专用测试设备启动返回 NSPOSIXErrorDomain code 3（未返回进程）。本次未取得回归 result.json；已有旧时间线测试的 result.json 不计入本次证据。
- 真实图片点击、真机滚动与真实控制会话创建/首条任务投递尚未验收，没有发送真实业务测试消息。
- 本次未执行独立审查，不标记 R2 完整交付或发布门禁已通过。
- 未提交、推送、部署或安装到真实 iPhone。本地运行服务仍是上一发布版本。

恢复：撤回本次源码差异及新增 creation.py 即可，无持久化迁移。保留请求账本和原生会话；不能通过回滚撤销用户之后实际创建的新任务。
