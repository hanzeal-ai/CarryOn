# 官方能力证据与边界

核对日期：2026-10-03。依据已安装官方 App 的可读 bundle、随 App 安装的 app-server 0.159.2 导出 schema、CarryOn 原始实现和隔离运行结果。未操作用户真实任务或凭证。不存在“一切功能已一比一”的结论。

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
| 技能选择 | `skills/list(cwds,forceReload)`；`UserInput {type:skill,name,path}`；direct/Owner skill-only 发送与持久历史验证 | 已加载 native及新建首轮；最终写前核对同 cwd 已发现且 enabled 技能；最多 20 项；无伪 mention；插件安装由独立配置管理入口负责 |
| 设置与模式 | 原生 settings schema、`thread/settings/update`、`latestCollaborationMode` 权威投影 | `activePermissionProfile` 在 native 仅可读，supportedSettings 不提供写入 |

原生 review/start 与目标管理已接入，并通过私有 CODEX_HOME + localhost 模型的 direct/Owner 实际进程验证。证据仅覆盖隔离测试，不冒称用户账号端到端验收。

## 已接入能力的契约与验证范围

### 仓库审查

`v2/ReviewStartParams.json` 支持 `review/start {threadId,target,delivery}`，target 是 uncommittedChanges、baseBranch(branch)、commit(sha,title?) 或 custom(instructions)。本次实现只开放 inline，响应包含源 reviewThreadId 与 turn。detached 已由原生文档标注废弃，不能作为新分叉捷径。

CarryOn 使用原授权/journal、Owner native_session、空闲及空队列检查。原生 active turn items 的 enteredReviewMode 投影 activeTurnKind=review、canSteer=false；首条 item 到达前仍由原生 activeTurnNotSteerable 错误保护，禁止失败后改为普通 prompt 重发。

### 临时侧聊创建

官方 `main-C5425b_s.js` 的 `mx()` 建立 sideConversationBoundaryItems；`app-shared-36eae88777f2.js` 的分叉流程先 thread/fork，再 thread/inject_items 注入“父历史仅为参考、不得延续父任务”的边界，ephemeral 保留在所属 runtime。`ThreadForkParams` 与 `ThreadInjectItemsParams` 均有导出 schema。

现已对自持 native/Owner 接入创建与关闭。使用专属长驻 runtime，fork(ephemeral=true,excludeTurns=true) 后 inject_items；逐写验证父子身份/权限/代次，未知不重放，失败关闭未发布进程。9项真实原生测试覆盖父上下文、禁止自动发送、独立发送、父Owner释放、重连、撤权及未知回执。ephemeral原生拒绝goal、queue/list和turns/list，因此不提供持久恢复/队列/目标；历史仅当前runtime事件。公共desktop socket无相同创建入口。

### 插件、应用与结构化 mentions

`plugin/installed(cwds)` 返回 marketplace 与 installed/enabled/availability/authPolicy/installPolicy；官方 installed-inventory 查询确实使用该 RPC。`plugin/list` 可以远程拉取目录，不能当纯本地列表；`app/list(threadId,cursor,limit)` 为 experimental，返回 isAccessible/isEnabled。

`TurnStartParams.UserInput` 支持 mention(name,path)。现已接入原生库存发现、plugin://plugin.id.trim()与app://app.id、提交前刷新并重验可访问性、请求指纹与发送/补充/队列/编辑保留。真实本地fixture插件direct/Owner持久化和卸载后拒绝通过；真实已授权应用账号尚未验证。安装/卸载及技能配置写已通过独立持久配置管理入口接入，不属于只读发现；插件共享尚未实现。桌面 extraRoots 与动态物化插件状态不能从另一 runtime 推定一致。

### 项目文件引用

官方 `app-shared-44edd7bfa69c.js` 的 `oin/qrn` 将正常文件路径投影为 `# Files mentioned by the user` 与 `## My request` 的普通文本 envelope，`Yin→kle` 使用 text input 且 `text_elements: []`。文件不是 plugin/app mention，也不上传或预读文件正文。

现有会话通过公共 `fuzzyFileSearch(query, roots)` 在当前权威 cwd 搜索，目录命中、缺失文件及越界 symlink 不进入候选。iOS/Web 使用独立文件草稿与原始查询身份；最多20项，支持普通发送、立即补充、原生排队，首轮创建及 ephemeral 侧聊暂不支持。系统 `/var` 与 `/private/var` 别名只在文件根身份边界规范化；运行连接仍按原始 cwd/process/session 校验。最终授权、Owner事务、文件范围与存在性检查全部发生在原生写入前。排队确认后由原生普通文本上下文执行；不从任意正文反解析权限规则。路径引用不保证之后模型读取时的文件内容不可变。

