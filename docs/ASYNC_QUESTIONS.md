# 非阻塞异步提问

识别 Codex 原生 `agentMessage.delivery == "async"`，从 `questions[].title/options` 生成卡片；无结构化 questions 时提供该消息的自由文本回答。普通 Markdown 列表不会生成交互。

问题标识与安装的 Codex 实现一致：有 questions 时为 JSON 字符串 `["request_user_input_async", nativeItemId, questionIndex]`，否则为 nativeItemId。依据本机 ChatGPT.app 的 Codex 包内原生消息转换、回答解析与 30000ms 自动收起逻辑核验。

Web、移动 Web、iOS 自动展示问题卡片。30 秒未操作后仅显示“回答问题”入口；点击入口重新打开，选项、自填、关闭与跳过均不暂停任务。开始编辑会取消自动收起。同一已提交答案不会再次发送；可修改后重新提交。

提交使用已有 compose 通道，正文按原生协议编码：

```text
<send_user_message_question_reply>
[{"questionItemId":"...","question":"...","answer":"..."}]
</send_user_message_question_reply>
```

沿用已有远程控制授权、请求幂等和未知结果保护。运行中交给原生 steer，空闲时正常发送；若任务另有真正的阻塞请求，沿用原生等待队列。异步问题本身不写入 pendingRequests，不改变运行状态。用户主输入框的草稿和图片不会被问题回答覆盖。

历史投影识别已接受的 steeringUserMessage / userMessage 回答并关联原问题；拒绝的补充不算已回答。页面显示可读的问题与答案，原生数据保持不变。

## 验证

- Python 全套 163 项通过；新增补充消息幂等专项后，异步提问专项共 5 项通过。覆盖非阻塞状态、普通列表排除、原生 ID、答案回读、拒绝的补充、后续轮次回答、只读拒绝和仅一次 steer。
- Node 现有客户端逻辑测试通过，JavaScript 语法及差异检查通过。
- iOS 完整未签名 App 编译通过。
- 浏览器固定数据验证：自动显示卡片，30 秒无操作收起；点击入口重新打开、选项及自填回答的关联回复提交。此验证使用本地回调，不向真实 Codex 任务发送测试回答。
- iOS 真机手势/键盘、真实云端到 Codex 的回答往返尚未实测。未提交、推送、部署。

恢复：恢复本次问题投影与客户端展示代码，无数据库变更或新增外部依赖。此前附件功能的独立审查额度阻塞未被本次测试替代。
