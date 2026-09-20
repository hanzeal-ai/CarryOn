# 会话接续交互：变更前影响分析

用户确认：保留底部再次点击“会话”切换项目/全部会话的快捷操作；其他体验按已讨论方案优化。现有功能不得因交互调整退化。

## 保留契约与改动边界

| 修改点 | 影响路径 | 必须保留 | 验证 |
| --- | --- | --- | --- |
| 状态/连接提示 | Core 状态投影、主会话顶部、AppModel 接收状态 | 运行状态仍来自原生；缓存不授权写入；已有后台时限和复用连接不改 | Swift 状态测试、缓存/后台模拟器回归 |
| 历史阅读/分页 | ConversationView、updateSelection | 输入、附件、父子返回、临时聊天、历史窗口、原有导航栏；更早记录加载期间不能扩大写权限 | 导航模拟器回归、快照/队列隔离测试 |
| 列表筛选 | RecordListView 与 workspace GET 筛选 | 快捷切换、项目分组、搜索、分页和已有默认顺序 | workspace 分页/身份隔离测试；模拟器列表检查 |
| 动态直达 | ActivityRow、loadActivity/openActivity | 审批/问答面板及请求指纹；已读不等于已处理；切换工作区后迟到结果无效 | ActivityDetail/Core 权限测试；审批夹具 |
| 消息回执 | OutgoingMessageStatusView、现有 pending/journal | 同一请求编号、失败保留输入、不自动重发；不改变发送/停止/排队协议 | 发送投影与 pending 测试、操作夹具 |
| 改动查看 | 只读 timeline fileChange/turnDiff 投影 | 现有 ExecutionDetailView、附件安全路径、滚动和展开状态 | Core 文件聚合测试、模拟器查看 |
| 通知/远程状态 | 已有通知打开路径、WorkspaceDetails | server/device/thread 隔离，不因打开通知执行操作；未确认状态不显示就绪 | PushTarget/ActivityDetail 测试、缓存夹具 |

## 风险与执行约束

R2：共享会话状态与原有交互入口。先查调用者和既有测试，再小批量实施、独立审查及回归。RootView 快捷切换不修改；只读展示不能增加 canWrite/canPerform 权限。新交互优先复用现有代码，已有发送/排队/停止/审批/图片/子会话/后台保活作为回归基线。

本轮开始前，前两轮源代码已经完成 Python 454 项（1 项跳过）、Swift 97 项、Node 32 项及缓存/后台模拟器 24 项检查。当前工作区已有这些未提交变更，不能按 HEAD 回退；恢复只撤回本轮差异。新一轮测试结果必须另行记录，不能复用此前结果冒充。

## 原生旧会话加载检查

只读检查本机 `/Applications/ChatGPT.app/Contents/Resources/app.asar` 的 IPC 注册表与 handler：可用历史请求为 `thread-follower-load-complete-history`，owner discovery 由已有 owner 条件决定。本次检查没有确认可由 CarryOn 安全调用的独立会话加载接口。不猜测接口、不通过发模型消息或写 Codex 数据库强制打开。保留已实现的本地历史读取并明确继续对话所需条件；不声称完整接续已经实现。

## 发布与恢复

授权范围为本地实现、隔离验证和修复，不包含真实业务消息/审批、提交、推送、发布或真机安装。独立审查必须基于原始实现和实际测试输出，可以要求修改或拒绝。

## 当前实现与验证

- 已实现连接/任务状态分离、最近同步时间、会话筛选和列表窗口保留、动态结果直达、只读改动查看、发送结果核对、通知锚点和远程访问检查。
- RootView 无差异；发送/审批/停止/队列授权仍复用原有契约。更早历史加载保留原有连接门禁。
- Python 全量 457 项通过（1 项跳过），日志 /tmp/carryon-continuity-python.log；新增通知锚点后 push 全套 16 项通过。
- Swift 最终 101 项通过，日志 /tmp/carryon-continuity-swift-final.log；Node 32 项通过；compileall、JS/shell 语法检查及 git diff --check 通过。
- 隔离模拟器完整构建成功；缓存/后台 24 项通过。导航追加消息和同 ID 流式更新前后，可见 message25 的 Y 坐标均为 317.6667，阅读位置保持。
- 隔离操作回归通过：队列失败不当作成功、队列成功、回答失败保留/成功确认、子会话操作保留父 ID、过期子会话拒绝、本地历史/只读拒绝；实际轮询 5 次。夹具补全现有权限契约，生产权限判断未放宽。
- 模拟器证据位于 .runtime/cache-regression、.runtime/navigation-regression、.runtime/alignment-regression；复现入口 tests/run_ios_cache_regression.py 和 tests/run_ios_navigation_regression.py（可选 alignment）。
- 未进行真机安装、真实 APNs 投递或生产业务写入。原生未加载会话自动激活仍受已确认 IPC 能力限制；本地历史读取不等于原生可写。

独立审查发现并修复通知并发竞态：每个打开流程使用独立 token，手动打开/关闭会话或新通知会使旧请求失效；在异步返回后检查有效性。最终缓存/后台模拟器回归扩展至 26 项，全部通过（/tmp/carryon-continuity-cache-final.log），包含迟到通知不覆盖手动导航、两条并发通知以新通知为准。最终模拟器构建通过。
