# Web 与 App 功能同步

基线：只读核对 e96a/CarryOn 当前未提交源码和 2026-09-20 四份审查记录。c6d7 初始工作树干净；不修改源工作树。Web 由 example.html、app.js、mobile-ui.js、timeline.js、operations.js 与两个 transport 客户端组成；web/src 为现有控件构建层，不另建页面。

风险 R2：会话可用性、异步导航、发送回执和共享历史投影。操作权限继续由现有服务端/原生 access 与客户端 canInteract 控制。实现授权不包含提交、部署、真实消息或审批。恢复撤回本任务差异即可，无持久数据迁移。

| 能力 | 影响路径与权威契约 | 验收 |
| --- | --- | --- |
| 可用偏好、全部会话与筛选 | workspace availableOnly、workspace/threads；app 列表查询、mobile 设置与快捷导航 | 默认关闭不活跃；idle 保留；过滤先于分页计数；四种筛选 |
| 未加载历史 | 源 bridge/ipc/realtime/rollout 及对应测试；timeline 展示 | 分页、追加、原生切换；无写权限；明确桌面打开提示 |
| 生命周期与缓存 | 两个 client transport、app 连接展示 | 短回不重新订阅；失效重连；scope 隔离；缓存不授权 |
| 阅读连续性 | timeline 渲染锚点、列表分页窗口 | 新消息/同 ID 流式更新不移动旧阅读锚点；回到最新 |
| 动态与通知 | 原活动投影与 timeline 锚点、导航 generation | 结果直达；审批仍走既有请求；迟到请求不覆盖新导航 |
| 回执与改动 | 原 jobs/:id GET、timeline fileChange/turnDiff | 只查询原请求不自动重发；只读 diff |
| 其他现有流程 | operations、subagents、附件、工作区和设置 | 现有浏览器回归；独立源码差异审查补充缺口 |

验证计划：共享 Python 回归、Node 客户端测试、桌面 1280 与移动 390 浏览器隔离交互和截图，最终独立审查。隔离 transport 不等同于真实云端、APNs 或浏览器后台时限；如实标明未验证项。

## 最终功能核对

- 项目、全部会话、动态统一发送 availableOnly；偏好默认关闭并保存在当前浏览器。四种筛选复用服务端过滤，动态 includeRead 保留已读、允许清空已读，权限与审批状态不受已读影响。
- 来源基线中的 Bridge/IPC/Realtime/Rollout/Workspace 与必要 push 锚点及测试差异已纳入本工作树；不依赖源任务未提交文件。历史分页、追加和原生快照切换仍由同一后端负责。
- 本地历史显示桌面打开提示；连接断开保留缓存并显示最近同步时间。首次历史尚未确认、未加载、未知或错误状态不启用会话写入。
- 浏览器短暂返回保留健康订阅；本地应用层 ping/pong 只探测连接，云端使用已有 heartbeat。失效后重建并同步，不重放 HTTP 写入。Bridge workspaceSession 隔离不同本地实例，云端沿用设备/账号作用域。
- 列表保持已加载分页窗口及实际滚动容器位置；历史用可见消息 ID 和相对位置保持阅读锚点，追加/同 ID 更新可提示新消息并回到最新。
- 动态完成/失败按原时间线定位；前台通知携带请求/回合/条目锚点，历史查询受导航 generation 和 scope 约束；审批和问答继续使用原流程。
- 只读改动面板聚合当前历史窗口内 fileChange/turnDiff，不读取或写入文件系统。发送回执和请求记录的核对按钮只 GET 原 job，不重发。
- 新建会话补齐服务端项目选择和 projectId 创建；仍由服务端选择有效原生入口并验证项目归属。未知项目、权限撤销、忙碌入口和结果项目不符由原有后端测试覆盖。
- 工作区新增浏览器扫码/粘贴绑定链接，严格限定当前云端 origin/path 和 fragment 格式。先 inspect 显示账号与权限，再由用户点击确认 accept；无相机/BarcodeDetector 时支持系统相机链接和粘贴。未加入依赖。
- 保留发送/停止/队列、请求指纹、审批确认、失败答案与草稿、图片压缩发送/预览、父子/临时会话、注册登录、工作区切换和连接历史。发现并修复原时间线 navigator 变量遮蔽导致的复制失败。
- 原生更新安装不属于浏览器能力；Web 继续由服务端提供当前资源。没有新增外观系统或重设计页面。

