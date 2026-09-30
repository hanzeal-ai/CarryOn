# 任务结束后自动释放 owner

用户要求：解决桌面归档 app-server 会话时 `already has an active writer`，任务完成后自动释放 owner。

实现位于主项目 main，基于此前未提交的 owner 实现作局部修复。R2：会话执行进程生命周期。任务开始前保存了本次涉及文件的基线，未创建 worktree、未提交或修改其他功能。

自动释放同时要求：本次 owner 已接受的任务出现原生终态（completed/failed/interrupted）、原生 idle、无 inProgress 轮次、无待审批请求、IPC 回复写入已结束。仅加载旧历史不触发释放。未知启动响应只在后续原生新轮次终态证据出现时释放。

新请求和释放共用 manager 锁；原生状态在两次检查间改变时安全拒绝并延后，不停止其他会话。IPC 断线或失效快照发送失败不应保留已空闲的 native writer。回执跨同一服务内的释放/重新加载保留，避免重复执行；停止和审批不受执行回执容量限制。

验证：31 项 owner 测试、11 项 IPC 测试通过；隔离真实 app-server 集成验证了首轮执行、流式结果、去重、自动释放、另一个 app-server 成功归档。集成使用临时 CODEX_HOME 与本地模型 fixture，未操作用户会话。Python compileall 和 diff check 通过。

独立审查读取原始代码和测试，发现并要求修复执行配额阻断审批及单会话异常终止 publisher 两项问题；修复后独立重跑 31 项 owner 测试通过，无剩余阻断。

最终全量 Python 回归共 589 项，588 通过、1 跳过。经用户授权重启默认 CarryOn 服务，保持 CARRYON_OWNER_ENABLED=1；重启前确认原 owner 会话空闲且无审批，重启后桌面 IPC、云端连接、supportsSessionLoading 均正常。真实桌面点击归档的交互未重新验收；另一 app-server 归档通过证明原生 writer 已释放，不替代桌面 UI 验收。

恢复：空闲后停止 CarryOn，恢复本次涉及 owner manager 和 IPC transport 的基线，再启用原有 owner 配置。不得整仓 reset 或回退其他未提交工作；恢复旧行为会重新需要手动释放 owner。正常重启不会重新执行未知任务。
