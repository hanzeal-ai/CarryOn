# iOS 主会话发送时的列表闪动

范围：R1，本次只修复 iOS 主会话发送时的布局更新。未修改 IPC、发送接口或第三方依赖。工作区已有侧边聊天及其他并发改动不属于本次修复。

## 原因与实现

ExyteChat 默认将列表差异拆成多次带动画的 UITableView 更新。发送提示直接观察实时 model，可能先于消息列表事务改变单元格高度；随后新增轮次、消息和发送确认再次更新列表，产生反复收缩和展开的观感。

- 串行合并消息投影，跳过无变化的快照；底部同步使用无动画事务，查看历史时使用保持位置的事务。
- 发送提示、队列、原生请求和空态随 status Message 的同一份快照渲染，避免提前改变高度。快照也写入 Message.text，以匹配依赖不比较 customData 的等价判断。
- 活动详情使用公共 ConversationDisclosureGroup；主会话的展开状态由单元格外的 ConversationDisclosureState 持有，随会话视图释放。

## 验证

- 使用实际 ConversationView、独立 iPhone 17 Pro / iOS 26.5 模拟器和本地假数据；未连接账号或向原生会话发送消息。
- 修改前发送阶段记录 70 帧单元格动画；最终发送阶段采样 119 帧，动画帧为 0，result.json 的 passed 为 true。
- 最终截图已检查，旧回复、第 2/3 轮、hello 和追加回复均正常显示。全程 305 帧中，后续新增回复内容增长仍有 28 帧自适应高度动画；本回归断言针对发送阶段，不声称所有流式内容完全没有动画。
- Swift Package：48 个 Swift Testing 测试和 4 个 XCTest 通过。
- 原工作区 iOS Simulator Debug 构建通过，无需替换 ImageLightbox。
- 已有 GPT-5.6 Sol 独立审查 Agent 基于实现及 ExyteChat 原始代码给出 Accept。
- 真机键盘交互、长历史滚动以及手动展开活动详情后发送，仍需使用者抽查；模拟器本地快照不等同于完整真机链路验收。

证据目录：`/tmp/carryon-timeline-regression/`，包含 baseline-samples.json、final-samples.json、final.png、swift-tests.log 和 workspace-snapshot-build.log。

## 重放发送回归

`tests/fixtures/ios_timeline_regression.swift` 是独立模拟器测试入口。复制当前 iOS 目录到临时目录（排除 .build、build、.swiftpm），以该文件替换副本中的 CarryOn/App/CarryOnApp.swift，使用现有 Xcode 项目构建。仅将测试包安装到新建的专用模拟器。

```sh
fixture_root=$(mktemp -d /tmp/carryon-timeline-check.XXXXXX)
rsync -a --exclude=.build --exclude=build --exclude=.swiftpm iOS/ "$fixture_root/iOS/"
cp tests/fixtures/ios_timeline_regression.swift "$fixture_root/iOS/CarryOn/App/CarryOnApp.swift"
xcodebuild -project "$fixture_root/iOS/CarryOn.xcodeproj" -scheme CarryOn -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath "$fixture_root/build" CODE_SIGNING_ALLOWED=NO build
fixture_device=$(xcrun simctl create CarryOn-Timeline-Test com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro com.apple.CoreSimulator.SimRuntime.iOS-26-5)
xcrun simctl boot "$fixture_device"
xcrun simctl bootstatus "$fixture_device" -b
xcrun simctl install "$fixture_device" "$fixture_root/build/Build/Products/Debug-iphonesimulator/CarryOn.app"
xcrun simctl launch "$fixture_device" com.hanzeal.carryon
```

运行约 10 秒后，用 `xcrun simctl get_app_container "$fixture_device" com.hanzeal.carryon data` 获取测试容器，检查 Documents/result.json 的 passed 为 true、animatedSendFrames 为 0。Documents/samples.json 保留逐帧证据。结束后关闭该专用模拟器。

恢复：撤回本次 ConversationView 的事务/快照修改及 ChatAppearance 的 disclosure 组件和对应调用；保留这些文件中原有并发修改。
