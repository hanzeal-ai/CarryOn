# 桌面工作区由 app-server 创建并经 Owner 投递

## 范围与基线

目标：手机选择 Codex 项目后，临时 app-server 直接创建原生分页会话，Owner 接管同一运行时，经现有 IPC 下发首条任务。用户明确要求不保留兼容代码。

风险 R2：涉及原生会话生命周期、任务投递、项目身份和远程撤权。保留现有绑定及成员权限契约，不新增依赖，不写 Codex 数据库，不推送、不部署、不自动重启用户服务。

在 `main` 当前工作目录修改，起点提交 `e1d9c5e2acedc585a358b9fefb705685a539cc4e`。任务前已有大量未提交模块重构和客户端修改；没有创建 worktree 或提交。任务前相关文件逐个保存在 `.runtime/source-backups/2026-09-30-owner-creation/`，本次差异位于 `.runtime/owner-creation.diff`。

## 实现与影响

- 新建要求目标项目 ID，校验原生项目身份与目录；原生 `thread/start` 使用 `projectId`、`cwd`、`historyMode: paginated`。模型与权限使用原生配置。
- 实测空会话在首轮前关闭进程后不能 `thread/resume`。因此创建进程交给 Owner 管理，直到任务结束后释放，不采用关闭再恢复的交接。
- 创建回执登记在原生写入前；相同编号并发只创建一次，内容冲突拒绝。创建后已知 ID 立即记入回执。结果未知不重建、不重投。
- 创建前、Owner 声明前、首轮投递前重新校验授权、连接代次和项目。明确拒绝或投递前失败回收空闲进程；投递结果未知时保留 Owner，等待原生证据或用户核对。
- 桌面工作区默认装配 Owner。原控制会话创建、配置入口、CLI、前端状态依赖、原生创建工具结果核对及 worktree 绑定解析全部删除，无旧链路兼容。
- 独立工作区保留自身 app-server 创建路径；普通消息和审批继续使用原有权威状态与权限契约。

## 独立审查

由独立审查 Agent `/root/review_creation` 对原始需求、变更前文件、当前实现及测试独立形成结论，可拒绝交付。可用模型列表没有规范优先的 `gpt-5.6-luna`，使用继承模型。

审查发现明确拒绝首轮后可能保留空闲进程的问题，已修复并增加负向测试。审查者独立执行 85 项聚焦测试及真实创建集成回归，全部通过；无兼容清理复核后接受当前代码。该结论不替代人类验收或部署批准。

## 验证

- `python3 tests/run_creation_regression.py`：真实已安装 app-server、隔离 CODEX_HOME、本地模型服务及真实 IPC 帧；验证零已有会话创建、原生项目归属、绑定请求作用域、Owner 接管、首轮流式完成、重复请求、自动释放、另一进程归档，通过。
- `python3 tests/run_owner_regression.py`：恢复、发现、历史、投递、去重、释放及归档，通过。
- `python3 scripts/check_native_contracts.py`：已安装桌面版本 `26.924.22138` IPC 契约通过。
- `python3 tests/run_desktop_smoke.py`：编译桌面 Swift 源码并验证隔离工作区服务生命周期，通过。
- `node --test tests/test_*.js`：43 项通过。
- `swift test --package-path iOS`：117 项通过。
- `pnpm --dir web build`、Python 编译检查、JS 语法检查及最终差异检查通过。
- `tests/check_mobile_ui.cjs`、`tests/check_independent_workspace_ui.cjs`：真实浏览器，模拟 HTTP/WS；移动与桌面切换、全屏创建、现有会话交互、独立工作区创建入口通过。
- `python3 -m unittest discover -s tests -v`：578 项，577 通过、1 项跳过，耗时 156.358 秒；日志 `.runtime/owner-creation-tests.log`。

额外运行既有 `tests/run_appserver_regression.py`，在 `account_ready` 断言失败：该脚本给 source 写入模型 fixture 配置，却未给实际使用的两个隔离 CODEX_HOME 写入配置。失败发生于本次未修改的 `AppServer.connect` 行为，未进入创建测试。此项不能声明通过，也未修改该无关测试准备逻辑。

未验证真实手机 → 生产云端 → 桌面 GUI 的完整设备链路。当前源码未部署，运行中的 CarryOn 服务需在用户确认后重启采用。

## 恢复与验收

停止接收新建请求，等待 Owner 空闲释放，再退出服务。恢复本次前相关源码或安装包，保留 CarryOn 请求日志和 Codex 原生数据；不得整仓重置或覆盖其他会话未提交改动。未知请求按原编号核对，不重新创建。

人类验收重点：手机选项目创建、桌面可见该会话、流式内容和审批交互、任务结束后归档。远程推送、发布和服务重启均未执行。