私有 CODEX_HOME/native进程10项验证覆盖direct/Owner搜索和发送、暂停Owner只读查询、原始请求去重、写前删除和撤权、active queue及原生自动消费。Owner延迟轮次释放、明确拒绝及本地权限拒绝跟踪有专门回归。Web四组宽度/色彩实际页面验证覆盖真实按钮44px、键盘连续选中取消/焦点、无compositionend关闭重开、草稿切换、仅文件发送和撤权。iOS模拟器选择器5项行为通过；草稿持久恢复及确认清除在Core验证。真实用户账号写入尚未执行。

### 实时语音

已接入自持 native/Owner 的 `thread/realtime/start,appendAudio,stop` 与实时通知，音频为 PCM16LE / 单声道 / 24kHz。RPC 空响应只确认接收，必须由 started/closed 通知确认生命周期；错误或未知状态不能自动重发。会话、权限、Owner写前身份及连接代次逐次验证，未关闭语音阻止Owner释放。音频仅存有界内存队列，不写入历史或每帧广播完整快照。

Web使用AudioWorklet采集与有界播放，iOS使用AVAudioEngine/AVAudioConverter；显式启动、权限、静音、停止、切换工作区和后台清理已接入。私有CODEX_HOME/假API key/localhost WebSocket 的真实app-server及生产API集成2项通过，包含输入、输出、转录、HTTP拒绝后的停止；13项后端生命周期/权限/有界队列检查通过。Chromium验证采集前等待active、PCM转换、停止及取消未知启动。未验证真实账号资格、云端语音服务、真机麦克风/扬声器及WebRTC，不能将隔离验证称为真实账号闭环。

### 目标管理

`thread/goal/get,set,clear` 有正式 schema，goal 含 objective、status、tokenBudget、tokensUsed、timeUsedSeconds 与更新时间；status 为 active/paused/blocked/usageLimited/budgetLimited/complete。官方 bundle 使用 goal/get 恢复状态、goal/set 更新目标/状态，并消费 goal/updated、goal/cleared。

现已接入。2026-10-01 私有 CODEX_HOME + localhost 模型探测已确认：set active 立即产生 turn 并连续自动续跑；pause 后在途轮正常结束、后续请求停止；resume active 恢复续跑；clear 返回 cleared=true，在途轮结束后 get=null 且不再继续。原生自行累计 tokensUsed。记录见本次验证日志 `/tmp/carryon-native-goal-probe.log`；没有访问用户账号。探测模型不会调用完成工具，因此持续续跑不代表原生目标完成判断异常。

实现将创建/恢复 active 视为执行授权，复用 send 权限、journal 与未知结果核对；暂停/清除独立使用 stop 权限。Owner 在 active/unknown goal 的轮次间 idle 窗口不会释放 runtime。已暂停并释放物理进程的 Owner 通过短期原生控制连接进行 goal/get、pause、clear，不调用 thread/resume；真实集成确认额外模型请求为零。暂停/清除不等于立即 interrupt 当前轮。原生事件、GET 与回执采用带修订号的不可变快照，避免缓存失效遗漏和迟到 GET 覆盖更新的目标/未知状态；没有 UI 自建目标状态机。两端已实现目标管理与未知状态核对，原生 direct/Owner 集成及独立审查通过。

## 工作树、分支与环境的证据限制

app-server ClientRequest 没有 worktree 或 branch CRUD。官方内部 `worktree-create-managed` 接受 cwd、startingState、localEnvironmentConfigPath、streamId，交由 WorktreeService/Git worker；pending-worktree-* 和 local-environment-config[-save] 同属内部 Electron 路径，公共 socket 方法表不含这些入口。

schema 中 `environment/add` 的参数是 environmentId、execServerUrl、authBearerToken?、connectTimeoutMs?，用于注册远端 executor；environment/info,status 读取该执行环境。它不等于官方本地 environment.toml 的 setup/cleanup/action，也不创建 Git worktree。ThreadStart.environments 选择既有执行环境，同样不能替代 setup。

