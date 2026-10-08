# 官方交互对齐实现与验收记录

日期：2026-10-03。工作目录 `/Users/sanmws/Documents/CarryOn`，来源及交付目标均为 `main`，续作起点 `41cd18b`。用户已集成此前分支，本次直接修改 main 工作区；尚未提交、推送或部署。

目标：iOS 优先对齐官方 Remote，Web 同步对齐官方桌面工作台；保留 CarryOn 品牌、多云端、绑定权限、草稿保护、幂等提交和未知结果核对。功能以当前公共 IPC、app-server 和 Owner 契约为上限，不伪造私有接口，不添加历史兼容层或自有执行调度器。

风险 R2：涉及公共接口、权限、会话状态与跨端交互。实现及环境调用已授权；未向用户真实账号发送任务。独立审查者基于源文件、原生 schema、实际页面及原始运行证据形成结论，并提出过需要修改的缺陷。

**状态：当前已实现的范围完成下述局部验证与复审；全产品逐状态一比一和真实账号/真机验收尚未成立。**

## 当前实现

| 范围 | 最终行为与权威边界 |
| --- | --- |
| 执行、队列、编辑 | 原生停止、补充、队列增删改序和恢复；编辑经 revert、重读历史、start 分阶段执行。原生负责调度，两次写入不冒称原子操作。 |
| 创建与首轮配置 | 图片、模型/强度、技能和应用引用；创建前发现、创建后按实际 cwd 重验。create→settings→turn，高级配置要求 create+edit。必须确认非空 createdThreadId 才清理及导航，未知保留原请求 ID。 |
| 设置与能力 | supportedSettings 直接来自契约，权限配置不猜测。supportedOperations 始终明确；两端缺少列表不扩展为全部支持。Web 队列与设置解耦，各动作独立投影能力，点击时重验当前能力。 |
| 临时聊天 | 专属长驻 native runtime，ephemeral fork 后注入官方上下文边界；创建与发送分开。父子身份、权限、连接代次逐写检查。临时会话不提供原生拒绝的持久历史、队列、目标与引用库存。 |
| 分叉、审查、目标 | 普通/已结束轮次分叉；inline review 的四种原生范围；目标创建、预算、暂停、恢复、核对和移除。Owner 生命周期与目标、语音状态保持一致，不用 UI 自建运行状态机。 |
| 归档与恢复 | 原生持久归档库存、搜索分页、空闲归档及不自动加载的恢复；Owner 线程事务与同 session 清理，未知原 ID 查询。view 浏览、edit 写；普通 Desktop follower 仅浏览。保留历史、草稿和工作树。 |
| 正文引用 | iOS NSTextAttachment 与 Web contenteditable；可信身份及 UTF-16 偏移随工作区草稿保留。普通粘贴不建立可信引用，线上仅原生 name/path。旧 SkillReference 已删除。 |
| 技能及应用 | skills/list、plugin/installed、app/list 原生库存；写前重验 enabled/accessible、runtime 与 cwd。原生显示名和有界目录内 PNG 图标仅作展示；图标路径逐组件禁止符号链接，发送校验不读取图标。 |
| 语音 | PCM16LE 单声道 24kHz，等待 started/closed 确认；Web AudioWorklet 与 iOS AVAudioEngine。音频仅有界内存，切作用域/后台清理，未知启动不自动重发。 |
| 斜杠命令 | /side、/plan、/review、/compact、/fork、/goal、/model、/status 按原生能力路由。裸 /plan 在计划与默认模式间切换，带正文始终开启计划；保留原生协作配置，切换不自动发送。计划正文不递归解释命令；未知命令保留草稿。 |
| 正文与改动 | iOS MarkdownUI 原生文字选区；Web DOM-only 常用 Markdown、复制原文、有界 diff 和行评论。两端 diff 支持自动换行；iOS 单列行号随系统字号缩放，按实际文字测量横向宽度、保留惰性行及最多 500pt 视口，切换 patch 与历史快照时刷新。复用既有 Highlightr 给已知文件 diff 着色，仅投影颜色；原文核对、100k 字节上限与超限纯文本。共享浅色高亮采用内置github-gist，修复旧github主题被依赖无序选择器处理覆盖颜色；普通代码块和源码预览同样受益。Web 流式更新保留未改正文的正向/反向选区；替换正文及容器端点不猜旧位置。Web 复用同一已安装 Highlight.js 11.11.1 引擎，裁剪31种语言；Worker有界着色，保留原文/选区，100k字节超限或2秒超时降级。Markdown样式抽成两端共享CSS，手机代码块与复制按钮不再缺样式。Web 尚非完整 CommonMark或数学排版。 |
| 原位本地评论 | 按原生改动身份、精确 patch、路径和原始 R/L 行保存在当前任务草稿；添加后继续读 diff，可编辑、删除及查看所有待发送评论。发送时在正文后投影为普通原生文本，不增加 RPC，正文引用偏移不变；仅评论也可发送/排队。确认只清除原样送出的评论，等待期间修改/新增保留；未知请求保留评论及请求 ID，不自动重发。iOS 草稿与原请求发送快照随现有草稿存储；核对确认仅清原样内容，保存成功后才释放请求ID，缺快照或保存失败保留ID供显式幂等重试；发送前仅排队保存，不冒称已落盘。Web 随现有内存草稿切换，尚不保证页面重载保留。 |
| 保留 CarryOn 功能 | 多云端/工作区、绑定与权限、活动、请求记录、草稿/图片保护、幂等与未知结果核对，继续使用现有权威服务。 |

完整原生契约、隔离环境与能力限制见 [CAPABILITIES.md](CAPABILITIES.md)。

## UI 与交互

