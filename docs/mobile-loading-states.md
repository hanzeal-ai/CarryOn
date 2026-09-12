# 移动端加载与空态

移动网页与 iOS 使用相同的状态规则：

- 首次加载只显示一个加载占位；请求成功且确实无数据后才显示空态。
- 刷新保留已有内容。iOS 下拉刷新由系统提供指示器，网页显示单个紧凑刷新提示。
- 分页仅在已有记录时显示自己的加载状态；更换搜索或工作区清空旧分页信息。
- 加载失败结束加载状态，提供原位重试；已有会话记录继续保留。
- 会话同步占位与运行指示互斥；本地待发送消息不被空态覆盖。

iOS 空态使用 `ContentUnavailableView`，加载使用 `ProgressView`。两端均支持搜索清除、300 ms 搜索防抖、回到最新消息、通知设置加载失败重试及减少动态效果。iOS 图片读取失败可以单独重试。

## 验证

`node --test tests/test_*.js`：36 项通过。

`tests/check_loading_ui.cjs` 在真实 Chromium 中验证首次加载、刷新保留内容、分页重置、搜索清除、会话同步/失败/空态、回到最新消息及通知设置重试。HTTP 和 WebSocket 使用受控响应，不代表真实云端验收。

```sh
PLAYWRIGHT_MODULE=/path/to/playwright \
CARRYON_UI_URL=http://127.0.0.1:8989/example.html \
node tests/check_loading_ui.cjs
```

iOS 已通过设备目标编译和未签名应用构建；原生运行时布局、VoiceOver、键盘及真机手势仍需设备验收。