所以 **现有公共 IPC/app-server 证据不足以实现官方受管工作树完整生命周期**；不是 Git 本身做不到。若扩展 CarryOn 自管工作树，需要明确增加创建、分支、环境脚本、失败恢复、删除保护、目录归属和跨进程互斥的产品范围，不能把执行 git worktree add 标为已复刻官方行为。当前不伪造支持，不写桌面私有状态，不调用未公开内部 Electron handler。


### 新建前引用发现

`/api/creation/references` 使用权威项目cwd查询skills/list及plugin/installed；app/list的threadId可为null，只作为候选。Owner使用同home短生命周期runtime；独立创建在tasks下临时空child查询，完成后清理，避免把tasks本身的repo市场误当作子目录库存。原生repo市场并不自动继承；测试需要跨目录可用时，仅在私有home调用marketplace/add注册，产品不自动注册任何市场。读取后复验runtime process/session/connected、桥接代次、授权与项目身份。

创建后在实际thread/cwd再验技能和应用/插件身份；请求指纹包含引用。原生拒绝时保留已知thread ID和不确定回执，同ID不自动重建。私有原生测试覆盖direct/Owner仅引用创建、单轮持久历史、重复ID与卸载后拒绝。真实账号应用权限尚未验收。

语音证据：私有无API-key的OAuth runtime可能异步拒绝；客户端保留错误并等待原生停止确认，不把RPC接收解释为可用语音。功能入口只对native声明能力开放，真实账号资格由原生启动结果决定。


### 输入框斜杠命令

两端提供 /side、/plan、/review、/compact、/fork、/goal、/model、/status 的能力过滤发现菜单，路由到既有原生服务及配置界面。裸 /plan 按当前collaborationMode.mode在plan/default间切换且不自动发送，保留原生model/effort/developer_instructions；/plan 带正文开启plan，仅在 settings confirmed 后提交普通正文，正文中的斜杠不再解析；edit/create-only 可执行对应命令，普通正文仍需 send。未声明能力、附件冲突、不合法参数和未知命令保留草稿；未知原生回执不自动重放。/compact 使用现有 thread/compact/start；/review 自定义参数进入原生审查配置；/fork 仅确认新 thread 后清理父草稿并导航。没有建立另一套原生操作语义。


技能图标展示投影仅支持原生iconSmall指定的技能目录内PNG，不改变输入契约。文件打开逐组件禁止符号链接，读后复验原生/项目身份；每图64KiB、512×512、一次展示读取累计512KiB。发送库存不读取图标。缺失、非PNG、过预算及解码失败显示通用图标；没有外部URL请求或SVG解释器。iOS先校验格式/尺寸并生成48px缩略图，Web采用data:image/png且失败回退。图标保存在草稿展示元数据，原生value仍仅name/path。


### 新建首轮配置

`creation_settings.supported`直接投影原生settings schema，排除threadId、cwd、projectId、activePermissionProfile及已停用multiAgentMode。模型/强度只需create；任何额外配置键（包括null）同时要求create+edit。Console入口及成功回执重验完整权限集合；回执撤权返回409 uncertain，不声称云端成员权限在每个native RPC前刷新。

两端新建设置入口提供工作模式与执行审批，模型选择保留其他配置并同步模式内模型/强度。失效选择保留并提示重选；iOS配置随账号隔离的工作区草稿持久化。native创建后先配置再首轮，完整配置进入请求指纹；配置失败保留已知thread和原请求ID，不重新创建。私有CODEX_HOME+localhost模型的direct/Owner原生持久turn_context确认首轮plan、never和high（合并在4项引用集成中），未访问真实账号。

### 明确操作能力投影

controls始终返回supportedOperations：desktop follower来自当前核实的METHODS，native来自app-server声明，空集合保持为空。两端不再把缺少列表解释为全部支持。Web队列独立于设置呈现，并逐项核对add/edit/reorder/resume/delete/clear能力；旧面板点击再次检查当前列表。该列表是权威实现的展示投影，不创建另一套操作契约。


## 归档与恢复

公开 `thread/archive` 只接收 threadId，返回空对象；`thread/unarchive` 返回原 thread 和 notLoaded；原生 SQLite 的 archived 字段是列表与未知结果核对的权威状态。CarryOn 使用只读库存与搜索分页，写入只通过 native RPC。普通 desktop follower 没有公开归档写入口，只能浏览库存；不调用私有 Electron handler。