- 桌面依据已安装官方 App 26.928.31416/build12553 的可读组件与 CSS：275px 可调侧栏、48rem 内容区、46px 工具栏、14px 字体及对应暗色。新建是右侧工作区非模态页面，居中标题、底部项目及输入框；手机新建保持全屏。
- 新建与普通会话附件均进入加号菜单，设置、模型和圆形发送/停止留在同一底栏。桌面 Tab 顺序与视觉一致；跨断点复用原按钮，不复制事件与业务状态。
- iOS 创建模型按当前工作区目录及查询代次校验，失效选择保留并提示重选；默认模型不受目录读取失败影响。首轮设置按账号/工作区保存。
- iOS 临时聊天使用自身原生模型设置及元数据，长名称截断；新建/结束及刷新移到顶部，移除额外底部工具栏。实际检查标准字号、375pt 小屏和系统 accessibility-extra-large 字号。
- 删除 style.css 中不可达的四段 max-width:760px 样式：HTML 对该文件限定 min-width:761px，手机由 mobile.css 承担。测试 SQLite 连接改显式关闭，生产数据库行为不变。

官方公开图片与 CarryOn 实际渲染分别存放。fixture 使用生产 DOM/SwiftUI，截图是真实渲染，内容与传输为测试数据。官方 App 的计算机控制曾被工具拒绝，未绕过；不存在完整官方逐状态现场对照结论。视觉资料与截图说明见 [VISUAL_REVIEW.md](VISUAL_REVIEW.md)。

## 验证与独立复审

环境：官方 CLI/app-server 0.159.2；隔离 CODEX_HOME 与 localhost 模型/语音服务；Chromium；iOS 26.5 模拟器。条件跳过的原生集成另外启用专项执行，不冒称真实账号验证。

| 验证 | 结果及证据 |
| --- | --- |
| Python 全量 | 最新 849 项，99 项条件跳过；`plugins-discovery/python.log`。对应原生专项另行启用，不把跳过计为通过。 |
| JavaScript 全量 | 最新 96 项通过；`plugins-discovery/javascript.log`。 |
| Swift Core | 最新 149 项 Swift Testing + 7 项 XCTest 通过；`plugins-discovery/swift-core.log`。后续 App UI 已编译并实际运行。 |
| 真实 native 集成 | side 9 项、mentions/创建首轮 4 项、voice 2 项，以及队列/编辑/分叉/审查/目标专项通过；具体隔离边界见能力记录。 |
| iOS 页面 | 创建配置/引用/未知身份 17 项、首页 10 项、alignment 37 项通过；实际正文选区、命令权限、临时草稿与无自动发送再次通过。 |
| Web 页面 | operations、parity、commands、21 项移动几何及交互通过；队列部分能力、撤权旧按钮、审批/回答、断点恢复、迟到回执均有实际页面断言。 |
| diff 与计划开关增量 | 两端裸 /plan 开/关、配置保留及不发送通过。iOS 换行/恢复、横向可读、长→短 patch 宽度回落、独立历史更新及评论隔离通过；最终单列/高亮版本千行挂载 22→13 行，71帧最大间隔约65.0ms；此前82.1ms仍是有效观测，不称无卡顿。375pt与真实系统accessibility-extra-large版本挂载10→3行、75帧最大42.5ms；高亮前后差异不能以此替代同机比较。`carryon-diff-highlight-final.log`、`carryon-diff-se-accessibility-evidence.log`，修复前复现见 `carryon-diff-snapshot-repro.log`。 |
| 高亮冷启动 | 6个独立进程（3次large、3次accessibility-extra-large）全通过，浅色固定3色；千行已实际启用高亮，标准挂载22→13、大字号10→3。采样最大帧间隔标准52.2–64.8ms、大字号33.8–38.3ms，保留此前82.1ms等观测，不称零卡顿。原文含中文/emoji、字体归属、明暗主题及超限降级通过；`diff-cold-start-results.json`、`carryon-diff-cold-start.log`。 |
| 本地评论增量 | 两端实际发送/排队、未知保留不重发和等待期间修改/新增通过；iOS未知→核对确认后原样再次发送无新写入，核对前编辑/新增保留，`carryon-comment-receipts-ios-final.log`。Web 1280/390 页面实际添加、编辑、删除、切任务恢复、旧作用域拒绝通过。原位及总览 A 编辑期间 B 新增/删除保留 A 未保存输入；iOS 实际发送保留评论合法 U+FFFC。核心 9 项 Swift 与 4 项 JS 覆盖原始行校验、不同改动身份、持久化失败恢复、引用正文前缀及确认清理。`carryon-review-comments-web-{parity,delivery}-final.log`、`carryon-review-comments-ios-final.log`。辅助功能accessibility-extra-large实际回归通过，标题/行定位纵向避免压窄；`carryon-review-comments-ios-accessibility-final.log`。 |
| Web 长历史 | 千条记录渲染最近 120 条；两宽度更新约 13–15ms、既有 DOM 复用、阅读位置偏移 0。正/反向选区保持，容器边界及替换正文不继承旧选区。 |
| iOS 长历史 | 千条历史按稳定消息 ID 比较发送前基线、目标与呈现高度。最终 9 个既有消息、962 个样本无高度不稳定；121 个发送窗口帧。最大帧间隔约 95.1ms。前一次约 82.5ms 且有状态/位置动画，不称始终零动画或无卡顿。 |
| Web 高亮增量 | 1280/390真实组件与完整工作台通过；原文/中文emoji/明暗主题/选区/超限/卡死Worker均通过，卡死期间主线程2秒内100次计时回调。真实Console+CSP经仅允许/carryon的HTTP反向代理成功加载Worker及引擎。许可证原文一致，未新增依赖；独立复审接受。 |
| 归档增量 | 8项真实 native 集成通过；绑定/权限/只读库存5项通过；iOS实际归档8项行为通过。Web1280/390明暗主题完整页面包含关闭重开只查询、草稿保留、恢复不打开与旧scope拒绝；原生及界面独立复审通过。 |
| 构建及差异 | Web 构建通过；iOS 隔离生产视图编译通过；git diff --check 通过。 |

临时聊天、mentions、输入编辑器、模型目录代次、创建身份、能力投影、底栏及选区的独立拒绝项均已修复后复审。队列复审另修复设置与队列耦合、逐动作能力及旧按钮提交；长历史测试复审补稳定身份与基线高度，未用删除失败测试掩盖压缩问题。评论独立审查曾拒绝 Web 全量重建卡片导致未保存编辑丢失，修复为按 ID 复用后独立 Chromium 复验通过；另修复 iOS 全局删除标记损坏评论原文，实际发送再次验证。续查发现核对确认清除请求ID而未清草稿的重复投递路径，现已按原请求快照清理，保留后续编辑，并在落盘后释放ID；补齐flush后身份复验。Web 比较不再序列化大 patch，保持精确字符串身份。