## 验证结果

环境：当前 c6d7 工作树，Python 3.14、Node、已安装 Playwright Chromium；桌面 1280×844、移动 390×844，补充 320×640、390×390 与桌面恢复。所有业务写入均为隔离夹具。

| 验证 | 结果与证据 |
| --- | --- |
| Python 全量 | 462 项，1 项可选 APNs 依赖跳过；`python3 -m unittest discover -s tests`；`/tmp/carryon-web-python-complete.log` |
| Node 客户端 | 42 项通过；`node --test tests/test_*.js`；`/tmp/carryon-web-node-final.log` |
| 主同步功能 | `tests/check_web_parity.cjs` 双视口通过：偏好/筛选、130条分页返回与刷新、已读清空、只读提示、流式锚点、新消息、diff、GET核对、短回订阅、迟到通知、项目创建、同源绑定 |
| 写操作回归 | `tests/check_web_operations.cjs` 双视口通过：真实浏览器图片解码压缩/提交，停止 expectedTurnId、队列 fingerprint、审批 nativeRequestId/确认、失败问答保留与原ID重试、只读拒绝写入 |
| 既有浏览器设施 | loading、realtime、conversation_navigation、connection_workflow、independent_workspace、subagents、side_dialogue、message_edit 通过；包含跨工作区同thread缓存隔离 |
| 设计与响应式 | `tests/check_mobile_ui.cjs` 22 项设计几何检查及完整操作通过；旧用例按当前项目创建、增加的标准菜单行、已存在的状态行位置/账号字段/CLI管理边界更新，未通过删减安全行为断言规避失败 |
| 实际产物 | 已检查移动设置、未加载历史、桌面历史截图；`.runtime/web-parity-{settings,history}-{390,1280}.png`；Python compileall、变更 JS 语法和 git diff --check 通过 |

浏览器复现：在本工作树启动 `python3 -m http.server 8923 --bind 127.0.0.1`，设置 `PLAYWRIGHT_MODULE` 指向已安装 playwright，`CARRYON_UI_URL=http://127.0.0.1:8923/example.html`，运行上述 cjs 文件。新增两个 parity/operations 脚本默认使用 8923。

独立审查由单独只读审查者读取原始 App 基线与完整差异，先要求补齐动态契约/项目创建，再指出本地缓存身份隔离问题；修复后复核接受。审查者可要求修改或拒绝，不以本记录替代原始测试输出。

## 限制与恢复

本轮已验证的是 Chromium 实际页面与隔离 HTTP/WS、真实 Python loopback/SQLite/Rollout 链路（原生 IPC 为 fixture）。未测试真实业务云端、实体手机相机、Safari、真实 APNs 投递或操作系统长时间冻结/回收。浏览器后台执行无固定时限保证；恢复依靠可见性、网络事件与连接心跳。没有提交、推送、部署、PR、真实业务消息/审批或真机安装。

本地 workspaceSession 随桥接实例变化而保守清理显示缓存；同一实例的普通断线保留缓存。服务端持久 job 记录仍可查询核对。恢复撤回当前工作树本任务源码和测试差异；不触碰 e96a 原任务，也不迁移或删除用户数据。

## 2026-09-21 主分支整合验收

已授权将 c6d7 合入 main，沿用本任务提交、推送与自动部署授权。源工作树保留，快照分支 codex/pending-c6d7（e1e8fee）。整合基线 1bf42b6，保留 9603 视觉、输入框自适应和 b20a 手机确认绑定；移除旧绑定对话框依赖，扫码入口接入现有账号菜单与移动帮助。目标账号绑定也明确要求手机确认。无持久数据迁移。

独立源码复审通过；Git 冲突索引已收敛。Python 495 项通过（1 项跳过），Node 42 项通过；桌面/移动 parity 与写操作、导航、绑定入口、独立工作区、子会话、侧聊、编辑、加载和实时恢复检查通过。移动端 21 项布局检查、8 组视口/主题通过。绑定按钮验证先展示再确认，打开入口不写入绑定；权限/原请求核对与不自动重放语义保留。验证为 Chromium 与隔离协议夹具，实体相机、Safari 和真实云端绑定仍未验证。

回退可使用本次合并的第一父提交；不回滚账号/设备持久数据，不删除源 worktree。6e22 未引入：其跟踪文件与已在 main 历史内的 4b04502 完全一致，额外 design/web 为内存演示，仅保留设计参考。
