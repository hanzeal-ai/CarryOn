# CarryOn 账号与工作区改造独立审查

## 范围与结论

风险 R2。用户指定 GPT-5.5，由独立 Agent `/root/review_gpt55` 读取源文件、差异和测试形成结论，并可要求修改或拒绝。最终结论：**接受（Accept）**。本记录整理自审查者返回的结论，不代表生产发布批准。

审查覆盖 app-server 协议与任务状态、独立工作区 CODEX_HOME、Codex 认证与 CarryOn 账号分离、密码修改、定向绑定、权限与恢复边界。

## 要求修改及关闭证据

- 旧链路清理误删正常 `/console/logout`：恢复会话持久化、二维码清理、推送注销及实时流释放，相关认证和多云测试通过。
- 创建会话将 `turn/start` 接收误判为执行完成：改为 `accepted` 并保留 `createdThreadId`；`_refresh_job()` 根据 native terminal turn 映射 completed、failed、interrupted；测试覆盖三种终态。
- Codex 登录状态由 `account/read` 初始化、由 `account/updated` 更新；未登录拒绝直接创建，与 CarryOn 账号授权分离。

## 审查者验证

- `PYTHONPATH=tests python3 -m unittest test_app_server_workspaces test_product_accounts`：38 tests OK。
- `python3 -m compileall -q carryon`、关键模块 AST 解析、`git diff --check`：通过。
- 最终复审未发现新的阻断问题。

## 最终实施验证与边界

最终完整回归为 Python 410 项（跳过 1 项）、JavaScript 38 项、Swift 73 项；桌面编译及 iOS Simulator、iPhoneOS SDK 未签名构建成功。证据路径见 `docs/implementation-onboarding.md`。

用户要求常规测试和构建，不再试机。生产绑定、Apple 线上关联与系统密码自动填充、签名发布不在本次已验证范围。app-server 原生队列编辑不可用，明确返回不支持。未授权或执行提交、推送、部署及生产数据变更。恢复边界见实施记录。
