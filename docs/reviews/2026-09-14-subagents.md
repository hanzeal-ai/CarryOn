# 子会话入口与共享详情

范围：Web（含手机布局）与原生 iOS 会话菜单新增子会话入口，多个显示列表、单个直达；结构化 Agent 活动名称可以打开目标子会话。主、子会话共用已有详情页、时间线、草稿与资源预览；只读子会话隐藏写入控件，可交互子会话使用已有主会话操作接口。未授权提交、推送、部署、安装到设备或操作真实业务会话。

风险 R2：共享读取接口与会话级读写边界。权威关系为 Codex 数据库 `source.subagent.thread_spawn.parent_thread_id`；全后代枚举按该关系去重，排除已归档记录。权限来自父会话结构化 `collabAgentToolCall.spawnAgent` 的发送者和接收者 ID；仅有 `subAgentActivity` 的后台 Agent 不获得写权限。未知关系默认只读。客户端不能指定或提升 `canInteract`。

## 实现边界

- `GET /api/threads/{id}/subagents` 返回 `threads`，每项有 `id/title/cwd/access`。`access` 包括 `isSubagent/parentId/canInteract`；历史另带 `nativeReady` 表示原生快照已就绪，客户端只有可交互且已就绪才启用写入。
- 子会话沿用 `/api/threads/{id}/history`、图片/文件资源、消息和 operations 接口，以及现有 WebSocket 选择、历史增量与分页协议。没有第二套子会话发送器或详情页。
- Web 的 `SubagentNavigation` 汇合菜单和内联入口，异步结果绑定原会话及设备范围；iOS `SubagentsView/SubagentLinks` 汇合到 AppModel 的会话选择。已有 `Timeline` 和 `ConversationView/ConversationTimelineRow` 是公共内容组件。
- 后端 `Subagents` 是统一访问判定，消息、compose、operations、控制会话选择均拒绝只读子会话。实际写入前再次判定，并保留既有 owner、状态、请求身份和远程授权检查。
- 没有 owner 的子会话通过只读持久事件投影展示历史，不生成运行状态、不恢复会话、不成为写入授权。选中该类会话时每秒检查文件版本，通过原有 WebSocket 更新；append-only 索引只扫描新追加字节，记录事件偏移，按 `historyLimit` 个可展示事件读取窗口（`historyWindow.unit=items`）。最多保留 8 个索引，每个索引只缓存一页且不超过 2 MB；不保留大工具输出在索引中。
- 持久投影使用已完成原生展示事件与非 analysis 的助手消息；用户输入只采用原生 `UserMessage` 展示事件，排除混有运行时/继承上下文的 raw user-role 模型输入，且不根据文本关键词猜测可见性。推理限摘要，不暴露开发者指令或加密/原始推理字段。若日志仅有原始或加密委派输入，该段输入无法恢复展示。输出、引用文件和历史页使用相同投影。损坏记录明确失败，正在追加的末行等待下一次文件版本。文件替换、截断会重建索引。
- HTTP 历史默认 limit=40，验证单一整数参数 1–4000，子会话持久历史按展示项分页；内部资源校验保留更早历史查找，回归覆盖窗口外文件预览。

## 验证

- `python3 -m unittest discover -s tests -q`：321 项，320 通过、1 项既有跳过；日志 `/tmp/carryon-subagents-tests.log`。新增 13 项测试覆盖父子/后代关系、大于 16 MB 日志增量索引/分页、只读全部写入口、可交互消息与设置共用原生方法、无 owner 拒绝执行、历史输出/去重/分页/修订、内部内容过滤、HTTP 参数验证和窗口外文件预览。
- `node --test tests/test_*.js`：36 项通过；原有客户端范围、幂等与增量回归，日志 `/tmp/carryon-subagents-node-tests.log`。
- `PLAYWRIGHT_MODULE=<installed-playwright> node tests/check_subagents_ui.cjs`：本地静态服务通过 `CARRYON_UI_URL` 指定，隔离 HTTP/WS 夹具，不连接业务 Codex。验收桌面/手机的列表、单个直达、名称跳转、只读展示、可交互共用详情、草稿隔离、空/失败/重试、迟到响应、断线、云端切设备/退出登录、未就绪写入禁用、溢出。
- `swift test --package-path iOS`：35 项 Swift Testing 与 4 项 XCTest 通过；Xcode Debug iOS Simulator 构建通过，`CODE_SIGNING_ALLOWED=NO`，只生成验证产物。日志 `/tmp/carryon-subagents-swift-tests.log`、`/tmp/carryon-subagents-build.log`。
- 真实已持久化子会话记录只读解析核对了消息、命令输出和 Agent 活动；未向真实可交互子 Agent 发送消息或审批，未进行真机验收。
- 真实 Sol 子会话日志复核：3 条 raw user-role 输入全部排除，投影保留 159 项展示事件；回归同时确认 canonical 用户主动引用的上下文标记正常保留。最终 wheel 重建后核对了 Python 源码一致性、JS 资源与 HTML 引用，`git diff --check` 通过。

## 恢复与审查

无数据库迁移、持久写策略或新增依赖。恢复时撤回本次 API/投影/导航及对应资源清单变更，保留原生历史、队列、请求账本及用户草稿。新 JS 资源随原有安装包和 wheel 清单一起交付，并已检查实际 wheel 内文件与 HTML 引用。工作区已有的品牌素材、输出文件及外部 Xcode 工程格式化改动不属于本次恢复范围。

独立审查：用户明确授权的 GPT-5.6 Sol（Erdos，01a09ef3-0b65-7942-91da-28351b759025）最终结论 **Accept，R2 门禁通过**。审查曾要求修正 raw user 输入暴露与 HTTP 无分页两项问题；修复后审查者独立核对真实持久日志、访问边界和最终差异，并复跑 13 项子会话、7 项 HTTP、321 项全量 Python 测试（1 项既有跳过），两项问题均关闭。此前独立复跑的 36 项 Node 测试通过。

剩余验证边界：未进行真实子 Agent 写入、真机交互或部署验证；窗口外资源查找仍需临时读取完整历史，存在大日志下的瞬时资源消耗。测试中的既有 ResourceWarning 与 wheel 重复文件名警告未导致失败。发布、提交和真机安装需要单独授权。