日志归档：`.runtime/parity-main-validation-2026-10-02/`。iOS 实际截图与结果：`.runtime/{conversationvisual,creationrefs,home,alignment,timeline,parity,archives}-regression/`；Web 截图：`.runtime/web-style/` 及对应回归截图。长历史原始逐帧证据为 `.runtime/timeline-regression/samples.json`。

## 尚未成立的验收与恢复

- 完整会话与全部弹层的官方逐状态视觉一致尚未验证；原位评论卡已实现并作局部实图检查，两端旧/新版本与多hunk隔离、无末尾换行标记已验证；缺少完整文件前文时无法恢复跨hunk真实词法状态，全部语言尚未覆盖。
- 真实账号应用授权、语音资格/云端服务，以及真机麦克风、扬声器、键盘和性能尚未验证。
- 公共 IPC/app-server 不提供官方受管工作树与本地环境服务的完整生命周期。不能将普通 git 操作或装饰按钮标为复刻了该功能。
- 归档/恢复已接入并通过隔离 native 与两端实际页面检查；全部真实归档记录及官方逐状态视觉一致仍未验收。
- 本地 fixture 与隔离 native 验证不能替代真实账号端到端验收。

本次不迁移原生数据或删除历史。恢复时基于 main 起点及本次差异逐项撤回代码，保留用户已有改动、原生数据与请求 journal；不得直接强制重置工作区。用户尚未授权远程推送或部署，本次没有执行。

Web高亮复审曾拒绝根路径Worker和本地许可证MIME遗漏，修复后真实前缀代理回归通过。完整工作台实图另发现手机未加载Markdown样式，现抽出共享文件并补布局断言，独立复审通过。生成脚本`scripts/sync_web_highlighter.mjs`可从已安装Highlightr重建裁剪引擎、BSD许可证及纯颜色主题；运行产物不依赖iOS checkout。

归档独立审查曾拒绝查询锁顺序、旧回执清理新 Owner 及 iOS 重开未知操作再次 POST；三项均已修复并补真实进程竞态或实际 UI 回归。归档列表使用专用行，避免把未加载的 archived 记录展示为无来源的“状态未知”。

本轮全量初跑有一次既有云端 socket 关闭超时（`carryon-archives-python.log`），专项15项复查及全量772项再跑通过，保留初次失败日志，不推断已证明所有调度时序无超时。归档提交额外检查会话同步，失同步不创建 pending ID；明确失败后重新读取 pending，未知仍保留。

最终归档回执续审发现成功态之外的错误身份失败回执可能释放当前 pending；两端现先对所有状态校验 id/thread 再 reconcile。iOS 实际生产 write 错失败回执保留原 ID，再 GET 完成恢复；Web 四种宽度/主题完整页面同样通过。JS新增两 action、三失败状态及两种身份错位组合，最终76项通过；两位独立审查者复审接受。


## 时间线与 diff 词法续作

时间线窗口保持120条；排序时间使用完整历史位置，避免每次尾部追加让119条保留消息仅因日期变化重新配置。流式更新仍只改变对应消息。不可编辑消息先检查自身类型，再读取共享历史及操作权限，减少无关正文观察；两条既有回复在同一带仪器场景各由13次重绘降至6次。实际阅读旧消息时追加回复与展开历史的锚点偏移分别约0.0000013pt、0.0000076pt，旧消息995个高度样本稳定。Debug最大帧间隔91.6ms，不称无卡顿。

主线程采样另发现fixture每帧递归定位表格有明显开销；改为弱引用并校验window，仍逐帧读取当前可见消息身份、真实/呈现高度与阅读位置。该缓存只覆盖单会话；同一window内旧表仍挂载而替代表出现的导航场景不在此fixture范围。修正后的Debug重跑993个旧消息样本稳定、锚点通过，但最大间隔115.5ms；两次运行不能用于证明峰值下降。采样报告与两轮原始数据均保存，测量修正不冒称产品优化。

两端diff按hunk分别还原旧/新版本，删除行使用旧侧词法，新增和上下文使用新侧；补丁头与标记保留原文且不着色。`No newline`标记不截断同一hunk状态。Web解析器抽为`unified-diff.js`供审阅与Worker共享，保留100k字节、2秒、128组与总32000 token run上限；iOS缓存当前主题，避免每侧重复读取主题文件。未新增依赖或兼容路径。跨行注释/旧新状态分离、后续hunk、Unicode与标记专项、完整工作台、前缀代理及iOS实际视图通过；无完整文件前文时不保证真实跨hunk状态。

增量验证：JS79、HTTP资源9、Console6、Swift140+7通过；Chromium1280/390高亮及完整parity通过；iOS `diffHunksIsolate`与`diffNoNewlinePreservesState`及既有换行、历史刷新、评论、回执场景通过。最新diff千行挂载22→13，69帧最大间隔62.1ms，仅为本次Debug模拟器观测。独立审查接受产品改动及单会话测量修正。证据`carryon-diff-hunks-*-final.log`、`carryon-timeline-observation-final.log`、`timeline-low-overhead-*`与`carryon-timeline-main-thread.sample`位于统一归档。Python772项为前一轮全量基线，本轮后端未变，只重跑受影响资源/Console检查。


Release实际编译/安装/运行通过，沿用完整时间线fixture；982个旧消息高度样本稳定，两阅读锚点保持，日期单独变化为0，投影最大耗时13.3ms。最大帧间隔105.85ms，发生在流式追加阶段；其后仍有多处大于60ms间隔，不能声称已解决流畅性。Release与Debug的重绘次数不作为同配置比较。runner通过`CARRYON_IOS_CONFIGURATION=Release`显式选择构建，白名单仅Debug/Release，产品路径与配置一致。原始构建、逐帧和结果存为`timeline-release-*`，没有替换此前Debug证据。


