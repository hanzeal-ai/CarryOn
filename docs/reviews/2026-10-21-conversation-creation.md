# 会话创建修复验证（2026-10-21）

范围：CarryOn iOS App 的项目内新建与首页不选项目新建。风险 R2：共用创建接口与持久化请求回执。用户授权实现及实际创建验证；未授权生产部署、推送或提交。本次直接使用当前工作目录，未创建 worktree。

## 实现与影响

- 保留任务开始前已有的原生项目目录改动：`Catalog.projects()` 从 `projects/project_roots` 读取权威 ID，创建时重新核对项目；不再把桌面旧 ID 传给原生 `thread/start`。
- 桌面 OwnerBridge 声明 `supportsProjectlessCreation`；无项目目标在后端解析为 None，使用 owner/tasks/<request-id> 独立目录，核对原生返回的空 projectId、cwd、historyMode 后才发送首条消息。
- iOS 保留项目选择并提供“无项目”；首页不会因只有一个项目而自动归入该项目。按钮和提交校验共用目标判断，无项目请求省略 projectId。独立工作区既有 directCreation 行为保持。
- 新建附件和引用发现复用相同目标解析。保留请求授权、连接代际校验、幂等回执和创建后不确定状态。
- 对无项目创建既有 `new:` pending 键补全终态回执清理，不更换键以保留升级前请求身份。uncertain 及缺少创建 ID 的成功回执继续保留。

## 已验证

- 聚焦后端测试：`PYTHONPATH=tests:. python3 -m unittest test_project_creation test_creation_references test_uploads test_catalog test_workspace -q`，98 项通过，无线程警告。
- `python3 tests/run_creation_regression.py`：使用真实 Codex app-server 与本地模型响应服务，覆盖原生项目 ID、空项目列表、两类实际创建及首条流式回复、归属、目录、重复请求、释放与归档。
- 本机真实登录账号：通过 CarryOn 的 scoped_dispatch -> 创建服务 -> 原生 app-server -> owner IPC -> 首条消息完整链路，两条均收到 CARRYON_CREATE_OK，且原生归属和重复请求身份匹配。证据：`.runtime/new-conversation-live-result.json`。
  - 项目：01a15c66-dd7d-70e0-be51-5740a3af33bb
  - 无项目：01a15c67-4532-73d3-a51c-a083ae8b1368
- 两条测试会话保留；未删除用户会话或修改业务文件。
- iOS 模拟器页面回归：`python3 tests/run_ios_navigation_regression.py 37847076-5D1C-4815-A8AC-061176398EB4 creationrefs`，21 项行为检查全部通过，包含无项目发送、选中项目传参、清空项目、能力撤销、失败保留草稿、创建身份确认后打开新会话。截图已检查，“无项目”与可用发送按钮正确显示。证据：`.runtime/creationrefs-regression/result.json`、`creationrefs.png`。

- 最终 iOS App 模拟器构建通过（包含 PendingWrites 修复），日志 `.runtime/new-conversation-build.log`。最终差异 `git diff --check` 通过。

## 独立审查与恢复

独立审查者基于原始代码、任务前快照、测试和真实创建证据审查。首轮要求修复 new: 回执清理，已补充代码及重启恢复回归；独立复审通过，P2 阻塞已解除。`swift test --package-path iOS --filter projectlessCreationReceiptReconcilesAfterRestart` 通过，覆盖 uncertain 保留、缺身份 completed 保留、failed 与完整 completed 清理。

未修改运行服务或手机安装包。恢复本次代码时只反向应用本次增量，不能 git reset 当前工作区；任务前已有改动保留。任务前相关文件快照位于 `.runtime/new-conversation-fix-baseline/`，增量补丁位于 `.runtime/new-conversation-incremental.patch`。已有原生项目目录修复不属于可回退的本次新增改动。
