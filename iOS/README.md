# CarryOn iOS

原生 iPhone 客户端：Swift 6、SwiftUI、iOS 17+。视觉与交互依据 [design/mobile](../design/mobile/README.md)。聊天界面使用 Exyte Chat，Markdown 与代码高亮使用 MarkdownUI 和 Highlightr。详见 [Markdown 与聊天界面](docs/MARKDOWN-CHAT.md)。

## 打开与运行

用 Xcode 打开 `CarryOn.xcodeproj`，选择 `CarryOn` scheme。在 Signing & Capabilities 选择自己的开发团队，核对 Bundle Identifier（当前为 `com.hanzeal.carryon`），再选择已连接且开启开发者模式的 iPhone 运行。其他开发团队需使用自己账号下的 Bundle Identifier 和描述文件。

Run 使用 Debug：默认不加载推送及 Associated Domains 签名权限，可使用免费 Personal Team 真机调试；仍需保留自动签名，并在设备上信任开发者。此配置不支持远程推送及关联域名密码共享。Archive 使用 Release：启用这两项权限，发布前需选择付费开发团队及匹配的描述文件。免费账号安装的开发版本通常有效期为 7 天，过期后需重新构建安装。

2026-09-14，本机 Xcode 26.6、Swift 6.3.3 已完成 iPhone 16 Pro Max 的开发签名构建（1.0 build 2），并校验 GiphyUISDK 框架嵌入。真机安装结果与交互验收应分别记录，签名构建不代表完整端到端验收。

```sh
# 在仓库根目录运行：原生协议与请求状态测试（macOS 主机）
swift test --package-path iOS

# 完整 .app 构建，不签名、不安装
xcodebuild -project iOS/CarryOn.xcodeproj -target CarryOn \
  -configuration Debug -sdk iphoneos ARCHS=arm64 CODE_SIGNING_ALLOWED=NO \
  SYMROOT="$PWD/iOS/.build/xcode-products" \
  OBJROOT="$PWD/iOS/.build/xcode-intermediates" build

# 通过 Xcode 检查 App 与 Swift Package 资源，不签名、不安装
./iOS/scripts/compile-device.sh
```

产物位于 `iOS/.build/xcode-products/Debug-iphoneos/CarryOn.app`。上述命令生成未签名检查包；需要真机安装时，用自己的团队配置选择实际设备并启用签名。当前正式工程的模拟器 generic destination 和实际 iPhone destination 均已完成构建。

## 当前实现

- 我的 → CarryOn 版本可检查应用更新，显示 Bundle 版本并区分 TestFlight / App Store 渠道；由 Apple 分发页面完成安装。当前尚未发布更新清单及 Apple 链接，显示“尚未发布可用版本”。配置与发布步骤见 [App 检查更新](../docs/APP_UPDATES.md)。

- 默认账号密码登录，支持扫码后由已登录电脑确认；密码自动填充使用系统密码管理器。HTTPS 云端登录、设备目录、工作区切换与退出；独立 Cookie 会话，带正确 Origin，拒绝重定向。可撤销的会话凭证按云端完整地址保存在本机 Keychain；启动后经服务端验证再恢复登录。登录口令不保存，退出或收到 401 清除保存的会话凭证。
- 首页可切换项目卡片与全部会话视图，选择通过 UserDefaults 持久保存；项目沿用现有排序，会话按原生 updated_at 倒序分页，运行中气泡图标标绿。保留项目汇总、搜索、按通知偏好展示的动态和独立连接申请分组。
- 云端 WebSocket 实时会话、消息和执行详情、原生队列展示、进入后台在系统允许的执行时间内继续同步，到期关闭并在前台重连。网络恢复仅重建读取订阅，不重放写入。
- 原生多行输入、现有会话在空闲、执行和等待状态附图（最多三张，每张压缩至 200 KB）、缩略图与大图预览、逐张删除、发送/停止、文本与附件按云端/设备/会话隔离，原子保存到受保护的本地草稿文件。
- 模型与思考强度菜单读取本机 Codex 缓存目录中的可见模型及支持强度，通过原生 settings 操作从下一轮生效；缺少目录时不提供虚构选项。
- 活动摘要支持 Markdown、长内容省略和按需展开；助手引用附件以绿色文件名打开，避免重复平铺。
- 命令/文件/权限审批、问题文本回答及 MCP 回应，沿用原生 request ID 与 fingerprint，扩大权限的交互先展示确认。
- 新建会话与控制会话选择、编辑最后一轮、压缩、临时聊天只读、会话信息与请求记录。
- 服务端四类通知偏好、读游标。阅读不会替代审批，未读不会逐 token 增长。
- 我的 → 运行日志持久保存最近 200 条问题（时间、工作区、操作和错误）。后台刷新、已读同步和自动重连失败不弹窗；登录失效及用户提交操作失败仍提示，未知提交结果保留原请求编号，不自动重发。日志过滤凭证，单条最多 2048 字符，文件不参与备份；文件损坏时保留原文件并显示存储问题。
- 上次工作区按云端地址保存在 UserDefaults，登录恢复时验证设备仍可访问。
- 请求编号与正文哈希继续沿用既有 UserDefaults 持久化；未知结果保留原编号，变更正文前要求核对原请求。持久记录损坏时暂停写入，禁止静默生成新编号。

## 权威边界

[WORKSPACE.md](../docs/WORKSPACE.md) 和 [MULTI_CLOUD.md](../docs/MULTI_CLOUD.md) 是业务契约。云端通过 HTTPS request 代理提交操作，通过 `/console/devices/{deviceId}/ws` 推送会话更新；客户端不直接访问 Mac IPC。WebSocket 使用同一登录 Cookie 与 Origin，进入后台申请系统允许的最长执行时间，期间保持主会话订阅；短暂切回复用健康连接，后台时间到期则关闭并在前台重建订阅；45 秒无消息时重连，不重放写入。

SwiftUI View 负责展示，Observation 页面状态管理前台生命周期；`CarryOnCore` 负责 Codable 数据边界、URLSession、请求幂等编号及草稿提交规则。Swift Package 让这些纯逻辑在 macOS 上验证，iPhone App target 复用同一份代码。

发送/补充/排队、原生状态、项目统计和权限最终由服务端裁决。缺少授权或状态未知时 UI 不提供控制。同一绑定共享读游标与通知偏好；账号登录及会话有效性由云端验证。

## 尚未完成的验收与平台能力

- APNs 注册、云端投递与点击恢复已加入开发实现，默认未启用推送 entitlement；真实系统通知需要云端密钥及 Apple 签名配置，尚未真机验收。开发与模拟器验证步骤见 [APNs 接入](../docs/APNS.md)。
- 新建会话附图、编辑时增删历史附件尚未开放；普通会话的运行中附图与模型设置已接入现有后端契约。
- 当前为调试开发工程，已包含 App 图标；尚未准备上架素材、分发签名归档或 TestFlight 发布。
- 真机上的样式还原、动态字体、键盘、安全区、滚动、后台恢复与真实云端完整链路仍需逐项验收；编译通过不代表这些验收通过。

风险、独立审查和验证证据见 [开发验收记录](docs/DELIVERY.md)。
