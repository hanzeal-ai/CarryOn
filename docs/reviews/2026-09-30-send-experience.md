# 未加载会话发送体验与发现超时

本任务目标为修复 iOS 草稿/临时气泡闪现、未加载会话发送超时，并调查桌面未打开会话的运行状态同步。用户明确不新增兼容性代码，并要求保持桌面当前页面不变。

风险 R2：原生 IPC 发现时限与异步投递回执生命周期。直接在当前 main 修改，未创建 worktree 或提交。开始时 Owner continuity 的 manager、测试及文档已有未提交变更，已保留。仅本次涉及文件的当时基线位于 `.runtime/source-backups/2026-09-30-send-experience/`。

## 原始证据与范围

安装的桌面版本 26.928.21956：原生 router 先通过固定 10 秒发现 handler，再启动 request.timeoutMs。CarryOn 原先本地仅等 timeoutMs + 3 秒；OwnerManager 使用 3 秒查询，侧栏使用 1.5 秒查询，会在原生发现结束前误报超时。

对用户指定的“撰写三款产品小红书文案”只读查询：修改前 6.01 秒 `Codex 响应超时`；修正本地等待预算后 10.00 秒收到明确 `no-client-found`。没有发送用户任务、强制接管、将超时当无 Owner 或重发未知请求。

三次发现及恢复可能超过云端 25 秒单次请求限制，故桌面 Owner 的 compose 在校验输入、权限及请求身份后，先持久化 preparing 回执，再后台完成原有发送/steer/queue 分流。同一 Journal 记录转换为实际操作回执，保留编号、composeFingerprint、来源绑定和创建时间。未扩大云端接口超时或修改独立工作区行为。

后台准备仍复核 bridge generation、会话权限及动态远程授权；并发同编号返回原记录，冲突内容拒绝，同会话提交竞争拒绝。IPC 已写入后的失败/未知语义由原 dispatch 保持；shutdown 先关闭 IPC/Owner，随后等待后台 worker 收尾。启动 worker 失败或准备中服务停用写入失败回执，避免挂起 preparing。

## iOS

发送期间草稿保留在输入框，输入与发送禁用；接受成功后才清空本次草稿并显示气泡，失败无需恢复逻辑、直接保留草稿供重试。结果未确认保留请求身份。问题回复沿用其独立的发送状态展示。若同编号实时原生接受凭证已到达而 HTTP 回执丢失，则依该凭证确认发送成功，避免清除请求身份后仍保留草稿造成重复发送。

接受回执不会提前删除气泡，匹配原生历史才移除；迟到的 preparing/failed/uncertain 不能覆盖已观察到的接受凭证。一次渲染捕获同一时刻的历史和临时气泡，避免异步时间线渲染混入不同版本。

本次 UI 修订基线位于 `.runtime/source-backups/2026-09-30-draft-submit/`。已删除移走/恢复草稿方案的回调和 revision 状态。冷加载仍串行执行初始快照发现、恢复前发现、恢复后发现，并在恢复中读取全量 turns；三次发现可累计约 30 秒，外加启动与历史读取。具体最新请求没有逐阶段计时，不能把约 30 秒视为本次实测总耗时。

## 尚未解决的桌面侧栏

当前原生 `handleThreadStreamStateChanged` 对不在 followedConversationIds 内的会话直接返回；可用 IPC 表没有无导航公告会话状态/主动订阅外部 Owner 的入口。用户拒绝自动打开会话，因此本次不自动导航、不修改安装的原生 App、不伪造协议消息。此验收项未实现，不能声称全需求完成。

## 验证

- IPC 12 项通过，含延迟发现后明确 no-client-found、单次请求且不误标未知的回归。
- Owner 50 项通过，含慢恢复立即返回 preparing、处理中重复请求去重、冲突拒绝和后台 steer。
- 真实隔离 app-server 的 Owner 和 creation 两个回归均通过：加载、真实执行、原生消息去重、自动释放/冷恢复、桌面追加、归档等。未操作用户会话。
- `swift test --package-path iOS --no-parallel`：本轮 117 项通过，日志 `.runtime/draft-submit-swift.log`。
- iOS alignment 隔离模拟器构建及回归通过，含 accepted 无历史保留、历史接替、发送期间保留草稿、成功清空、失败保留及二次发送、live accepted 后 HTTP 503 仍确认成功、用户清空和图片编辑保留。检查最终截图，输入控件可见；未安装用户手机。
- 全量 Python：598 项，597 通过、1 跳过（158.268 秒）。存在既有 zip 重复条目及 SQLite ResourceWarning，无失败。compileall、git diff --check 通过。
- 独立审查 review_send_experience 基于基线/原始代码，指出草稿恢复覆盖后续编辑和两处异步测试编号问题；修复后独立重跑 50 项 Owner 和两个真实集成回归通过，异步投递门禁接受。审查不包含对未实现桌面同步的接受。本轮 review_send_experience 独立复核草稿留存、成功清空及实时接受/HTTP 丢失时序，依据原生接受不可撤销的发送契约接受修订。模拟器本轮日志 `.runtime/draft-submit-ios-final.log`，全部断言通过。

## 恢复与生效

沿用本任务服务重启授权，重启前 PID 86561 无 app-server 子进程（仅 caffeinate）；已重启为 PID 40761，端口 8769，桌面 IPC 与云端均已连接。未发送真实用户任务，未部署云端，未安装真实 iOS 设备。恢复应比较本次文件基线，仅撤销本次变更；不得回退 Owner continuity 或其他任务内容。服务有执行中的 Owner 时先等待空闲，保留 Journal 和原生数据；已未知请求不能换编号重发。iOS 改动需安装新包后在真实手机验收。
