# 会话操作界面

当前入口为编辑最后一轮、压缩上下文、临时聊天、会话信息及请求记录。

会话信息按字段展示模型、思考强度、Git 信息和用量，嵌套数据可展开，字段值可以选择复制，不展示 JSON 文档。

临时聊天目录完成发现后，只有一项时直接打开；多项提供选择和切换。内容复用主会话的 `ConversationTimelineRow`，包括活动折叠、Markdown、代码块、图片及代码附件预览。临时聊天保持只读，不提供输入、审批或问题回答；资源通过 `/api/side-chats/{id}/…?parentId=…` 读取，父子关系仍由服务端核验。读取结果在会话/工作区切换或任务取消后丢弃。

本轮为 R1 只读展示调整，没有改变服务端权限或写入契约。恢复时仅撤销对应页面与只读上下文变更，不回退并行任务的草稿、登录、日志或通知改动。

验证：

- `swift test --package-path iOS --scratch-path iOS/.build/markdown-tests`：3 项 XCTest 和 21 项 Swift Testing 通过，包含普通/临时会话资源路由边界检查。
- 生产会话信息视图及 AppModel 在独立模拟器验证工程编译通过，实际检查了模型字段和 Git 信息展开。
- 整包构建仍受 Exyte 传递依赖下载失败阻塞：Kingfisher/Giphy 出现低速超时及 GitHub 443 连接失败。临时聊天的完整运行链路尚未验证，需网络恢复后构建并验证零项、单项、多项选择、切换、失败重试、图片及附件。
- 本地证据：`iOS/.build/validation/conversation-operations/conversation-info.png`、`info-build.log`、`core-tests.log`。没有提交、推送或部署。
