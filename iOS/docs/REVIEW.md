# iOS 独立审查结论

## 结论

**有条件接受。** 当前源码满足本轮原生 Swift 6、SwiftUI、iOS 17+ 的实现范围；未发现仍会阻断构建、破坏设备/绑定隔离、绕过服务端权限、错误重放写入或错误绑定原生审批的缺陷。R2 的源码、协议和恢复门禁通过；真机交互与真实链路仍是部分验证，因此不能标记为完整端到端验收。

## 独立性与审查依据

审查者直接读取原始目标、`design/mobile/HANDOFF.md`、`docs/WORKSPACE.md`、`docs/MULTI_CLOUD.md`、服务端 `console.py`、`api.py`、`realtime.py`、`remote_scope.py`、`operations.py`、`images.py` 及全部 iOS 源码和测试。审查未依赖实施者的完成自述，并实际要求修正阻断问题；除本记录外未修改实现。

重点核对结果：

- HTTPS 控制台地址、Origin、内存 Cookie、禁止重定向和 401 失效处理沿用云端控制台契约；登录秘密不落盘。
- 设备、项目、线程和绑定范围在切换时由 epoch、设备 ID 和 scoped 草稿键隔离；旧响应不能写入新设备状态。
- 项目统计、运行态、发送/补充/排队以及最终权限裁决仍由服务端持有，客户端没有建立第二套业务状态机。
- 写入使用持久 requestId 和正文哈希；`preparing` 只表示服务端已登记，编号保留到 jobs 出现已接受证据。`failed`/`uncertain` 需要用户核对；不自动重发。
- 命令、文件、权限、问题及 MCP 回应同时绑定原生 request ID、fingerprint 和当前请求集合；权限子集由服务端再次校验。
- 已读只在当前线程前台展示后按捕获的 sequence 推进；不会把阅读当作审批完成。
- 当前仅支持已确认空闲的既有会话附图；新建、编辑和运行中附图保持禁用，模型页面不虚构可用目录。

## 审查中要求并已复核的修改

1. `ConsoleAddress.component` 原先编码 UUID 中的连字符，服务端不会对 API 路径再次解码，导致线程 compose、operations、图片和临时聊天路由失败。现保留 RFC 3986 路径片段中的 `-._~`，并增加 UUID 回归测试。
2. 客户端原先把服务端 202 返回的 `preparing` 误判为失败，导致首次发送、审批和新建无法完成 UI 流程。现将其视为已登记，同时保留 requestId，直到实时 jobs 提供可清理证据。
3. 发送等待期间返回列表会使已发送草稿留在原线程，后续可能使用新 requestId 重复发送。现按捕获的云端/设备/线程键清理已提交且未被继续编辑的文字和图片，并测试跨会话及在途编辑。
4. 持久请求记录解码失败原先会静默生成新编号。现失败关闭写入，提示保留 App 数据并先核对原请求。
5. 项目选择移到 `AppModel`，从聊天返回可恢复进入来源的项目层级；动态角标读取 `/api/activity` 的服务端汇总并单独加上连接申请数。

## 独立运行证据

- `swift test`：8 个 Swift Testing 用例全部通过，覆盖地址与 Cookie、UUID 路径、分页、结构化审批、请求编号跨重启与设备隔离、损坏记录失败关闭、提交草稿的范围隔离。
- `xcodebuild -project ConnectNow.xcodeproj -target ConnectNow -configuration Debug -sdk iphoneos CODE_SIGNING_ALLOWED=NO build`：最终源码构建成功。
- 最终产物 `build/Debug-iphoneos/ConnectNow.app` 已检查：Mach-O arm64，`MinimumOSVersion` 为 17.0，Bundle Identifier 为 `com.hanzeal.connectnow`。
- `git diff --check -- iOS`：未发现空白错误。

## 未验收边界与恢复

- 未签名安装到 iPhone；设计还原、动态字体、VoiceOver、触控、键盘、安全区、滚动和前后台往返需要真机验收。
- 未连接真实 HTTPS 云端、真实设备桥接和 Codex 会话执行发送或审批；URLProtocol 与源码检查不能替代该往返。
- APNs、系统/锁屏通知、动态模型目录、新建/编辑/运行中附图缺少后端权威能力，本轮未宣称完成。
- 本轮未提交、推送、部署或修改生产数据。源码恢复边界是新增的 `iOS` 目录；客户端回滚不能撤销已由原生 Codex 接收的操作，结果不确定时必须保留 App 数据和原 requestId，在 Codex App 核对后处理。

完成条件：用户配置有效签名后，在目标 iPhone 上完成主要页面与键盘/安全区验收，并使用测试云端执行一次登录、设备切换、读取、发送、审批拒绝及后台恢复往返。完成前，本交付保持“有条件接受”。