Release续采样保留在`carryon-timeline-release-main-thread.sample`。主线程主要处于等待，活跃采样同时含fixture采集与SwiftUI/UIKit布局；8秒统计不足以把单个105.85ms峰值归因于特定函数，不据此修改第三方依赖或声称根因已定位。


## 会话重命名续作

已接入官方原生名称RPC，两端会话菜单提供重命名，保留线程身份、草稿与工作树。native control的Owner事务保持与metadata eligibility抽成独立模块供归档/名称共用；名称不依赖归档实现。edit写、view核对、普通Desktop follower不提供伪入口。8项私有native集成、两端实际渲染和独立复审通过。

复审修复写后原process/session复验、suspended快照校验前置及未知后标题广播、iOS jobs列表缺记录仍可重新写入、两端查询名称内容错位。原请求与名称摘要随现有请求机制保留；无法读到原请求禁写、显式重读；未知不重放。JS全82通过、HTTP/Console/归档/名称权限24项通过，Swift141+7通过。失败fixture日志及修正后实际结果均保存，测试宿主的编译错误、连接状态遗漏和Web等待选择器错误不冒称产品缺陷。

iOS实图`.runtime/rename-regression/rename.png`，Web`.runtime/web-rename-{1280,390}-{light,dark}.png`。原生`carryon-native-rename-reviewed-final.log`，两端`carryon-rename-ios-content-final.log`/`carryon-rename-web-hash-final.log`，全JS`carryon-rename-all-js-final.log`。总体任务仍包含其他可接入能力、视觉与性能验收，不以重命名局部通过宣布完成。


## 内容搜索与创建界面续作

内容搜索使用公开 thread/search（recency_at 降序）与 thread/searchOccurrences，保持 opaque cursor；两端只读用户可用，不借用发送权限。命中位置通过 inclusive turnCursor 验证原生 turn/item 后计算历史尾窗，当前 HTTP 窗口上限4000轮。官方接口未加载会话的 canonical user/assistant 历史通过 thread/turns/list 读取，不从 response_item 原始用户上下文生成气泡，也不恢复任务或执行模型。Owner 短连接读取后关闭，暂停快照保持原对象。缓存有界4MiB/8条，文件版本、连接代次、transport与归属隔离，命中复验归档。实时持久历史刷新保持1秒。

11项私有真实 native 搜索/历史集成通过，Web四组实际搜索/分页/UTF16高亮/命中视口验证通过；iOS13项实际结果全通过，含首次命中可见、live先到不含命中、12次初始回调与迟到行高变化。UIKit实际列表viewport与布局信号替代失效的零尺寸Preference；有限修正保留scope/代次及拖动取消。独立复审及共享时间线回归通过，未宣称所有规模与滚动场景均无问题。基础全量 Python806（60跳过）、JS82、Swift141及既有XCTest通过；全量之后新增实时来源分类测试单独通过。

创建页项目与模型独立并行加载；真实模拟器键盘高度336pt，单行、多行及图片状态验证与独立视觉审查通过。Web创建截图等待真实目录和模型数据后拍摄，主工具栏的显示选项与会话信息收敛到更多菜单，键盘展开/关闭与焦点恢复已通过8组尺寸主题验证。

以上是局部续作证据，整体仍有能力、视觉与性能剩余验收。Release105.85ms帧峰值尚未闭环，失败的xctrace产物不能作为性能通过依据。


## 原生分组与置顶续作

公开 threadSection/list、thread/list(section_position) 和 thread/section/move 对接持久分组、置顶与移动，原生分组排序不与本地项目目录混合。threadSection/create/update/delete 已接入两端管理入口；更新省略 appearance 保持原值，删除分组保留会话。内置置顶不可修改删除。公开创建无 client identity，回执丢失不能按同名分组合并或再次创建；更新/删除以 canonical 原生库存核对。全部待确认分组生命周期与移动在 bridge 锁内双向互锁，不复制源 membership 状态。view 读取、edit 管理，普通 Desktop follower 不提供伪管理入口。

11项隔离原生验证通过，其中互锁场景注入 uncertain journal 检验双顺序，不冒充并发压力测试。Web客户端40项、Swift143项及既有XCTest通过；iOS16项实渲染涵盖未加载移动、错误回执、原请求恢复、权限撤销、跨scope退出、创建/修改/删除。Web两种宽度两种主题的管理与移动均通过，移动/桌面断点来回、共享滚动区域修复及21组移动几何回归通过；8组Web主题尺寸验证通过。独立后端与界面审查阻断已修复并局部接受。

证据集中在 `.runtime/parity-main-validation-2026-10-02/sections/`。当前分组阶段不代表全部功能与官方视觉完成；原生排序和后台终端现已局部闭环；技能配置和插件安装/卸载已完成下述局部验证；此前帧峰值仍待继续闭环。


## 原生后台终端与持久配置续作（2026-10-03）

后台终端只读取真实拥有任务的 runtime，停止/清理前校验原生 processId 归属；未知只在原进程/session 核对。Owner 空闲不等于没有后台命令，自动/显式释放和归档均须先确认库存为空。全局锁外读库存，再锁内重验身份和空闲，避免其他会话被等待阻塞。两端仅展示原生命令/目录，公开协议没有输出流，不提供伪实时终端。native13项、Owner相关68项、两端实际页面和独立复审通过。

技能持久开关接入 skills/config/write，精确原生路径、edit 权限、effectiveEnabled 与重读确认；未知冻结后续工作区配置，与同会话归档双向互锁。插件安装/卸载接入 plugin/list/read/install/uninstall，详情先展示来源与运行能力，确认已安装与应用是否授权分开表达。未知保留原 ID，不重新发送；失效身份、撤权、失去作用域和错误失败回执均不能释放新请求。插件与技能同属原生工作区配置，共享 journal 互锁而不创建另一套原生状态。

