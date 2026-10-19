# 一个工作区多个连接：实施与验证

## 目标与范围

同机同 Codex Home 的桌面端、CLI 在手机归入一个工作区，各连接分别显示在线状态并可切换。
官方默认仅共享保存历史，因此运行状态、请求、审批、缓存、草稿和权限继续按连接隔离。
连接适配器、公共协议组件及 app-server 的结构边界不变；不切换官方客户端的运行模式。

基线：`main` / `49729a469bf9ae7f7d9a2b9283735886d8bf3c3a`，直接使用原工作目录，未创建 worktree。
上一轮 CLI 适配及其他未提交界面修改均保留；本轮未提交、推送或部署。
风险 R2：本机登记模型、云端目录与 iOS 选择状态；实施由用户明确授权，部署另行授权。

## 实现边界

- `carryon/workspaces/connections.py` 为本机登记分配稳定的工作区 ID/名称，生成不含本地路径的展示描述。
- 启动/登记在已有目录锁内升级旧记录；不改变服务 ID、token、端口、Home、socket 或 Journal。
  先 CLI 后桌面端保留分组；desktop Home 变化时拆分工作区身份。
- 经过设备 token 认证的 hello 发布元数据；Console 持久保存并按绑定 owner 派生公共分组 ID。
  会话目录仍逐 device 检查权限，分组不影响写路由、审批或权限判断。
- iOS `WorkspaceGroup` 仅投影目录；工作区弹层分组列出连接，首页可切换当前组内来源。
  切换复用原 scope/epoch 清理与恢复流程；选择来源后重新读取，绝不自动接管另一端运行中的任务。
- 移除仍针对单个 device ID。手机前台只订阅当前连接；电脑上的多个连接可同时运行。
- 项目目录、原生项目归属和会话历史不迁移、不复制。缺少分组数据的旧连接单独显示。

## 验证

- Swift：`swift test --package-path iOS`，151 项 Swift Testing + 10 项 XCTest 通过。
  新增覆盖同组独立连接 ID、旧版同名不合并、移除后保留另一连接。
- Node：`node --test tests/test_*.js`，97 项通过。
- Python：889 项测试运行完成，780 项通过、109 项因原生集成开关跳过，无失败。
  完整结果见 `/tmp/carryon-group-python.log`；聚焦测试覆盖注册迁移、分组拆分、握手认证、
  离线目录持久化、同组权限不继承以及单连接撤销隔离。
- 手机：`python3 tests/run_cli_mobile_integration.py --simulator 52703D0F-CD14-4138-891D-F51A9CFE93A5 --output .runtime/workspace-connections --workspace-connections`。
  测试包构建成功，35 项手机检查通过；CLI 使用真实 Codex daemon 与普通 TUI，HTTPS/WSS 使用测试证书。
  覆盖两连接同组、相同 thread ID 下历史隔离、流式输出中切换后任务继续、审批来源隔离、
  旧审批目标拒绝误投、切回恢复原审批、CLI/手机断线继续执行及重连恢复。
- 手机结果：`.runtime/workspace-connections/result.json`；界面证据：`cli-workspace-connections.png`。
  已检查截图；同一工作区中两个连接均显示在线且仅 CLI 标为当前连接。
  `source-verification.json` 核对 122 个 Python/测试入口文件与 107 个实际编译 Swift 文件均对应当前源码。

边界：桌面通道使用 IPC 协议测试替身；没有将其描述为真实 Codex 桌面端的完整手机验收。
模型响应来自本地确定性服务；未覆盖物理手机、公网或真实模型推理。
测试使用独立 Codex Home/测试账号/专用模拟器，结束后关闭测试进程和模拟器。

## 独立审查与恢复

独立审查访问原始需求和源代码，发现并要求修复“更换 Home 后旧分组 ID 仍复用”的 P2。
修复后审查者独立运行 19 项聚焦测试通过，结论无剩余阻断项。

生效需要更新本机服务、Console 和 iOS，并重启各本机连接发布新元数据；本轮未执行部署。
回退保留 `services.json`、Console `devices.json`、各连接目录与 Journal；旧程序可忽略新增字段。
不删除数据、不重新生成凭证、不自动重放未知写入。正式环境/真机验收仍需后续发布步骤。
