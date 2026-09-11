# ConnectNow iOS

原生 iPhone 客户端：Swift 6、SwiftUI、iOS 17+。视觉与交互依据 [design/mobile](../design/mobile/README.md)。不包含第三方生产依赖。

## 打开与运行

用 Xcode 打开 `ConnectNow.xcodeproj`，选择 `ConnectNow` scheme。在 Signing & Capabilities 选择自己的开发团队，核对 Bundle Identifier（当前为 `com.hanzeal.connectnow`），再选择已连接且开启开发者模式的 iPhone 运行。Bundle Identifier 的账号归属尚未验证，可改为自己账号下的唯一标识。

无需安装模拟器。当前本机 Xcode 26.6、Swift 6.3.3 已完成未签名真机目标构建；没有有效签名证书，因此尚未安装到手机、完成真机视觉/键盘/网络验收。

```sh
# 在仓库根目录运行：原生协议与请求状态测试（macOS 主机）
swift test --package-path iOS

# 完整 .app 构建，不签名、不安装
xcodebuild -project iOS/ConnectNow.xcodeproj -target ConnectNow \
  -configuration Debug -sdk iphoneos ARCHS=arm64 CODE_SIGNING_ALLOWED=NO \
  SYMROOT="$PWD/iOS/.build/xcode-products" \
  OBJROOT="$PWD/iOS/.build/xcode-intermediates" build

# 仅检查 iOS 17 目标编译与链接，不替代 .app 构建/签名
./iOS/scripts/compile-device.sh
```

产物位于 `iOS/.build/xcode-products/Debug-iphoneos/ConnectNow.app`。这不是可分发的签名安装包。本机 scheme + generic destination 路径提示 iOS 26.5 平台组件缺失；上面的 target 构建已实际通过，不将可列出 SDK 等同于所有 Xcode 运行能力就绪。

## 当前实现

- HTTPS 云端登录、设备目录、工作区切换与退出；独立内存 Cookie 会话，带正确 Origin，拒绝重定向。登录凭证不落盘，App 进程重启需重新登录。若后续增加持久登录，认证秘密使用 Keychain，不使用 UserDefaults。
- 项目汇总与分页、项目内搜索及状态筛选、待处理动态、独立连接申请分组。
- 云端 WebSocket 实时会话、消息和执行详情、原生队列展示、进入后台取消订阅与前台恢复。网络恢复仅重建读取订阅，不重放写入。
- 原生多行输入、现有空闲会话附图（最多三张，每张压缩至 200 KB）、发送/停止、文本与附件按云端/设备/会话保留内存草稿。
- 命令/文件/权限审批、问题文本回答及 MCP 回应，沿用原生 request ID 与 fingerprint，扩大权限的交互先展示确认。
- 新建会话与控制会话选择、编辑最后一轮、压缩、高级 JSON 设置、临时聊天只读、元数据与请求记录。
- 服务端四类通知偏好、读游标。阅读不会替代审批，未读不会逐 token 增长。
- 请求编号与正文哈希持久化；未知结果保留原编号，变更正文前要求核对原请求。持久记录损坏时暂停写入，禁止静默生成新编号。

## 权威边界

[WORKSPACE.md](../docs/WORKSPACE.md) 和 [MULTI_CLOUD.md](../docs/MULTI_CLOUD.md) 是业务契约。云端通过 HTTPS request 代理提交操作，通过 `/console/devices/{deviceId}/ws` 推送会话更新；客户端不直接访问 Mac IPC。WebSocket 使用同一登录 Cookie 与 Origin，进入后台关闭，前台及断线恢复时重建订阅；45 秒无消息时重连，不重放写入。

SwiftUI View 负责展示，Observation 页面状态管理前台生命周期；`ConnectNowCore` 负责 Codable 数据边界、URLSession、请求幂等编号及草稿提交规则。Swift Package 让这些纯逻辑在 macOS 上验证，iPhone App target 复用同一份代码。

发送/补充/排队、原生状态、项目统计和权限最终由服务端裁决。缺少授权或状态未知时 UI 不提供控制。服务端是同一绑定共享读游标/偏好的模型，不提供独立手机账号。

## 尚未完成的验收与平台能力

- APNs 安装注册、推送投递、失效 Token 清理和通知点击恢复需要后端与 Apple 开发者配置；当前没有系统/锁屏推送，不申请虚假的通知权限。
- 动态模型目录及新建/编辑/运行中附图尚无后端可用契约。模型入口展示当前值，未开放的图片能力禁用。
- 当前为调试开发工程，尚未制作正式 App 图标、上架素材、签名归档或 TestFlight 发布。
- 真机上的样式还原、动态字体、键盘、安全区、滚动、后台恢复与真实云端完整链路尚待签名后验收；编译通过不代表这些验收通过。

风险、独立审查和验证证据见 [开发验收记录](docs/DELIVERY.md)。
