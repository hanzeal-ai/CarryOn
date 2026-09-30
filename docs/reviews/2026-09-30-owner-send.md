# 未加载会话直接发送时接管 Owner

目标：iOS 对已有未加载会话直接发送时，由后端确认无 IPC owner 后接管并投递；自动释放后再次发送同样有效。手动加载、已有桌面 owner、独立工作区和临时聊天沿用原有边界。用户明确要求不写兼容性代码；本次仅复用现有 OwnerManager 与原生 IPC，不增加旧协议或历史版本回退。

本次在当前 main 工作目录局部修复，起点 HEAD 为 e1d9c5e2acedc585a358b9fefb705685a539cc4e，已有大量未提交改动。未创建 worktree 或提交；代码验证完成后，经用户追加授权重启本机服务。修改前相关文件完整基线保存在 `.runtime/source-backups/2026-09-30-owner-send/`，不会以整仓回退覆盖其他工作。

风险 R2：发送入口可能恢复执行进程并取得原生写锁。授权为用户本轮要求“修复一下这个链路”；用户随后明确授权“重启服务”，已完成本机服务重启；iOS 实机发送仍待验收。

## 影响与实现

`Bridge.compose` 和消息 `_dispatch` 共用 `send_snapshot`，默认保持原有快照读取。`OwnerBridge` 仅对确定的 `no-client-found` 复用 `OwnerManager.load`，随后重新获取原生快照；不捕获写入失败并重发，也不以历史状态代替执行状态。仅作用于持久会话，临时聊天不尝试恢复。

接管前、Manager 恢复过程中及恢复后核对 bridge generation、会话可交互范围和远程授权。沿用 Manager 的已有 owner 探测、分页历史要求、原生 writer 锁及竞争拒绝机制。读取和写入 IPC 响应时不持有 bridge 锁，保留状态流、取消和审批处理能力。

重复请求优先读取原回执；已接受或未知请求不会因 owner 释放而再次加载或执行。compose 检查与实际 dispatch 之间 owner 消失时，dispatch 再次核验并加载；实际 start 之后的错误继续沿用原有确定失败/未知结果语义。

## 验证

- `python3 -m unittest discover -s tests -p test_owner.py -q`：42 项通过，其中新增 11 项，覆盖两个发送接口、自动释放后再次发送、原回执重用、已有 owner、错误和未知结果、只读/撤权、加载中取消、竞争与 legacy 拒绝、临时聊天及检查与投递间释放。
- `python3 tests/run_owner_regression.py`：隔离 CODEX_HOME、真实 app-server、本地模型 fixture，连续两轮未加载 compose → IPC 接管 → 原生 turn/start → 流式完成 → 自动释放；同时验证 API 回执去重、原生消息去重及另一 app-server 归档成功。测试用 socketpair 模拟路由连接和缺失 owner 的应答；不声称验证了实际桌面 router/iOS UI。
- `python3 tests/run_creation_regression.py`：既有新建会话、原生项目归属、Owner adopt、真实流式执行、去重、自动释放与归档回归通过。
- Python compileall、差异空白检查通过。
- `rtk proxy python3 -m unittest discover -s tests -q`：589 项，588 通过、1 跳过（153.303 秒）。运行有 zip 重复条目与 SQLite 未关闭的警告，无测试失败；本次未扩展修复这些告警。
- 独立 R2 审查通过：审查者依据原始代码、基线差异、授权与回执实现形成结论，未发现阻断缺陷或不必要兼容层；独立重跑 42 项 Owner 测试、23 项 IPC/Bridge 测试及两个真实 app-server 回归均通过。

## 恢复与待验收

用户明确授权后已重启 CarryOn：重启前服务无 app-server 子进程（仅 caffeinate），重启后 PID 从 67063 变为 75752，端口保持 8769，桌面 IPC 与云端均已连接，supportsSessionLoading 为 true。iOS 实机发送未执行，待用户验收。恢复代码时按本次基线比较并仅撤销本次修改；不得直接覆盖基线之后其他会话的新增修改。若已部署，先等待或停止 Owner 执行、确认空闲并释放，再恢复代码和重启；保留请求回执及 Codex 原生数据，未知请求不得重新发送。
