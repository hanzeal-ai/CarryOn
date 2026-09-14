# Markdown 与聊天界面

本次范围：iOS 会话列表、新建/编辑会话输入区、Markdown 正文、带语言标签的代码块与只读代码附件预览。风险等级 R2：替换聊天容器及引入运行依赖，涉及发送、草稿和阅读交互；没有改变服务端契约、权限、存储或部署。

## 实现边界

- Exyte Chat 3.3.0 提供聊天列表、滚动到最新消息、消息菜单及输入插槽。CarryOn 的活动、审批、队列和附件保留为自定义消息内容。
- 三个输入入口共用 Exyte 主题与 `CarryOnChatComposer`。上游默认输入组件会在发送回调后立即清空草稿，且没有独立禁用发送的公开接口；自定义输入插槽直接绑定现有草稿，继续由服务端确认结果清理已提交内容，保留失败后的草稿及发送期间新增文字。
- MarkdownUI 2.4.1 负责 GFM 排版；本地附件继续通过已有会话授权接口读取，Markdown 图片不会绕过附件读取流程自动联网。
- Highlightr 2.3.0 在本机通过 JavaScriptCore 生成原生富文本，无 WebView、无远程代码执行。代码块及文件预览共用语言识别和高亮。无语言、未知语言及高亮失败时保留纯文本。
- UTF-8 代码附件按文件名识别，Markdown 文件可切换源码；二进制、非 UTF-8 或未识别类型继续使用 Quick Look。超过 100 KB 的代码文本省略高亮，文件仍可完整阅读、选择和复制；附件大小上限沿用 8 MB。
- 三个直接依赖均使用 MIT 许可证并固定版本；传递依赖已解析并生成工程 Package.resolved；完整构建结果见下方当前记录。Exyte 的 GIF、录音、定位、视频与文档发送功能未启用，因为服务端没有对应发送契约。

## 验收

- 协议及文件类型测试：`swift test --package-path iOS --scratch-path iOS/.build/markdown-tests`。
- 完整构建：`iOS/scripts/compile-device.sh`，通过 Xcode 解析 Swift Package 的资源及链接依赖。
- 人工检查：长 Markdown、表格、嵌套列表、已闭合/流式未闭合代码围栏、语言标签、未知语言、代码横向滚动；代码附件打开/关闭/复制、Markdown 源码切换、二进制回退；历史翻页、阅读标记、活动展开、审批、队列、附图/仅图片发送、运行中停止、发送失败保留草稿、发送期间继续输入、新建/编辑取消确认。

以下为聊天集成初始验证快照，网络阻塞已在后续编译优化中解除；当前完整构建与独立复核见 [修复验证记录](../../docs/reviews/2026-09-12-vibe-coding-fixes.md)。历史结果：

- 当前 Core 测试通过（2 项 XCTest + 21 项 Swift Testing）；覆盖代码扩展名、围栏语言别名、未知语言、二进制/非 UTF-8 回退，以及现有协议/草稿逻辑。
- 使用生产 `MessageMarkdown.swift` 源码和同一 Core 包的独立模拟器验证工程构建通过；iPhone 17 Pro / iOS 26.5 已实际看到 Markdown、Swift/Python 标签与高亮，以及原生 Swift 文件预览。此工程没有替代或修改生产 App 入口。
- 本地证据位于 `iOS/.build/validation/markdown-chat/`：`markdown.png`、`code-file.png`、`renderer-build.log`。
- 整包构建阻塞：Exyte 的 Kingfisher/Giphy 依赖下载停滞，备用读取分别出现 `Recv failure: Operation timed out` 与 `Failed to connect to github.com port 443`。已停止本次挂起的解析进程，没有移除依赖或使用替身绕过验证。
- Exyte 聊天集成、发送/审批/队列完整交互与真机链路尚未通过运行验收；独立审查仍未完成，不能视为完整交付通过。网络恢复后先运行构建脚本，再执行上面的人工检查与独立审查。

## 恢复

发布前可撤销本次聊天/渲染组件和工程依赖变更，恢复之前的原生列表；仅移除本次新增文件及对应依赖，不回退其他并行任务的 AppModel、日志、设置或后端改动。没有数据迁移或生产操作。本次未授权提交、推送或部署。
