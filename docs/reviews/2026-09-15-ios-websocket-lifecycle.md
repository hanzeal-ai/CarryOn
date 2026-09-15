# iOS WebSocket 生命周期优化

## 范围与影响

R2：连接与实时同步关键状态。保留前台现有 socket 与任务切换重订阅机制；失去活跃状态保存草稿、重置阅读确认、暂停目录轮询，不主动关闭 socket。断线后后台不建立新连接。恢复前台检查 transport 并重新订阅当前选择，使用服务端初始快照补齐状态。主会话和临时聊天内容在断线期间保留。没有修改服务端协议、发送确认契约或账号权限。

退出登录、移除设备、切换工作区仍取消旧任务；epoch 与 socket identity 隔离迟到结果。接收超时在后台暂停，恢复重新计时。健康检查和订阅发送均有 8 秒超时，失败关闭 socket 后由单一读取任务重连。

## 验证

- `swift test --package-path iOS`：73 项 Swift Testing + 4 项 XCTest 通过。
- 新增 socket 注入测试：健康连接后台/恢复不关闭；无响应健康检查关闭；卡住订阅发送关闭，不阻塞后续恢复。
- `python3 -m unittest discover -s tests -p test_console_socket.py`：16 项服务端 socket 集成测试通过。
- Debug generic iOS Simulator xcodebuild：BUILD SUCCEEDED。
- `git diff --check`：通过。
- GPT-5.6 Sol 独立只读审查：Accept，独立复跑 Core 测试通过。审查提出的临时聊天内容丢失、前序订阅发送无界等待均已修复。

日志：`/tmp/carryon-ws-lifecycle-tests.log`、`/tmp/carryon-ws-lifecycle-build.log`、`/tmp/carryon-ws-server-tests.log`。

## 恢复与边界

未提交、推送、部署或安装到设备。本次修改前的 AppModel.swift、ConsoleAPI.swift 备份在 `/tmp/carryon-ws-baseline/`；恢复时只逆向应用本次差异并移除本次测试，不覆盖其他未提交改动。

iOS 系统挂起、网络切换或服务端超时仍可能使连接失效，不能保证后台永久在线。自动验证使用注入 socket 和服务端集成设施，没有模拟真实 iOS 系统挂起；真机切后台/恢复及页面验收由用户完成。
