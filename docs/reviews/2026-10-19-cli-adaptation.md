# Codex CLI 正式适配验收

任务：会话发现、双向实时同步、审批和断线恢复；手机端走真实 Console/Connector 通道。
风险 R2：公共运行时协议与审批路径。用户明确授权本地实现、隔离验证；未授权发布、推送或普通 checkout 提交。
起点：main / 49729a469bf9ae7f7d9a2b9283735886d8bf3c3a；在原 checkout 工作，未创建 worktree。

## 边界与恢复

- CLI 只附加外部 Unix WebSocket daemon，桌面保留 IPC/owner，独立工作区拥有 stdio 子进程。
- RPC、事件投影、原生审批与能力契约由 codex_protocol 共享，不复制业务真相。
- fork/unarchive 使用运行时 peer 工厂，CLI 辅助连接仍附加同一 daemon。CLI 不提供临时聊天，避免把断开连接误当作销毁后台任务。
- CLI 工作区注册保持已有 home/配置/登录不变，不把用户 home 当独立 runtime 目录。
- 断线保存需要重新订阅的 thread id，重新建立连接并补读历史/待审批。失败的订阅会重试。
- 已投递写入的结果未知时保留 uncertain，不自动重发；审批需要原生 resolved 确认。
- 本次无数据迁移、生产依赖或部署。恢复可停止/移除新增 CLI 工作区登记（保留数据），恢复旧代码；外部 daemon 和原会话由 Codex 自行管理。

## 独立审查

首轮发现辅助操作错误启动 AppServer、恢复失败不再重试、临时聊天关闭语义与外部 daemon 不符，均已修复并补专项测试。
复审独立检查源码、手机证据及源码哈希，并运行 24 项相关测试通过。
最终复审：无剩余代码阻断项。审查者核对原始 schema，撤回要求添加不受支持的 resume 参数；读状态与订阅之间的原生竞态作为已知限制记录，活动 goal 自动继续尚未在本次实测，不视为已证实缺陷。最终手机复跑的 25 项检查全通过，121 个源码哈希均与当前文件一致。专用模拟器已关闭，临时 daemon 已停止。

## 验证

- Python 全量：877 项，成功，109 项显式原生集成测试按默认开关跳过；日志 `/tmp/carryon-final-regression.log`。
- 最终后端标签调整后定向回归：24 项通过；日志 `/tmp/carryon-cli-last-targeted.log`。
- Web：97 项通过；Swift：151 项通过。日志分别为 `/tmp/carryon-node-final.log`、`/tmp/carryon-swift-final.log`。
- 原生协议：使用生产 CliClient（仅增加帧捕获），真实 Codex CLI 0.155.1 PTY 与独立 Unix app-server，9 项通过。覆盖双向完成前 delta、相同会话订阅、双向审批与过期重复审批不重复执行、任一端及全端断开后后台继续执行、待审批重连恢复。证据 `.runtime/cli-protocol-probe/production-final/report.json`。
- 手机：真实 iOS AppModel → HTTPS/WSS Console → CloudConnector → CLI 托管 daemon → 普通 Codex CLI，25 项通过。无直接调用 snapshot 帮助订阅。包括发现、双向流、双向审批、自动重连、待审批恢复、CLI 退出继续运行、手机重新连接恢复历史。证据 `.runtime/cli-integration/result.json`，记录源码 SHA-256；截图 `cli-stream.png`、`cli-approval.png`、`cli-recovered.png`。
- iOS 专用集成 App 构建成功；使用隔离模拟器 `CarryOn-CLI-Integration` 和临时 CODEX_HOME、工作目录、证书、服务；没有读取真实账号凭据或创建桌面端连接。
- Python wheel 在干净临时源码目录构建，通过解包后的真实模块导入与资源检查，确认迁移前的 app_server 模块未混入。产物与 SHA-256 见 `.runtime/cli-package-clean/result.json`。

复现：

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_*.js
swift test --package-path iOS
python3 tests/run_cli_protocol_probe.py --output .runtime/cli-protocol-probe/new-run
python3 tests/run_cli_mobile_integration.py --simulator <专用 iPhone 模拟器 UUID> --output .runtime/cli-integration-new
```

协议探针输出目录必须不存在；手机脚本需要 macOS、Xcode、已启动的专用模拟器和 Codex CLI 0.155.1。脚本自行清理临时 daemon/CLI/服务，不修改个人 CODEX_HOME。

## 已知边界

- 手机验证使用 iPhone 模拟器及本地确定性 Responses fixture，覆盖真实 App、网络与原生协议；未验证实体手机、跨公网部署和真实模型推理。
- 任务继续运行依赖外部 daemon 存活。CarryOn 不安装、启动或停止它；daemon 自身崩溃/退出的任务恢复由 Codex 负责。
- 原生 `thread/started` 是全局发现通知，不代表当前客户端已订阅。本次修复该差异，手机验证会等待完成前流片段以防止只验证到最终历史。
- 恢复不会重发用户写入，但 `thread/resume` 本身具有原生加载语义。先读到 `notLoaded` 时只读持久历史；先读到 `active/idle` 后外部并发卸载时，恢复可能加载并继续活动 goal。0.155.1 `ThreadResumeParams` 无 `deferGoalContinuation`，也无原子 subscribe-if-loaded 接口，不能保证该跨客户端竞态下恢复绝对无执行副作用。
- CLI 临时聊天未开放；不影响本次会话发现、同步、审批和恢复目标。

代码保留在原 main checkout，未提交、推送、部署；无工作区数据迁移。
