# 控制台会话 WebSocket 验证

2026-09-12，本地开发环境。变更范围：云端控制台的 Web、移动 Web、iOS 会话订阅由 HTTP 长轮询改为 WebSocket；本机设备连接、实时投影、提交幂等与控制授权仍使用现有实现。目录查询、连接申请刷新、登录、提交和附件读取保留 HTTP。

## 已验证

- `PYTHONPATH=tests python3 -m unittest test_console_socket test_console test_cloud test_realtime`：37 项通过。包含真实 socket 握手、Origin/Cookie/设备范围校验、查询参数拒绝、初始快照、事件即时推送、桥接关闭推送、非法订阅、禁止 socket 写操作、注销/过期/设备撤销、断线重连及订阅回收。
- `node --test tests/test_console_client.js tests/test_client.js tests/test_device_removal.js`：21 项通过。包含订阅去重、旧连接迟到帧隔离、修订号去重、认证失效、设备移除期间停止重连及既有提交幂等。
- `swift test --package-path iOS`：8 项通过，包含部署前缀对应的 WSS 地址与既有 Cookie/提交记录行为。
- `xcodebuild -project iOS/ConnectNow.xcodeproj -target ConnectNow -configuration Debug -sdk iphoneos CODE_SIGNING_ALLOWED=NO CONFIGURATION_BUILD_DIR=/tmp/connectnow-ws-ios OBJROOT=/tmp/connectnow-ws-objects build`：成功。
- 本地浏览器实际登录并显示“只读连接”；使用测试云端与测试设备，无真实 Codex 写入。
- `git diff --check`：通过。

## 验证限制与发布门禁

浏览器会话目录显示“接口不存在”：当前 `connectnow/api.py` 的项目/动态工作区路由仅在 `not remote` 时分发，远程请求随后被白名单拒绝。此既有路由问题不属于本次 WS 修改，但阻碍完整浏览器会话操作验收。不要将此次传输测试当作提交到原生 Codex 再返回 UI 的时延验收。

iOS 尚未做真机网络切换、后台恢复、TLS 代理与持续连接验证。未部署；客户端需要与新增 WS 路由的云端版本一起发布。

本次涉及公共实时接口，按 R2 保留独立审查门禁。侧边会话禁止使用子代理，本次仅完成实施自检，没有独立审查结论。发布前需独立审查者基于协议、实现和上述测试形成接受或要求修改的结论，并完成真机与真实会话验收；不能以测试通过替代此门禁。

## 恢复

没有数据迁移及新增依赖。发布异常时，协调恢复本次 WS 修改前的服务端与 Web/iOS 客户端版本；原 HTTP streams 接口仍保留。当前工作区有其他并行修改，不可通过整文件恢复或清空工作区实施回退。禁止自动重放提交请求。
