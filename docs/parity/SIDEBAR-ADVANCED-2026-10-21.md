# 侧栏与高级面板验证

范围为 R1 局部交互：验证侧栏左滑，修正高级模型面板，相关测试通过后覆盖安装用户手机。用户明确授权安装；不使用重置卡，不清空应用或设备数据。

## 结论与变更

- 侧栏：用户在隔离模拟器实际左滑，确认可以关闭。测试副本记录到原生产手势完整的 began / changed / ended，最后平移 -247.33 点。保留原生产手势实现；撤回了没有运行证据支持的窗口挂载尝试。
- 自动化拖动限制：相同 CUA 拖动在侧栏只记录到 touch receive，没有 begin；对系统原生 sheet 的拖动也无效。因此该现象不能认定为侧栏代码故障。真人输入及事件记录补足验证。
- 高级面板：快捷选择器只负责原位浮层，由页面统一呈现高级 sheet。半屏高度、拖动条和背景修饰符仅应用于高级内容，不再由快捷浮层影响外层 fullScreenCover。新建和现有会话共用此呈现原则，设置保存仍使用原权威路径与权限检查。
- 辅助功能：视图层级中高级标题、取消、完成及模型值均存在，未被 accessibilityElementsHidden 隐藏；CUA 的 AX 读取仍停在下层，但原生模型菜单可读取。不能把 CUA 的读取限制等同于已完成 VoiceOver 实测。

## 证据

`.runtime/sidebar-advanced-2026-10-21/` 保留实际手势事件、视图层级、构建日志及测试结果。临时诊断仅注入隔离测试副本，已从测试运行器中移除；真机包使用正式 App 入口和源码。

## 验收与安装

最终 home 10/10、conversationvisual 33/33 均通过，差异检查通过。真机 Debug 构建与签名校验通过，已于 2026-10-21 13:24（Asia/Shanghai）覆盖安装到用户 iPhone 16 Pro Max，bundle ID 保持 `com.hanzeal.carryon`，版本 1.0 build 5。安装回执见 `install-result.json`，产物哈希和源文件哈希见 `device-manifest.json`。用户在手机进行最终外观抽查。

真机启动核查通过：原登录状态、项目与既有新建草稿仍可见；高级面板打开、真实模型目录加载、取消返回正常，未修改模型配置或发送消息。截图为证据目录中的 `iphone-home-installed.png`、`iphone-advanced-installed.png`、`iphone-models-installed.png`。已返回首页供用户查看。