技能6项、插件7项真实隔离原生用例通过；Owner不恢复任务且额外模型调用为零。Web四组窄宽/明暗实际页面与iOS技能11项、插件12项通过。该阶段的插件目录查找只过滤当前项目目录；随后补齐下述原生 scope 搜索，仍不冒称完整商店验收。独立复审曾要求修正来源展示、格式不合法的授权列表和详情往返键盘焦点，修正证据单独保留。原生后台终端、技能和插件的来源/边界及证据分别见 CAPABILITIES 和统一归档。

## 最新性能测量边界

Release轻量帧采样仅记录帧时钟，移除每帧遍历可见单元格；原有稳定性测量仍独立保留。空闲宿主一轮432个间隔、P95约18.55ms、最大74.63ms、7个超过50ms，旧历史追加和展开的两个锚点通过。fixture的passed仅表示有效采样及锚点稳定，不是性能验收通过。带仪器的分段回调自身曾耗时58.4ms，不能把其峰值全部算成产品开销。

后续拥有明确fixture PID的主线程采样中，更新阶段活跃栈包含Exyte UIList.updateTableNoAnimation→reloadData及SwiftUI/UIKit布局；初始加载还包含其录音/位置组件初始化。它说明存在整表更新路径，未建立单个帧峰值与函数的一一对应。第三方 checkout 未被修改，尚未宣称消除长帧或达到真机性能验收。


## 时间线近底部与插件搜索续作（2026-10-03）

状态行投影仅保留实际显示字段，队列更新通过真实 queue.messages 和 thread.id 验证：操作栏显示“待发送1”，消息投影与表格事务均不增加。完全空的状态行不再进入列表；“回到最新”定位实际末条消息。表格更新读取当前 UIKit offset，不复用按钮20pt显示阈值；offset异步回调核对显示代次。Release边界回归覆盖真实键盘、40段流式回复、5/20pt正文锚点、投影期间程序移动、回最新并发更新及扩展历史；搜索定位回归再次通过。独立复审局部接受，证据为 timeline-status-projection/、timeline-reading-offset/ 和 plugins-discovery/search-layout.log。

以上布局回归包含截图和单元格遍历，帧峰值不能用作纯性能结论。隔离 all-natural 和仅成员变化增量候选曾产生正文行高重算、近底部跳动，未采用；生产仍使用 none/keepStable。最新生产轻采样Release有416帧、P95约31.46ms、最大99.82ms及9个超过50ms的间隔，记录为 timeline-reading-offset/current-frame-only.json；此前闲置主机基线仍有超过50ms的间隔，真实手势因Mac锁屏未验证，真机离线；不称整体性能完成。

插件增加公开 plugin/search 的 global/workspace/personal 与 opaque cursor。默认目录本地过滤保留；搜索命中的详情和写前重新查原页、核对原生详情 ID/名称/市场/source，客户端不传自选selector。原查询身份进入幂等正文，未知按 journal 原来源核对，不依赖搜索继续可用或默认目录包含该插件。插件11项与技能6项真实隔离原生通过；个人本地非空安装、来源错配、丢回执后搜索失效及36项原生完整返回已验证。当前原生个人目录不严格遵循请求limit30，按实际nextCursor处理，不伪造分页。非空远程市场和真实多页cursor仍未验收；两端远程多页来自隔离服务。Web四组、iOS十六项通过；独立复审曾拒绝IME确认误发与清空输入后分页失效，现已补测修正并局部接受。分页、安装及刷新沿已提交query，保留未提交输入。

当前官方 App26.928.31416 的 Desktop IPC 版本只读校验再次通过，见 native-contract-current.log；Web生产资产构建通过。

隔离纯成员增删候选补显式ID集合变化后，三组交替轻采样对照：现生产最大83.60/67.80/99.61ms、P95 22.08/25.18/25.67ms；候选最大83.20/85.80/83.58ms、P95 22.10/21.01/21.61ms。峰值未稳定改善，且依赖后台差分后开始拖动的竞态未受控；未采用。减少动态效果仅测试注入分支覆盖，非系统设置实测。原始记录为 timeline-reading-offset/membership-comparison.json 和 membership-boundaries.log；不把隔离候选写入产品或据此关闭整体性能验收。

### 2026-10-03 项目文件引用闭环

- 原生来源与普通文本投影见 CAPABILITIES 的“项目文件引用”。不新增依赖、IPC私有消息或文件上传类型；结构化 files 只用于授权、草稿、请求身份与写前验证。
- 真实native/Owner10项、Owner66项、Web四组页面回归、iOS选择器5项与Core文件草稿2项已通过。脚本：`tests/test_native_file_references_integration.py`、`tests/test_owner.py`、`tests/check_project_files.cjs`、`tests/run_ios_navigation_regression.py <simulator> projectfiles`。
- 证据：`.runtime/parity-main-validation-2026-10-03/project-files/`；iOS实际渲染 `.runtime/projectfiles-regression/projectfiles.png`；Web `.runtime/web-project-files-{1280,390}-{light,dark}.png`。
- 后台独立审查、Web 与 iOS 局部源码及实图审查均接受。该记录不表示整个官方复刻任务完成，也不覆盖真实账号、实机拖动或全部性能验收。
- 恢复方式：撤销本模块和调用接线即可恢复原发送能力。新增草稿文件字段可缺省，不迁移/删除原会话数据；已获原生确认的队列或轮次不随代码撤销。


### 2026-10-03 持续增长回复的文字位置与选择

真实可选择正文中的同一字形在旧实现追加段落后偏移约392pt。当前在原生表格事务实际写入前捕获段落序号、前文、UTF-16位置与屏幕坐标，完成后允许最多750ms、3次有实际偏移的布局修复。拖动、导航、返回最新、退出、作用域或投影代次变化取消修复。几何与选区恢复抽出 ConversationNavigation.swift，不修改第三方列表缓存。

七组实际 UITextView 回归通过：相同前缀、重复段落、当前段落增长、静置选区、改选区、清选区和不改变范围的主动失焦；此前阅读旧历史、展开、近底部和投影中移动位置仍通过。内部属性更新抑制选择通知；用户结束选择时由 UITextViewDelegate 撤销恢复意图，不恢复旧范围或重新抢焦点。独立审查接受此局部修复；现有测试未单独证明所有视图替换分支，也不是用户真实拖动的证据。

