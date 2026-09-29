# 原生投递回执与移动端交互

来源分支 main，起点 dc7e26bed66a621c5c72451a4fea388b18a2183f；工作分支 codex/ipc-receipts；最终合入目标 main。R2：普通消息、审批、停止、队列和创建的公共投递契约。用户授权全部修复；不部署，不修改 Codex 数据库。另一会话的 legacy 清理独立进行。

## 权威与变更

- 普通命令在 HTTP 调用内等待 IPC 回执；Journal 仅保留请求去重、投递结果和丢失回执的核对依据。原生 accepted 不再跟随后续任务执行改为 completed/failed，也不再阻止新命令。
- 停止和审批不受其他未知请求阻塞。同一轮次启动/编辑/恢复仅在请求实际投递期间互斥，仍执行原生状态、权限、连接代次及目标检查。
- 原生队列是全量读改写：队列请求独立互斥；不确定的队列写只阻止新的队列写，停止/审批不受影响。修改前读原生持久化队列，避免延迟广播覆盖较新的队列。请求 fingerprint 防止操作旧内容。
- iOS/Web 收到原生成功回执即移除临时卡片，不依赖历史同步。明确 HTTP 拒绝与 IPC handler 拒绝显示失败并允许新请求；网络/路由超时保留原请求 ID，相同内容不会盲目重发。iOS 按 scope/target/payload 保留 ID，不以整个会话为锁。
- 无 turnId 的丢失回执可以用原生 message ID（包括实际 clientId）或队列 ID 核验，不按普通消息文本猜测。没有证据则保持未知并支持人工核对。
- 服务重启前仍为 preparing 的请求确定未投递，记为失败；dispatching 仍按未知处理。
- 创建表单等待真实 createdThreadId，不能把 controller 已收到指令当作新会话创建完成。AppServer 已有 createdThreadId 的成功回执不再追踪后续任务执行。

本机 `/Applications/ChatGPT.app/Contents/Resources/app.asar` 原始证据：router 超时返回 `request-timeout`，follower 包装超时使用 `<method>-timeout`，二者均保留未知；handler 明确失败返回 error.message；acceptFromFollower 等待 storage.update 后返回成功，但队列 broadcast 不等待；wasMessageAccepted 使用 userMessage.clientId。只读检查安装包，未执行真实消息发送。

## 验证

- `python3 -m unittest discover -s tests -p 'test_*.py'`：529 项，1 项可选跳过，其余通过。包含原生回执、无 turnId 恢复、断线幂等、队列冲突/持久化、停止/审批、撤权、跨账号与工作区隔离。
- `node --test tests/test_*.js`：43 项通过，包括云端 JSON 403、非 JSON 413、502 丢回执及请求 ID 生命周期。
- `swift test --package-path iOS`：110 项通过。
- `python3 tests/run_ios_navigation_regression.py 4E4AA14D-FBDE-4E94-806C-8585787CB27C alignment`：passed=true；覆盖无历史成功清卡片、失败卡片更新、未知请求后停止、创建等待真实 ID、侧会话及只读。查看了 `.runtime/alignment-regression/alignment.png`；全部请求由夹具拦截。
- iPhoneOS arm64 unsigned xcodebuild（既有缓存依赖，`-skipPackageUpdates`）：BUILD SUCCEEDED。未安装真机、未做生产部署。
- 独立审查发现并修复队列并发覆盖和云端 HTTP status 丢失，随后复核原始代码与测试证据；最终独立结论：接受，无剩余阻断缺陷（适用于隔离工作树，合入后另核验交集）。

## 恢复与集成

组合审查发现文本归一化会改变既有未决请求的 fingerprint；现保留原始 wire prompt 计算幂等标识，投递文本仍按当前契约规范化。新增原始空白与同 ID 重试回归通过。

没有数据库 schema 迁移，没有自动重发未知请求。若需回滚，回退本次代码提交并保留已有 Journal 与客户端请求 ID；不可删除记录来重发。合入前备份并保留 main 上另一会话的全部未提交改动，仅提交本任务差异；完成三方差异预检及集成回归后再交还 legacy 清理。