自持 app-server 与 Owner 已接入归档/恢复。归档在原线程事务内复验空闲、空队列、无审批、非 active/unknown 目标、无语音及持久线程；暂停释放后的 Owner 使用短控制 runtime 查询队列/目标，不 resume 原任务。原生 writer 锁拒绝其他进程持有的会话；完成时只清理原 Owner session，不能关闭并发替换的新 Owner。恢复创建短控制 runtime，不加载会话、不继续目标、不运行模型。未知只通过原请求 ID 查询 canonical archived 状态，不能重新发 RPC；查询与写入统一采用 thread→bridge 锁顺序。

8 项真实 CLI 0.159.2 集成使用私有 CODEX_HOME、假 API key 和 localhost 模型，覆盖暂停目标、未知归档/恢复、非空队列拒绝、loaded/suspended Owner、连接代次变更、新 Owner 身份及锁顺序竞态。恢复后 paused 目标原文/状态保留、notLoaded 不变、没有新增模型请求。外部 writer 另有实际拒绝探测。原生归档后不删除草稿、历史或工作树。

库存与请求查询要求 view，归档/恢复要求 edit；绑定请求 ID 独立映射且只能查本绑定凭证。两端完整页面检查包含未知保留、关闭重开只查询、确认后保留草稿、恢复不自动打开及旧 scope 拒绝。iOS 持久 pending 只读查找加载前禁用提交，防止重开再次 POST；Web 从 transport 对应存储恢复同一 ID。Core 及客户端拒绝身份或 archived 状态不符的终态回执。独立后端及前端审查拒绝项均修复后复审；真实账号、全部官方归档页面状态尚未验收。

原始日志 `carryon-native-archives-integration-final.log`、`carryon-archives-ios-native-final.log`、`carryon-archives-web-final.log` 和相关截图统一归档。初始失败证据仍保留，不能将阶段失败说成全程通过。


## 会话重命名

官方bundle调用`persistThreadTitle → thread/name/set {threadId,name}`；原生通知是`thread/name/updated`。现已接入direct及CarryOn Owner，使用edit权限、binding命名空间和独立journal；普通Desktop follower没有公开写入口。仅管理原生分页持久主会话，单行非空名称最多200 Unicode标量。已释放Owner使用短控制runtime，不resume；按canonical名称替换同身份快照并发布。

发送及读取后均复验原process/session、bridge generation、Owner service/session；canonical id/name在任何快照副作用之前校验。未知请求只按原ID或持久catalog读取核对，不重发，另一次名称/归档操作被待核对记录阻止。两端提交、查询、恢复均核对原名称内容身份（iOS既有payload hash、Web既有请求存储中的SHA256），错误失败和错误成功凭证不释放ID；iOS本地pending精确GET，不依赖截断jobs列表，读不到时保持禁写。两端保留草稿及线程身份。

8项真实native集成通过，覆盖direct、已加载/已释放Owner、未知、代次、同runtime换session、错canonical身份及未知后的标题广播；模型请求未增加。iOS8项实际视图和Web1280/390明暗主题通过，后端及界面独立拒绝项修复后复审接受。未对用户真实会话执行重命名。


### 剩余管理能力的真实契约探针

2026-10-02私有home/localhost模型验证：threadSection/list默认返回官方固定Pinned section ID01984de2-8f74-7c91-a3b2-5c5e937cf318；thread/section/move置顶/移出，以及thread/list(sectionId,sortKey:section_position)可读取原生顺序。操作后thread/loaded/list仍为空，没有额外模型调用。不得把置顶/分组记为公共协议不支持；两端产品入口、请求生命周期及原生顺序管理已经接入。

skills/config/write(path,enabled)返回effectiveEnabled，forceReload的skills/list确实显示禁用/启用新状态，零额外模型调用。当前技能发送/库存功能已接入，技能配置管理已按现有edit“编辑会话与设置”权限接入，未知回执只读核对；不借用send权限。后台terminal可列出/终止/清理但没有公开输出流，必须来自实际拥有任务的runtime，Owner后台进程保活已通过隔离真实原生验证。


2026-10-03续作：持久原生分组/置顶读取、会话移动及自定义分组创建/修改/删除已接入iOS和Web。隔离原生验证确认update省略appearance保留其原值、delete将会话移出分组而不删除会话。所有管理写使用edit并通过云端原请求隔离；不确定create不按名称猜测或重发。独立审查和两端实渲染局部通过。thread/section/move的beforeThreadId原生排序控制、两端失败读取重试和原请求位置校验已通过独立审查。