最新 Release 有编辑权限、真实可选择段落和键盘的轻帧时钟测量：374个间隔、P95约33.34ms、最大182.42ms、12个超过50ms；两个历史阅读锚点和队列更新隔离通过。该场景比此前只读基线更接近实际使用，但仍有长帧，不能据此关闭性能验收。行内容独立投影已作两轮隔离对照：第二轮生产峰129.19ms、候选130.38ms，两者均8个超过50ms间隔；没有稳定收益，未采用。


### 2026-10-03 成员追加与最终文字定位复核

新增“长回复增长后250ms追加消息”复现正在阅读的行离开可见区。失败日志保留在 timeline-reading 证据目录。最终捕获范围在成员集合变化时只取下一版本仍保留的消息；只扫描一次几何快照，全局优先当前选区、尚有效的连续锚点，再按屏幕位置排序。标记复用时解绑旧身份，并对标记ID与真实UITableView可见行再次验证，避免把旧ID投影到另一条消息。

实际视口转换出现约1e-13pt浮点差异，原CGRect精确比较误判为视口变化；四维采用小于0.5pt容差，实际尺寸变化仍取消。若同一有效锚点临时离开可见区，仅同步恢复一次捕获时附近offset，再按TextKit字形校正；同属750ms、最多三次非零修正预算。layoutIfNeeded后再次检查意图与作用域。曾尝试的异步scrollTo重新显露方案因无法证明取消时序而移除，无该路径残留。

最终严格回归通过：九组字形/选区场景（全部发生UITextView替换），包括有选区和无选区的增长后成员追加；近底部保留原cell-origin小于1pt断言并新增真实glyph小于1pt断言，两组均0pt、行高1168恒定；旧历史、展开、回最新、投影时改变位置及队列隔离通过。独立审查局部接受。任意规模的批量插入、真实手势和真机性能仍未验证，不把该有限恢复声明为全部状态通过。

最终Release真实可选择正文与键盘轻采样：377帧、P95约33.27ms、最大151.70ms、12个超过50ms间隔。历史锚点及队列隔离通过，但仍不能称性能验收已完成。证据目录：`.runtime/parity-main-validation-2026-10-03/timeline-reading/`；严格回归入口为 `tests/run_ios_navigation_regression.py <simulator> timelineboundary`，Release轻采样使用 `CARRYON_IOS_CONFIGURATION=Release` 和 `timelineperformance`。

仍有效的全量代码验证：Python867项、109项条件跳过；JavaScript97项；Swift Testing151项与XCTest7项。条件跳过的原生项目文件10项及Owner66项另有启用后的专项通过证据；已验证部分不可冒称全部真实账号路径。


本段历史生产入口Release构建通过，未替换App入口为fixture；后续 typed 列表与输入排版改造后需重新构建，此处不代表当前产物：`.runtime/production-final-build/Build/Products/Release-iphonesimulator/CarryOn.app`；bundle ID为 `com.hanzeal.carryon`，签名检查与bundle内product.json和源码一致性检查通过。构建日志及产物SHA256见本日证据目录。该产物为arm64模拟器构建，尚不是实机验收或正式发行包；未提交、推送、安装到用户真机或部署。


## 当前最终状态：流式行更新已独立投影

此前“行内容独立投影未采用”的记录是阶段结论，以下述最终实现与原始证据为准，保留原失败和对照数据。

正式实现将正文与预解析 Markdown 保存在逐行可观察对象中；纯正文变化不再引发整表交易。投影完成后先检查会话、工作区和显示代次，再发布行内容；有成员变化时仍在实际表交易内更新。菜单执行读取当前行正文，编辑再次校验权限；侧聊能力变化保留原 Message 重绘标记。对象只保存显示投影，没有第二套权限业务规则、兼容分支或生产测试钩子。

正式代码严格回归通过九组字形/选区场景以及十三项行操作断言，包括旧菜单复制/选择/编辑最新正文、撤权拒绝编辑、等待解析时切换会话/工作区拒绝旧发布、搜索固定后增长不修复阅读位置，以及原生 UITextView 选择菜单在 create 权限、side-create 能力撤销/恢复时的五项检查。入口仍为 `tests/run_ios_navigation_regression.py <simulator> timelineboundary`；测试注入只修改隔离副本。

采纳依据是同五次正文追加与同长度序列的 Release 配对，按首个请求到最后实际 View 求值后划定流式窗口：原生产 P95 50.59ms、峰值189.00ms、4个超过50ms间隔；候选P95 34.14ms、峰值66.19ms、1个超过50ms间隔。五次更新均观察到相同长度22/44/66/88/110。观察延迟记录的是 View 求值，不是 GPU 呈现。候选整体峰值149.84ms，因此只接受流式局部收益，仍不关闭新增成员阶段及整体性能验收。原始 result/samples/build 与比较记录在 `.runtime/parity-main-validation-2026-10-03/timeline-row-paired/`。


正式最终 Release 复测：整体P95 29.91ms、峰值117.85ms、6个超过50ms间隔；实际五次流式窗口78个间隔、P95 33.30ms、峰值37.29ms、0个超过50ms间隔，五个相同正文长度均观察到。历史阅读/展开和队列隔离通过。最新正式严格回归还加强撤销菜单断言，要求目标cell仍可见，十三项及九组字形再次通过。上述数据仍不表示整体性能合格。

后续三条隔离探索均未进入生产：成员自然插入布局通过，但第三方等待后台差分后缺少拖动/导航二次核对，且未覆盖减少动态效果；首屏60行峰值119.00ms没有改善，并未通过原历史展开窗口断言；LazyVStack尝试当前只有3个用户消息导航标记，不能代表千项导航，峰值132.51ms也无改善。导航索引只包含用户/steering消息，不把1000条助手历史错误当成1000个标记。保留原始结果，未为采用候选降低断言。


## 尺寸测量复用：正式代码与严格回归

