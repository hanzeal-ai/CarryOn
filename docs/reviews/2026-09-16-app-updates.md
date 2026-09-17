# iOS 与 Mac App 更新流程

## 范围与契约

用户授权两端接入更新流程，并确认暂无 TestFlight / App Store 链接，先接好流程。风险按 R2 管理：涉及两端共享发布清单与外部下载入口。本次仅修改代码与本地验证，不发布、不提交、不替换已安装应用。

两端共享 `iOS/CarryOn/Core/AppUpdate.swift`：从真实 Bundle 获取版本，读取官方 GitHub Release 的 `app-updates.json`，校验版本、渠道、架构、系统要求和下载地址。iOS 使用 Apple 分发入口；Mac 手动下载安装 DMG。`release/ios-updates.json` 保持空数组，真实链接可用后再填。无发布、最新版本、网络失败与系统不兼容分别呈现。

影响范围：iOS 我的版本入口、Mac 应用菜单及侧栏、共享版本检查实现、发布清单生成与构建脚本、现有桌面验证编译入口、源码包资源清单。不会调用工作区登录接口或写会话数据。沿用项目既有依赖。

## 验证证据

- `swift test --package-path iOS`：96 项通过，日志 `.runtime/app-update-core.log`。
- `python3 -m unittest discover -s tests -p test_app_updates.py -v`：3 项清单生成测试通过。
- iOS 生产源码模拟器构建通过，日志 `.runtime/app-update-ios-build.log`。
- 完整 Mac 生产源码编译通过，日志 `.runtime/app-update-mac-build.log`；命令 `xcrun swiftc -parse-as-library -swift-version 5 -target arm64-apple-macos13.0 desktop/*.swift iOS/CarryOn/Core/AppUpdate.swift -o .runtime/app-update-build/CarryOn`。
- `tests/run_ios_app_update_regression.py`：隔离 Bundle / HTTP fixture，五种状态及真实 Bundle 版本共 6 项通过。首次安装遇到 CoreSimulator 服务退出，重启模拟器后成功安装运行已构建产物。证据 `.runtime/app-update-regression/app-update-result.json`、`app-update-available.png`、`app-update-unpublished.png`。
- `python3 tests/run_app_update_desktop.py`：真实更新视图与隔离 HTTP fixture，五种状态、Bundle 版本、品牌资源与更新说明共 8 项通过。证据 `.runtime/app-update-mac-regression/result.json` 与 `available-window.png`、`unpublished-window.png`。最终证据直接截取真实 NSWindow，等待布局与窗口合成后确认品牌图、更新说明及按钮完整显示。辅助 ImageRenderer 截图不能绘制 ScrollView 内容，不用于更新说明验收。
- 两端有更新及未发布页面已目视检查；测试下载链接仅在 fixture 中，未写入发布配置。
- `git diff --check` 通过。保留工作区已有缓存优化及其他未完成改动。

## 独立审查

由用户授权的 GPT-5.6 Sol 审查 Agent 基于原始文件、基线及验证产物进行审查，可要求修改或拒绝。已修复未发布文案歧义、Swift 5 actor 隔离默认参数编译问题、Mac 图片加载及截图状态问题。最终审查结论 Accept；补充审查也已确认更新说明滚动容器的固定高度及真实窗口截图，Swift 5 全桌面独立 typecheck 再次通过，无剩余阻断项。

## 恢复与剩余验收

本次修改前相关文件快照位于 `.runtime/app-update-baseline/`。撤回实现时按这份基线逐段移除更新入口、共享实现与构建集成，保留其他工作；不对混合工作区执行整体回退。发布后的清单可恢复到已验证的上一份，客户端不会因此降级；Mac 旧包可用于手动恢复，iOS 遵循 Apple 分发限制。数据未迁移。

尚未发布实际更新。真实 Apple 链接、商店安装、签名公证和真机升级保留数据需在正式发布时验收；当前模拟器和本地编译不替代上述验证。发布步骤见 `docs/APP_UPDATES.md`，发布仍须用户另行授权。
