# iOS 初始开发验收记录（历史基线）

> 以下只记录最初 iOS 客户端交付，不代表当前工作区状态。文中的依赖、凭证、范围和测试数量均仅适用于该历史版本。当前编译与认证/推送修复、独立复核及未验收项见 [本轮修复记录](../../docs/reviews/2026-09-12-vibe-coding-fixes.md)。

## 初始任务契约

目标：在 iOS 目录交付可构建的原生客户端，按 design/mobile 样式实现移动端主要页面与现有服务端已支持的操作。使用 Swift 6/SwiftUI、最低 iOS 17，不引入生产依赖。用户已授权本地开发与验证，且明确允许 gpt-5.6-sol 执行独立审查。

风险 R2：客户端接入认证、远程任务与审批，可能触发原生副作用。修改仅在新建 iOS 目录；不修改服务端或其他现有未提交内容，不执行真实远程审批/任务，不提交、推送、部署，不删除生产数据。

验收：Xcode 原生目标编译/链接，协议与重复提交边界测试，原始契约独立审查，真机视觉及真实业务链路验证。最后一项当前受签名阻塞，不能称为完整验收。

## 影响与恢复

- 复用服务端 Cookie、Origin、设备 request 代理和 streams；不改变后台权限、绑定或数据库 schema。
- SwiftUI 页面只投影权威状态；审批使用 nativeRequestId/requestFingerprint，编辑和停止绑定原轮次。
- UserDefaults 仅存非秘密服务器地址及请求编号/哈希；登录令牌仅驻留进程内存。文本与图片草稿按云端/设备/会话隔离。
- 新目录可独立撤回，不影响 Python/网页程序。已发出的原生任务无法通过回滚客户端撤销。
- 如果发生结果不确定，保留 App 数据与请求记录，核对 Codex 后处理；不通过重装 App、删除记录或更换 requestId 重发。

## 已执行验证

2026-09-12，本机 Xcode 26.6（17F113）、Swift 6.3.3、iOS SDK 26.5。

- `xcodebuild -target CarryOn -sdk iphoneos ARCHS=arm64 CODE_SIGNING_ALLOWED=NO ... build`：最终变更后再次完成 Debug .app 构建，BUILD SUCCEEDED。
- `scripts/compile-device.sh`：Swift 6 严格并发模式编译与链接。Mach-O arm64，LC_BUILD_VERSION platform IOS、minos 17.0、sdk 26.5。
- `swift test --package-path iOS`：8 项测试通过；覆盖 HTTPS 地址/Origin/目录前缀、UUID 路径、Cookie 会话与过期、403、结构化审批、分页汇总、未知请求跨重启编号、正文变更禁止新编号、跨设备隔离、在途发送后原草稿清理、持久记录损坏拒绝写入。
- `plutil -lint`：工程 plist 语法通过。
- 已使用浏览器实际查看原型项目首页，并核对设计 HTML/CSS 与交接说明。原型页面不是原生 UI 验收证据。
- 本地构建与测试日志分别保存在 `.build/validation/xcode-build.log` 和 `.build/validation/swift-tests.log`（构建产物目录，不纳入版本控制）。已检查 .app Info.plist 与 Mach-O 的 iPhoneOS、arm64、最低 iOS 17 信息。签名检查确认未签名。

## 独立审查

独立审查者直接读取用户需求、设计、服务端源文件和 iOS 源码，具有要求修改或拒绝权限；不以编译成功替代契约判断。

已反馈并修复：UUID 被过度编码导致路径不匹配；202 preparing 被误判为失败；发送中退出会话导致已发草稿残留，存在重复发送风险。

独立复核结论为**有条件接受**。审查者独立复跑最终 8 项测试和未签名 iPhoneOS 构建均通过；未发现仍阻断构建、隔离、权限/审批绑定或请求幂等的缺陷。完整依据见 [REVIEW.md](REVIEW.md)，真机和真实链路验收仍未完成。

## 未验证和阻塞

- 已发现连接的 iPhone 16 Pro Max，但钥匙串未发现有效签名身份。未签名安装包无法用于正常真机运行，因此未进行手机安装、视觉、触控、键盘、滚动和后台往返验收。
- scheme + generic destination 构建提示平台组件缺失；直接 target 构建可用。未安装模拟器，未改变系统签名/账号设置。
- 未登录真实云端或向真实 Codex 会话发送测试任务/审批。网络单测使用 URLProtocol 夹具，不宣称生产 TLS 与原生 IPC 往返通过。
- APNs 与真实模型目录等依赖后端能力仍未提供，不纳入已完成能力。
- 人类批准/真机验收由用户在签名和实机使用前完成；当前交付处于部分验证状态。
