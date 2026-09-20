# iOS 消息导航条修复

范围 R1：只修改会话左侧导航条的命中计算、手势结束行为和展开状态。保留之前的文字选择等未提交修改。

- 使用现有原生视图 tracker 读取导航内容与可视窗口的实时偏移，按触点选择消息；取消“当前消息索引加拖动位移”的计算。
- 松手提交目标并调用原有导航加载/跳转流程；点击和辅助功能按钮也可直接跳转。
- 长条只在预览交互期间展开，结束或取消后清除预览并恢复短条；当前位置仍以颜色标记。

验证：iPhone 17 Pro / iOS 26.5，现有 `tests/run_ios_navigation_regression.py` 的隔离 150 条消息场景。最终无诊断源码完整构建成功，回归结果 passed=true、activityTargetConsumed=true、scrolledToEarlierMessage=true。验证副本与实际 ConversationView.swift 内容一致。

通过模拟器真实拖动检查：内容偏移 -20 时，触点 y=32.67 命中第 6 条、松手 y=92.67 跳至第 12 条；导航滚动后偏移 -120，相同触点命中第 16 条、松手跳至第 22 条。截图观察目标消息进入可视区域且导航恢复短条。诊断只加入隔离验证副本，正式源码无诊断输出。移除诊断后再次实际拖动，跳转和收起保持有效。

本地证据：`.runtime/navigation-regression/build.log`、`result.json`、`navigation.png`、`gesture-verification.log`。`git diff --check` 通过。未安装到真机，未提交或发布。
