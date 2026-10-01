# 官方能力证据与边界

核对日期：2026-10-01。依据已安装官方 App 的可读 bundle、随 App 安装的 app-server 0.159.2 导出 schema、CarryOn 原始实现和隔离运行结果。未操作用户真实任务或凭证。不存在“一切功能已一比一”的结论。

可复查证据：本次导出位于 `/tmp/carryon-capability-schema/`，原始 bundle 摘取位于 `/tmp/carryon-review-native/`。它们是调查产物，不是生产运行依赖。安装包升级后应重新导出、验证；不能只据方法名相似认定契约相同。

## 传输边界

- 公共 desktop coordination socket 提供带版本的 thread owner/follower 协调：start、steer、interrupt、settings、edit、queue、审批等。`version-check.js` 中固定版本表可追溯到官方 bundle。
- `main-C5425b_s.js` 的 Electron renderer/main handlers、Git worker、WorktreeService 是官方 App 内部接口。发现代码不等于它们可经公共 coordination socket 调用。
- app-server JSON-RPC 是独立原生协议。CarryOn 自持 Owner 可调用其控制中的 runtime；不能把另起进程的状态冒称桌面 Owner 的瞬时状态。

## 当前已接入并有隔离运行证据

| 能力 | 权威契约及验证 | 边界 |
| --- | --- | --- |
| 原生队列 | `thread/queue/add,list,start,update,delete,reorder`；active-add/idle-add 自动执行，interrupt 留队列，start 恢复 | 无 CarryOn 自有调度器；已接受原生任务不随远程控制断线取消 |
| 最后用户轮编辑 | `thread/revert(beforeTurnId)` 后 `turn/start`；重新分页读取 retained history | 两次写分别授权；部分成功有相位记录；未知不可自动重发 |
| 普通/指定完成轮分叉 | `thread/fork(lastTurnId,excludeTurns,deferGoalContinuation)`；独立 runtime 创建后释放，catalog 可见，Owner 可再次加载 | 不自动开始新目标；未知无 client fork id 可核对，不能根据列表猜 child 或自动再次 fork |
| 技能选择 | `skills/list(cwds,forceReload)`；`UserInput {type:skill,name,path}`；direct/Owner skill-only 发送与持久历史验证 | 仅已加载 native；最终写前核对同 cwd 已发现且 enabled 技能；最多 20 项；无伪 mention、无插件安装 |
| 设置与模式 | 原生 settings schema、`thread/settings/update`、`latestCollaborationMode` 权威投影 | `activePermissionProfile` 在 native 仅可读，supportedSettings 不提供写入 |

原生 review/start 与目标管理已接入，并通过私有 CODEX_HOME + localhost 模型的 direct/Owner 实际进程验证。证据仅覆盖隔离测试，不冒称用户账号端到端验收。

## 可实现、尚未全部闭环的协议能力

### 仓库审查

`v2/ReviewStartParams.json` 支持 `review/start {threadId,target,delivery}`，target 是 uncommittedChanges、baseBranch(branch)、commit(sha,title?) 或 custom(instructions)。本次实现只开放 inline，响应包含源 reviewThreadId 与 turn。detached 已由原生文档标注废弃，不能作为新分叉捷径。

CarryOn 使用原授权/journal、Owner native_session、空闲及空队列检查。原生 active turn items 的 enteredReviewMode 投影 activeTurnKind=review、canSteer=false；首条 item 到达前仍由原生 activeTurnNotSteerable 错误保护，禁止失败后改为普通 prompt 重发。

### 临时侧聊创建

官方 `main-C5425b_s.js` 的 `mx()` 建立 sideConversationBoundaryItems；`app-shared-36eae88777f2.js` 的分叉流程先 thread/fork，再 thread/inject_items 注入“父历史仅为参考、不得延续父任务”的边界，ephemeral 保留在所属 runtime。`ThreadForkParams` 与 `ThreadInjectItemsParams` 均有导出 schema。

因此该能力对自持 native runtime **可实现，当前尚未实现创建闭环**，不是协议不支持。最小范围：专属长驻 runtime、父子身份关联、两阶段 journal、每次写重新授权、失败清理/未知结果核对、原生侧聊输入与生命周期。普通 fork 完成后关闭 runtime 的流程不能直接套用。公共 desktop socket 未查得相同创建入口。

