# 动态详情已有内容优先展示

范围：iOS 动态详情首次打开、重复打开、后台刷新与迟到响应。风险 R1；复用现有显示缓存及请求校验，不改变服务端运行状态、审批、问题回答或已读契约。

动态详情有摘要或匹配当前轮次与类型的缓存时直接显示内容，后台仍读取最新历史；只有没有可展示内容时显示加载提示。成功响应写入现有会话显示缓存，关闭弹窗释放活动快照但保留缓存；刷新失败保留内容并提供重试。缓存仅用于展示，通过现有 access/readiness 字段禁用操作，最新响应确认后恢复原生操作条件。新轮次和旧的未完成缓存不能遮盖当前完成摘要。请求版本与弹窗生命周期阻止关闭或重新打开后的迟到响应覆盖新内容。

验证：

- `python3 tests/run_ios_navigation_regression.py 4E4AA14D-FBDE-4E94-806C-8585787CB27C activity`：隔离模拟器 App 构建与 15 项检查通过，覆盖摘要、空内容、缓存重开、刷新失败、缓存操作门禁、新轮次、未完成缓存、迟到响应及工作区隔离。所有 HTTP 请求由夹具截获，没有投递真实任务。
- 已查看 `.runtime/activity-regression/activity.png`：摘要直接显示，没有加载提示。
- `swift test --package-path iOS`：118 项 Swift Testing 与 4 项 XCTest 通过。
- 正式 Debug 真机签名构建及 `codesign --verify --deep --strict` 通过；已检查 IPA 内版本、可执行文件及 SHA-256，正式 App 不含测试通知钩子。

沿用本次对话更新手机安装包的授权，2026-09-30 18:37（Asia/Shanghai）已在已连接的 iPhone 16 Pro Max 上安装 CarryOn 1.0（build 5）；设备安装清单确认 build 5。自动启动被 iOS 拒绝，原因为手机锁屏；解锁后可手动打开。本次没有后端变更，未再次重启服务。手机上的实际视觉与手动交互仍由用户验收，未发布到 TestFlight 或 App Store。

产物：`.runtime/ios-activity-device/CarryOn-1.0-build5.ipa`；构建、安装、启动及校验记录在同目录。恢复副本：`.runtime/source-backups/2026-09-30-activity-loading/`；相对任务开始时的差异：`.runtime/activity-regression/changes.patch`。共享 main 工作区存在其他修改，恢复时必须选择性撤销，不能整文件覆盖；此前 build 4 的 IPA 与 Payload 保留。本次没有 worktree、提交或推送。
