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

当前入口已接入统一隔离运行器，包含千条较早历史和稳定消息ID的CADisplayLink采样：

```sh
CARRYON_SWIFT_PACKAGES=iOS/.build/SourcePackages python3 tests/run_ios_navigation_regression.py <booted-test-simulator-id> timeline
```

结果为 `.runtime/timeline-regression/result.json`，逐帧记录为 `samples.json`，实际渲染为 `timeline.png`。验收比较发送前每个既有消息的基线高度及呈现高度（容差1pt），新增发送提示行的展开动画单独保留观测；不能用所有行的动画数量推断旧正文压缩。历史记录中的零动画结果只适用于当时短历史fixture，不代表所有当前状态。2026-10-02千条历史复核观察到新提示行与位置动画，但既有正文高度保持一致；Debug模拟器帧间隔不能代替真机性能验收。

恢复：撤回本次 ConversationView 的事务/快照修改及 ChatAppearance 的 disclosure 组件和对应调用；保留这些文件中原有并发修改。