### 插件、应用与结构化 mentions

`plugin/installed(cwds)` 返回 marketplace 与 installed/enabled/availability/authPolicy/installPolicy；官方 installed-inventory 查询确实使用该 RPC。`plugin/list` 可以远程拉取目录，不能当纯本地列表；`app/list(threadId,cursor,limit)` 为 experimental，返回 isAccessible/isEnabled。

`TurnStartParams.UserInput` 支持 mention(name,path)，但这不证明任意 app:// 或 plugin:// 字符串等价于已授权工具。最小范围：原生库存发现、按身份生成 canonical URI、提交前重验可访问性、请求指纹与全部输入路径保留，再用隔离契约验证。安装/卸载、共享、配置写是额外持久操作，不属于只读发现。桌面 extraRoots 与动态物化插件状态不能从另一 runtime 推定一致。

### 实时语音

有 `thread/realtime/start,appendAudio,appendText,appendSpeech,stop,listVoices` 与实时通知；start 支持 outputModality、transport、voice、version 等。协议面可实现，当前未实现音频会话闭环。最小范围包含麦克风权限、原生音频/WebRTC 传输、播放/转录、断线与停止、会话授权、账号功能门禁。现有 localhost 文本模型不能验证真实语音服务，不应展示无执行能力的按钮。

### 目标管理

`thread/goal/get,set,clear` 有正式 schema，goal 含 objective、status、tokenBudget、tokensUsed、timeUsedSeconds 与更新时间；status 为 active/paused/blocked/usageLimited/budgetLimited/complete。官方 bundle 使用 goal/get 恢复状态、goal/set 更新目标/状态，并消费 goal/updated、goal/cleared。

现已接入。2026-10-01 私有 CODEX_HOME + localhost 模型探测已确认：set active 立即产生 turn 并连续自动续跑；pause 后在途轮正常结束、后续请求停止；resume active 恢复续跑；clear 返回 cleared=true，在途轮结束后 get=null 且不再继续。原生自行累计 tokensUsed。记录见本次验证日志 `/tmp/carryon-native-goal-probe.log`；没有访问用户账号。探测模型不会调用完成工具，因此持续续跑不代表原生目标完成判断异常。

实现将创建/恢复 active 视为执行授权，复用 send 权限、journal 与未知结果核对；暂停/清除独立使用 stop 权限。Owner 在 active/unknown goal 的轮次间 idle 窗口不会释放 runtime。已暂停并释放物理进程的 Owner 通过短期原生控制连接进行 goal/get、pause、clear，不调用 thread/resume；真实集成确认额外模型请求为零。暂停/清除不等于立即 interrupt 当前轮。原生事件、GET 与回执采用带修订号的不可变快照，避免缓存失效遗漏和迟到 GET 覆盖更新的目标/未知状态；没有 UI 自建目标状态机。两端已实现目标管理与未知状态核对，原生 direct/Owner 集成及独立审查通过。

## 工作树、分支与环境的证据限制

app-server ClientRequest 没有 worktree 或 branch CRUD。官方内部 `worktree-create-managed` 接受 cwd、startingState、localEnvironmentConfigPath、streamId，交由 WorktreeService/Git worker；pending-worktree-* 和 local-environment-config[-save] 同属内部 Electron 路径，公共 socket 方法表不含这些入口。

schema 中 `environment/add` 的参数是 environmentId、execServerUrl、authBearerToken?、connectTimeoutMs?，用于注册远端 executor；environment/info,status 读取该执行环境。它不等于官方本地 environment.toml 的 setup/cleanup/action，也不创建 Git worktree。ThreadStart.environments 选择既有执行环境，同样不能替代 setup。

所以 **现有公共 IPC/app-server 证据不足以实现官方受管工作树完整生命周期**；不是 Git 本身做不到。若扩展 CarryOn 自管工作树，需要明确增加创建、分支、环境脚本、失败恢复、删除保护、目录归属和跨进程互斥的产品范围，不能把执行 git worktree add 标为已复刻官方行为。当前不伪造支持，不写桌面私有状态，不调用未公开内部 Electron handler。