正式段落 Coordinator 只保存两个精确宽度的高度结果，正文、字号或主题渲染键变化清空，不共享跨消息高度，不改变权限或原生选择状态。缓存同时容纳 SwiftUI 的有限及无限宽度提案；实际字体、文本、宽度变化均重新测量。

在原三次新增成员同步布局中，每次出现181–214次段落尺寸计算，累计约19–23ms。这支持尝试缓存，但不是将73–94ms同步布局全部归因于 TextKit。两轮无诊断 Release：P95 21.19/22.10ms、峰值116.68/107.73ms、7/5个超过50ms间隔；上一正式基线P95 29.91ms、峰值117.85ms、6个超过50ms间隔。独立诊断前5.5秒1306次测量请求、1270次命中，记录的尺寸方法耗时合计约7.75ms。诊断数据不能直接折算成用户端收益。

独立审查接受为有限重复测量开销优化。正式最终回归通过九组字形及24项行/布局操作断言：同一存活 UITextView 的初始、正文增长/缩短、变窄/变宽/恢复宽度、大/小字号、主题和侧聊权限变化均检验实际文本、字体、菜单、高度、对象身份；每项还检验无限宽度再回有限宽度后高度有限、实际 line-fragment 字形几何不变。维持近底部cell原点与字形双约束和所有旧历史/搜索固定/跨scope断言。测试窗口只存在于隔离副本，正式源码无测试钩子。该改动不关闭新增消息长帧、真人拖动、真机及真实账号验收；恢复方式是移除 Coordinator 两项缓存并还原原 TextKit 尺寸调用，不涉及数据迁移。

证据：`.runtime/parity-main-validation-2026-10-03/timeline-sizing/`。诊断曾因把infinity写入JSON失败，修正记录为字符串后成功，未修改生产宽度语义；保留原失败日志。首轮附加布局测试错误裁剪尾空格，已按生产仅裁剪newlines的规则修正，再严格通过，没有放宽高度/字形/身份约束。


最终正式源码无诊断复测：410个帧间隔、P95 23.98ms、最大116.20ms、7个超过50ms间隔；历史阅读、展开、队列隔离均通过。生产入口 Release 再次构建成功并核验签名及 bundled product.json；最新可执行文件SHA256为 `2d3ac2fdac7131a079d81e7f331d013bbef40b539a674a0fdb35bebff343090b`，证据为本节目录的 `production-artifact.json`、`production-release-build.log`。这些记录替代此前产物与性能阶段记录，不代表真机或整体性能已完成。


## 2026-10-03 侧聊菜单修正与原生列表候选

正式侧聊菜单现在分别执行复制和选择文字，选择操作打开实际原生选取 sheet；执行读取当前消息，并重新核对工作区、显示代次、父会话、侧会话和 view 权限。退出、切换与撤权清除选取状态。Release 隔离应用通过原 conversationvisual 回归与新增9项菜单检查，独立审查局部接受。证据为 `.runtime/parity-main-validation-2026-10-03/side-message-actions/`；此前遗漏的测试接收器和首次类型检查失败保留在同目录。此前产物 SHA256 已不代表含本次侧聊修正的最终产品，需最终重建。

原生 UITableViewDiffableDataSource 原型已完成保留行对象、事务版本、迟到目标导航、作用域和分页取消验证；两次配对测量有局部收益，仍出现长帧。第一次未观察到真实正文更新的性能结果无效，保留 `.runtime/diffable-prototype/initial-invalid-observation/`。测试已要求实际 View 求值观察到全部五次完整正文和 UTF-16 长度，不能只凭请求或帧计数通过。

typed 列表在隔离副本中移除主会话的 Exyte Message、假日期、customData 和旧交易适配；正式 Side chat 仍使用其现有 ChatView 菜单协议，不保留两条主会话实现。候选首轮9组字形、24项行/布局操作和12项事务/导航/分页保护通过，证据 `.runtime/typed-list-candidate/timelineboundary/`。该轮之后仅供测试使用的 didApply 接口从候选生产源移除，完成回调在隔离测试副本注入。当前仍需 typed 搜索、header 状态高度、关闭/重开、原生历史窗口、性能及最终独立复核；候选尚未进入正式源文件，不能将原型或首轮结果算作整体交付完成。


候选后续检查发现并继续修正：header 首次捕获的 timeline 状态导致同步提示丢失；只读环境在 live body 外构造导致权限 flag 均 false 时呈现可能滞后；空标题行在长历史中产生原生估计高度占位；关闭重开时纯绝对 offset 在未测量行上被截断。正式代码仍未采用这些候选修正。原失败保留在 `typed-list-candidate/liststates/initial-missing-sync-header`、`initial-long-reading-failure`、`initial-question-probe-missing`；后者是测试未安装问答 marker，不能归因于产品。

当前隔离候选按实际内容添加/删除 header，以明确内容键更新非空 header；只读上下文在 live body 读取；内存阅读状态保存可见行 ID 和相对原生行顶部的偏移，恢复优先当前活动目标、实际阅读位置、历史导航目标。目标在可见区外时先进行原生行定位和测量，布局后复核作用域、请求与用户意图。零高 header 是否挂载 UIView 不作为空态判据，改为验证无标题行；重开不要求 UITableView 的估计绝对 offset 相等，而要求同一行与实际文字字形屏幕坐标小于1pt，保留 offset 诊断。更改后的完整验收尚在进行。

typed 的阶段 Release 性能（非最终代码）：436帧，P95 21.36ms，峰值85.71ms，3个超过50ms；五次完整正文均观察到，旧历史阅读、展开及队列隔离通过。仍有长帧，未关闭整体性能；此记录不能替代后续修正后的正式性能复测。


### 2026-10-03：原生 typed 会话列表正式接入

两份独立审查允许本地接入后，正式主会话列表替换为 `ConversationList`、`ConversationListEntry`、`ConversationListTransaction` 和当前身份校验的菜单动作。移除主列表的 Exyte Message/customData/日期排序投影与其事务适配；Exyte 仍服务侧聊的实际消费者。阅读位置用可见消息和原生行内偏移保存，历史完整且消息已删除时结束普通恢复；外部活动定位保留迟到目标等待。切账号/会话、卸载列表、取消分页和旧事务完成均按当前身份及版本校验。

