# 已有侧边聊天对话

用户范围：已有临时侧边聊天继续文字对话、追加要求与停止；不新建、不提交、不部署、不安装真机、不发送真实业务测试消息。

风险 R2：共享投递路径和父子身份核验。权威为登记关系及原生实时快照的 id、ephemeral、sideConversation、forkedFromId；数据库候选不授权写入。

实现：side compose/operations 复用 Bridge.compose/submit、operations.dispatch、原生 owner、远程授权、请求幂等账本。sideParentId 由已校验路由写入任务，投递前再次核对关系。空闲 start、执行中 steer、等待时 queue。侧边聊天不走主会话的持久行查找。

客户端：iOS 复用 CarryOnChatComposer 与 ConversationTimelineRow、AppModel.write 和同一 WS 的 sideHistory；Web 复用 requestJob 与 Timeline。侧边草稿按设备/父/子隔离，切换/断线先禁写，已提交请求的迟到结果不清除其他会话的草稿。客户端目前提供文字输入与停止，资源预览保持原路径，其他原生 operations 仅提供后台接口。

验证：9 项 side tests；全量 Python 363 项（1 项既有 skip），38 项 Node，Swift Testing 41 项及 XCTest 4 项通过。桌面 1280 与手机 390 的 Playwright 实渲染测试通过，覆盖发送目标、停止、主侧草稿隔离、侧间切换、迟到响应、断线、桥接关闭。截图 /tmp/carryon-side-dialogue-ui/；GPT-5.6 Sol（Erdos，01a09ef3-0b65-7942-91da-28351b759025）完成原始差异独立审查，最终 Accept，R2 门禁通过。审查者独立复跑 side 9 项、Node 38 项、Swift 42+4 项和 Web 桌面/手机夹具。

构建：原工作区构建被并行修改的 ImageLightbox.swift:43 Swift concurrency 错误阻断；在 /tmp/carryon-side-dialogue-validation/iOS 复制当前源码，仅将该无关文件替换为 HEAD 版本后构建通过，原文件未修改。最终新增共用发送状态组件已纳入隔离构建并通过，日志 /tmp/carryon-side-dialogue-isolated-final.log。该结果验证捕获时的源码；之后并行任务对 AppModel 新增 openLinkedThread 的改动不属于本次构建结论。

恢复：撤回本次客户端/API/共享投递的 side 参数变更即可，无数据库迁移或新增依赖。保持原生会话、草稿和请求账本；此前创建探测文件不属于本次功能。真实 owner 投递和真机尚未验收。
