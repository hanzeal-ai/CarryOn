# iOS 暂停、启动与编辑交互

范围：本次修改 iOS 会话输入框及已有设备操作接口；Web 调用方沿用原接口，新增 resume 不改变既有调用。没有安装、部署、提交或修改线上数据。风险 R2：涉及远程执行与请求状态收敛。

当前契约：运行中空输入显示暂停，输入追加内容后显示发送；原生确认 interrupted 且空闲后显示启动，启动重新执行最后一轮原输入；最后用户消息的编辑恢复文字及附件预览到输入框，提交调用原生 edit 替换并重新执行。取消编辑恢复先前草稿。failed/interrupted 等已确定结果按原请求 ID 解除本地阻塞；uncertain 不解除、不自动重发。

权威来源：原生 threadRuntimeStatus、turn.status、turnId 和请求记录。resume 映射 thread-follower-edit-last-user-turn v2，限定最后一轮 interrupted、空闲且无待处理请求，在发送前重验。源码依据是本机 ChatGPT.app/Contents/Resources/app.asar 的 ucn 编辑处理器：保留原 input 的非首个 text 内容，替换首个 text，然后 thread/revert 或 thread/rollback，最后重新启动。它不会撤销已产生的文件或外部副作用。

原生接口限制：可修改文字并保留图片、文件等原 input；未支持编辑时增删附件，纯图片消息不能添加新文字。恢复附件使用原历史引用及已有受权资源接口，没有接收任意本地路径。暂停后的纯图片轮次可以通过 resume 重放原 input。

验证：
- python3 -m unittest discover -s tests：303 项，成功，跳过 1 项。
- 修改最终输入检查后 python3 -m unittest tests.test_operations tests.test_bridge：30 项成功。
- swift test --package-path iOS：32 项成功，含暂停/追加/启动按钮状态、已确定失败解锁、未知结果继续拦截、重启后请求 ID 匹配。
- sh iOS/scripts/compile-device.sh：设备目标无签名构建成功。
- git diff --check：通过。

未验证：真实手机与运行服务的完整暂停、启动和带附件编辑流程；原生接口行为目前依据源码及模拟 IPC 测试，没有向真实用户任务投递试验消息。独立审查代理因模型额度不足失败，独立审查门禁尚未满足，不能视为完整验收。

恢复：只撤销本次 ComposerAction、resume、编辑上下文和 PendingWrites.reconcile 的定向变更；保留仓库原先未提交改动及所有手机草稿、日志、请求记录。新增 lastTurnStatus 为读取投影字段，无存储迁移；旧服务不显示启动入口，发布验收须同时更新服务端和 iOS。运行服务和手机当前版本未被替换。