### 后台终端

仅实际持有会话的 app-server 进程可读取 `thread/backgroundTerminals/list` 和执行 terminate/clean；悬挂 Owner 不恢复任务或创建替代进程来猜测库存。库存来自原生 processId，停止前核对归属、进程/session、bridge generation 和权限。未知回执只在同一原生身份下查询确认，不重发。公共协议没有终端输出流，两端仅展示命令和目录。

Owner 自动结束/显式释放前读取库存为空，网络等待在全局锁外，随后重验 idle/原生身份；归档同样拒绝活跃终端。停止、归档、排序共享 journal 互锁。读取需 view，停止需 stop。iOS/Web 入口实时核对能力与会话可交互状态，未知原请求和确定失败不会被库存刷新抹掉。

隔离真实 native13项、Owner/创建/归档相关聚焦检查、iOS11项及Web四组实际渲染通过，后端和界面独立审查接受。Core146项+7XCTest、client44项、全JS91项通过。整体复刻及性能仍有剩余验收。


### 技能持久配置

两端管理技能入口读取原生目录，展示启用状态和工作区持久影响。公开 `skills/config/write(path,enabled)` 仅接受此项目原生目录中精确路径，写前重验cwd、会话和权限，返回effectiveEnabled后forceReload读取确认状态。Owner使用短期控制进程读取和配置，不恢复任务。未知配置冻结工作区下一次配置，只按原请求精确内容与原生状态核对；同会话归档与配置双向互锁，防止未知结果被归档阻断。没有自行改写SKILL.md或借用send权限。

六项隔离真实原生验证、iOS11项实际回归、Web四组明暗窄宽渲染通过；Web额外验证写失败→读失败→partial目录错误→读成功不会丢失写错误。后端和界面独立审查接受。


### 插件持久管理

两端独立管理入口接入公开 `plugin/list`、`plugin/search`、`plugin/read`、`plugin/install`、`plugin/uninstall`。目录是当前项目 cwd 下原生返回的可发现市场，不宣称完整远程商店；详情展示原生来源、技能、应用、MCP 与运行钩子。只接受原生默认目录或原查询页中的精确 pluginId，写前复验详情ID/名称/市场/source，以原生市场名称/路径定位安装来源；安装策略与 availability 由原生决定。配置写要求 edit，读取要求 view，Owner 使用短控制 runtime，不恢复会话或发模型请求。

请求 journal 保存原始 ID、正文、cwd、selector 与 source。未知只按同一原请求核对 canonical 安装状态，不重放。技能配置与插件管理在工作区互锁，同会话归档也双向互锁。确认已安装不代表应用已经授权；丢失安装回复或授权列表格式无效时，两端显示授权状态待核对，未实现伪 OAuth。

插件十一项与技能六项隔离真实原生集成通过，覆盖未知单次写、Owner 不恢复、外部身份拒绝、配置/归档双向互锁及代次/撤权。Web 四组实际渲染和 iOS 最新十六项回归通过；详情来源与授权提示经独立复审修正。全 Python 849 项（99 条件跳过）、JavaScript 96 项、Swift Testing 149 项加 XCTest 7 项通过；跳过原生用例在对应专项启用。native search三种scope均已实际调用，非空personal本地来源及安装已验证；两端远程多页来自隔离服务，实际非空远程目录/多页cursor、账号 OAuth、插件共享及完整商店覆盖尚未验收。

`marketplace/add/remove/upgrade` 有公开契约，但当前官方 bundle 已确认的调用涉及 bundled 市场注册/清理，不足以证明 Remote 有用户市场管理主路径；产品不后台注册市场。upgrade 可部分成功，目录刷新不能替代其原请求结果。`plugin/reconcile` 仅确认本次观察到的状态变化，不证明 runtime ready；共享涉及外部可见范围，未执行真实账号发布。


原生插件搜索保留{searchTerm,scope,cursor}原页身份，详情及安装回执随原正文核对，未知恢复读取原selector和source；不把搜索命中强制归入默认plugin/list。原生personal搜索可在limit30请求下返回全部36项和null cursor，已按真实返回验证。浏览不发模型请求。Web组合输入确认Enter不触发搜索；分页与写后刷新沿已提交查询，不把未提交输入改成请求身份。
