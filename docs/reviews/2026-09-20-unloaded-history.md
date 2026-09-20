# 未加载会话的历史同步

目标：桌面 Codex 进程和桥接在线时，用户不必在 Codex 中打开旧会话即可读取历史；历史读取与实时运行状态分别如实展示。

实现边界：主会话没有完整原生快照时复用只读 RolloutIndex，支持 legacy 和 paginated 格式的增量索引、分页和更早记录加载。legacy 沿用原本的 response_item 消息可见性规则；paginated 用户输入仍只取 canonical UserMessage，避免把模型上下文当作用户消息。WebSocket 在本地历史模式下检查文件追加，原生快照就绪后自动切回实时投影。缺失或损坏文件返回读取错误，不以空记录或永久“同步中”隐藏失败。

状态与权限：本地读取成功返回 syncing=false、source=local-rollout、nativeReady=false 和空交互控件。运行状态只采用当前 IPC 的加载结果；没有证据时保留 unknown，明确路由失败才标记 notLoaded。不从记录的最后一轮或时间推断当前运行状态。桌面 Codex 完全退出后的离线桥接不在本次实现范围。

风险与恢复：按 R2 审查共享历史响应和状态投影。影响 Bridge、WebSocket、Web/iOS 状态显示和历史解析；不改变授权策略，不修改 Codex 数据或启动任务，无新增依赖。恢复只需撤回本次源码差异并重新构建，无数据迁移或回滚 SQL。本次未安装、部署、提交或推送。

验证：tests/test_unloaded_history.py 覆盖未加载分页、超过 200 条 legacy 记录、增量更新、原生切换、metadata-only、缺失和损坏文件，并通过 loopback WebSocket 走真实 Bridge/SQLite/rollout/server 链路（IPC 使用 fixture）。本机最旧的 8 个 legacy 会话经过只读分页解析，均取得记录。手机真机页面仍待人工验收。

最终证据：Python 全量 454 项完成（1 项因缺少 APNs 可选依赖跳过）；随后加入的 WebSocket 集成用例连同专项共 7 项通过。Swift 核心 97 项、Node 32 项通过；Python 编译、JS/shell 语法及 git diff --check 通过。独立审查提出 legacy 原有 200 条截断问题，修复并补充分页测试后复核接受，无剩余阻塞项。独立审查基于原始需求、源码差异及测试进行；真机验收和安装发布未执行。
