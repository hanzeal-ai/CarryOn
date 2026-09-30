# 全盘审查修复记录

当前用户授权：按审查报告顺序修复，每步开始前汇报，逐步实现与验证。
直接在 main 工作区修改，不使用 worktree，不提交、推送、部署或操作真实会话。
起点 e7162371367424b90e746e8b0a29c991fbaf9613。开始时49个已修改/删除文件属于已有工作；本任务在其基础上修改，不回退或混入提交。
本机原生基线：ChatGPT.app 26.924.22138；原始安装包 app.asar 只读检查。
风险R2：原生协议、已读游标和投递状态。用户已授权修复；独立审查逐步执行，真实原生写入、发布和真机验收不在本次自动验证中。

## 1. 原生协议

- settings follower v2，以 applied 布尔回执区分已应用、未应用和未知结果。
- queue broadcast v2，必须包含本地 hostId，并仍校验当前跟随 owner。
- read-state broadcast v3 新增身份上下文。CarryOn 不复制原生账号判定；将广播仅作为已跟随会话的刷新信号，不信任其中的已读值。
- 异步核实原生 owner 快照；重置、切换快照或新的刷新信号使旧结果失效。推进游标时以 bridge→IPC 锁顺序完成验证与写入，避免旧 false 清除新未读。实时投影优先使用最新原生快照。
- 回归涵盖设置 applied 回执、旧版本拒绝、无本地主机的队列拒绝、异步事件重置、广播与原生值冲突、回调提交前到达新事件，以及真实 HTTP/WS 投影。

后续步骤依次为回执语义、契约测试、Web/iOS规则统一、无调用代码清理、局部职责整理。完成证据随步骤追加。

恢复：停止本次新版本服务后只撤回本任务差异；保留原有未提交改动、Journal、请求ID和通知游标。代码回退不撤回已被原生接受的动作；不通过清空状态重试。没有数据库迁移。

第一步验证：134项针对性测试通过；独立审查者复跑并通过。原生设置版本校验与广播版本依据来自当前安装包，不发送真实业务操作。

## 2. 原生回应回执

独立app-server的审批、输入、MCP回应只有收到同一进程、同一threadId及相同类型requestId的serverRequest/resolved才完成。写入成功但事件未到时保留uncertain；同一请求ID不重放，原生回复waiter同时阻止换请求ID重复写。断线清除瞬态证据；Journal保存进程会话标识以拒绝新进程的相同ID。晚到事件可通过Journal完整记录CAS恢复，不能覆盖人工确认。完成证据命名为native-server-request-resolved，仅表示请求已解决，不证明某个审批决定的具体执行效果。

第二步验证：82项组合测试通过，独立复审通过。明确写入前IPC拒绝释放waiter，部分写入和超时保留未知证据。

## 3. 原生契约门禁

新增独立捕获的desktop IPC版本夹具；标准unittest discovery会核对实现与该夹具，并在安装App的主机直接读取ASAR版本表。缺方法、版本漂移或包结构不可识别均失败。`scripts/check_native_contracts.py`可在App升级后单独运行，不连接socket。
公共JSON schema另用独立工作区实际选择的Codex可执行文件导出校验。本机为PATH中的Codex CLI，而非ChatGPT.app内置程序；不能将此项误报为桌面IPC schema检查。无相应App/CLI的CI环境明确跳过动态检查，但仍执行离线夹具和行为测试。

第三步验证：53项契约与IPC行为测试通过；本机ASAR只读检查通过；独立复审通过。

## 4. Web/iOS模型设置

Web复用/api/models，按模型提供的efforts/defaultEffort展示；不再维护全量硬编码强度。保留当前未知值供核对但不允许将未提供组合保存。目录读取失败明确显示并可重试；缓存以传输对象及epoch隔离，过期、切换工作区、移除节点后的响应不写UI。设置重渲染保留草稿，只读状态和提交期间禁用控件。iOS已有同样目录路径，本步无须改动其业务规则。

第四步验证：桌面/手机宽度模型交互及完整会话操作浏览器回归通过，Node 43项通过，独立复审通过。补充跨重渲染的提交锁。原有重试测试已在任务初始源码上复现旧断言错误；更新为明确失败换ID、未知结果保留ID，保留两种语义的验证。

## 5. 无调用代码清理

删除无生产调用的SubagentLinks、ConversationDisclosureGroup、answerQuestion和singleActivity；保留实际使用的折叠状态及多活动摘要测试。删除仅测试使用的app-server project投影函数；消息顺序、用户输入、审批测试改为经过真实thread/started和server request事件处理入口。

第五步验证：app-server工作区13项、Swift Core110项通过；独立审查额外组合问题处理共19项通过。

## 6. 局部职责整理

iOS沿用既有AppModel extension组织方式，拆出ConversationDelivery（请求身份、回执核对）和ConversationComposition（编辑与草稿提交）。状态仍由AppModel持有，没有新增业务状态副本；仅开放跨文件所需的pending只读访问与reconcileOutgoing方法。原有权限、epoch、草稿与请求ID路径保持一致。

Web直接为现有DOM应用同样控件样式，移除每个控件临时createRoot/flushSync/cloneNode/unmount替换流程、React/Radix依赖及其构建插件、旧React生成器配置。构建产物由258887字节降为30534字节；锁文件仅删除不再使用的依赖。冻结安装、Vite构建和根静态产物一致性检查通过。

控件浏览器测试覆盖节点身份、事件监听、焦点、选区、输入与默认值、复选框状态、文件选择、disabled、样式覆盖及重复装饰。页面4种宽度×2种主题和桌面/手机会话操作回归通过。iOS无签名arm64构建通过，未安装或操作真机。

范围备注：最终检查观察到project.pbxproj较任务初始快照存在格式化和Recovered References分组差异，该文件未由本任务编辑脚本修改，来源未确认，予以保留；不把它计入本次功能修复。

## 最终验证

- 全量Python unittest：553项，552通过、1项APNs依赖环境跳过；APNs在专用.venv-apns补跑1项通过。
- Node测试43项通过；Swift Core110项通过；iOS完整无签名device构建通过。
- 模型设置桌面/手机测试、会话操作桌面/手机测试、控件状态保持测试、4宽度×明暗主题页面检查均通过。
- 冻结依赖安装、Web构建、根JS/CSS与构建产物逐字节一致、Python编译与JavaScript语法、git diff --check通过。
- 全量Python输出仍有测试夹具重复ZIP成员及SQLite连接释放的warning；未出现失败，不把这些warning表述为消除。
- 未执行生产部署、真实原生写入、真实云端链路或真机交互验收；未提交、推送、合并。运行浏览器所需静态服务只监听127.0.0.1，测试结束后停止。

六步均完成独立复审；第六步复审确认无新增状态副本、权限绕过或DOM状态丢失，无阻断项。本次授权修复与本地验证闭环完成。