最终隔离 Release 证据在 `.runtime/typed-list-candidate/`：boundary 九组字形、24 项行操作/布局、12 项守卫全部通过；search、conversationvisual 与 28 项 liststates 通过。最终性能为 434 帧，P95 19.21ms、最大 60.80ms、一次超过50ms，五次完整正文与 UTF16 长度均实际观测通过；阅读、历史扩展、队列检查通过。60.80ms 间隔发生在 5.52s 附近的历史定位阶段，仍不声明整体性能无改善空间。

checked-in runner 和 fixture 已迁移为单一 typed 路径，新增 `liststates` 和列表守卫；移除不再对应实现的 dateOnly 断言，保留正文、字形、稳定高度、权限和身份检查。测试输入无 `/tmp` 或隔离原型依赖，测试钩子仍仅注入副本。阅读意图 hook 不代表真实用户拖动；测试宿主复制目录遇到 `__pycache__` 的失败已修复为仅复制文件，不计产品失败。

正式源码与独立审查候选六份 Swift 文件字节一致。接入后的仓库 runner 回归、正式入口构建及新产物校验正在执行，旧生产产物和 SHA 不代表当前源码。整体一比一复刻、真机交互、真实账号和私有协议范围仍遵循前文未验证边界。


### 同文输入栏视觉精修与交互验证

官方与本机同文截图均为1206px宽。标准正文由17pt改为15pt基准，并通过 `UIFontMetrics` 继续动态缩放；普通输入、占位、引用标签及测高使用同一字体。正文行距按2pt基准缩放，显式作用于附件字符与后续输入；正文上下留白单独调整。加号及设置图形在各自44pt布局区域内向内4pt，发送图形保持32pt。

同英文正文、两个自定义PNG引用与一个通用引用，实际四行及逐行结尾与官方参考一致；完整系统键盘截图使用 owned simulator 截图，不以只含应用窗口的 drawHierarchy 图冒充键盘实图。独立视觉审查局部接受。fixture自定义图案不是官方原生图案，系统键盘语言、大小写及候选词不作为产品差距。

字体刷新在正文未变时保留 UITextView 选区，并独立记录 renderedFont，避免 UIKit 自动更新 view.font 后漏重建 attributedText；markedText 期间不重建。此前常规与辅助功能大字体输入验证已通过，追加的“六完整行后第七行裁切”以及最终样式回归继续执行。

输入栏spacing初次视觉运行超时，owned app主线程采样定位到 UIKit `UIPasteboard.general.items` 等待模拟器服务 semaphore（`/tmp/carryon-spacing-timeout.sample`）。仅重启该模拟器 `com.apple.pasteboard.pasted` 服务后，最新视觉运行通过；未修改host剪贴板服务或自动同步配置。失败日志保留，不算产品通过证据。


严格六行验收首次发现包含emoji的正文在字号行高估算下裁切第六行。失败原始结果保留在 `composer-six-lines-initial-failure`；现按 TextKit 实際第六行 fragment 底部封顶，常规12项输入检查通过，包括第六行完整、第七行须滚动、字体刷新选区、程序化markedText与引用复制/删除。引用图标及间隔按当前字体比例缩放，保持图标方形，避免大字体下固定宽度与变高高度造成拉伸；仍需最后常规/大字体与完整视觉重跑。


模拟器通用剪贴板全类型读取再次阻塞，新的独立采样确认仍为系统信号量等待。测试副本现按 `ios_clipboard_isolation.py` 使用每次启动独立的真实 UIKit 命名剪贴板，仅覆盖 composer/conversationvisual/timelineboundary；产品代码不变。独立审查接受该隔离，它验证显式复制正文、引用名称、剪切粘贴和权限/身份保护，不声明通用剪贴板同步或系统原生复制菜单已验收。使用该隔离后的最新视觉回归通过，同文四行结束仍与官方一致；完整最终回归继续执行。


### 本轮最终复核与正式产物

本轮正式八场景全部通过：标准及辅助功能大字号composer各12项、conversationvisual同文四行与完整键盘、liststates28项、timelineboundary九组字形/24项操作/12项守卫、完整timeline、轻采样timelineperformance及parity。独立UI及能力审查均接受本轮列表、输入及对应交互范围，没有新增必须修正项；不扩展为整产品逐状态一比一结论。

最终轻采样441帧、P95 17.63ms、最大68.18ms、三个超过50ms间隔；五次完整正文及UTF16长度观测通过。长间隔位于0.40s初始阶段、1.05s状态/成员更新附近及5.54s历史定位阶段。七秒owned测试进程诊断采样主要含等待与UIKit/SwiftUI布局、snapshot应用，不能把聚合调用栈当作每个长帧的确定根因；不据此追加未经验证的缓存或改动第三方代码。诊断采样单独存储，不能替换未采样的正式性能数据。完整timeline同时运行多项交互，不将其201.56ms峰值冒称轻采样数据。

生产入口Release已重建，签名verify、`com.hanzeal.carryon`、arm64模拟器架构、嵌入product.json与源码一致性检查通过。当前binary SHA256：`3b501444d7628b06a9ee643f8bbcb6d7699fce095aa7943bb537ed80ca0259d6`。源码哈希、结果、构建日志与产物记录在 `production-final-manifest.json`；旧SHA不适用于当前源码。仍为模拟器构建，不代表真机发行或部署；main保留未提交改动，未推送或部署。

证据目录 `.runtime/parity-main-validation-2026-10-03/formal-final-*/`。已完成的公开能力与测试仍按前文保持；真实账号、真实IME/手势、真机音频及性能、官方全部弹层逐状态视觉与私有受管服务生命周期仍不属于已成立验收。当前环境未提供可用真机及可操作的未锁定官方应用会话，不能补造这部分结论。

最终只读环境核验：devicectl返回两台物理设备tunnelState均为unavailable；IOConsole状态CGSSessionScreenIsLocked=Yes。设备原始状态保存在 `device-availability-final.json`。此状态阻止真机与未锁定官方应用的进一步实测，不以模拟器或静态源码替代该验收。
