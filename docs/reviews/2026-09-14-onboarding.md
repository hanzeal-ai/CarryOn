# 2026-09-14 初始化与账号权限独立审查

结论：有条件通过当前初始化、账号注册、工作区成员授权与桌面端成员管理切片。公开账号密码自助注册已由用户确认纳入本次范围，不作为缺陷；公共托管地址、账号恢复方式、真实生产部署和独立 app-server 仍不视为已验收。

本次审查是只读独立复核，只修改本报告。审查依据为 `docs/implementation-onboarding.md`、当前源码与我实际运行的测试。工作树同时存在会话、子代理、UI 等其他未提交改动，本报告只评价初始化和账号权限相关切片。

## 范围与边界

已纳入审查：

- CLI / 桌面初始化状态、重复初始化、过期续办、已确认账号自动绑定。
- 账号密码注册与登录身份持久化。
- 工作区绑定邀请、成员邀请、电脑端确认、成员 grant / revoke。
- HTTP、WebSocket、文件读取、push 注册与发送前的工作区权限检查。
- 桌面 `InitializationView` 与 `WorkspaceMembersView` 对 source 账号选择和权限传参的边界。

未纳入验收：

- 独立 app-server 仅可视为 schema / probe 或待适配方向，不能声明已支持。
- 真实 APNs 设备投递、真实 iPhone 扫码与撤权验收、生产代理部署、账号恢复流程、公共托管地址策略。
- 用户报告的全量 Python / JS / Swift / iOS 构建结果未由本审查重新全量复跑，只记录为外部报告；我只记录自己实际运行的检查。

## 已修问题与复核结论

1. 公开注册误报撤回。
   `docs/implementation-onboarding.md` 已记录用户确认本次采用账号密码自助注册并保留云端地址输入，因此 `/console/register` 和 iOS / 桌面注册入口本身在授权范围内。后续风险只按滥用防护、身份隔离和未定的公共托管策略评估。

2. 绑定 start 滥用面已收敛。
   `BindingInvites.throttle(peer)` 使用真实 TCP peer 做来源限速，不依赖 `X-Forwarded-For`。这解决了未认证 binding start 可被同一来源快速塞满邀请池的主要风险。代理部署下真实来源解释仍应写入部署文档。

3. 成员邀请需要使用者扫码和电脑端确认。
   `binding/accept` 对已有工作区成员邀请只进入 `accepted`，不会立即成为 member；`member_management.confirm` 再核对 poll secret、workspaceId、accountId 和状态后才写入 members。测试覆盖“扫码后 session 仍看不到设备，电脑确认后才可见”。

4. 撤权传播已补齐关键路径。
   成员 revoke 会更新后端 members，并主动 release 被撤销 identity 在该 device 上的 console streams。普通 HTTP、文件读取、写请求、WebSocket 发送、push 发送前均有后端权限检查或当前性检查。新增测试覆盖撤权后 HTTP / 文件 / 写拒绝和已有 stream 被关闭。

5. 转发后撤权竞态已处理。
   `ConsoleHandler.reply` 在成功响应前二次 `require`。如果写请求已被 gateway / 本机接收后权限变化，响应改为 `409` 且包含 `uncertain: true`，提示用原 `requestId` 核对且不要重试。stream 创建期间撤权时，handler 会临时登记 stream 并调用 `release_stream` 清理本地与上游，不泄漏 streamId。新增测试 `test_revocation_during_forward_preserves_uncertainty_and_cleans_new_stream` 覆盖该竞态。

6. `forward_body` 缓存替代 `rfile` 重绑语义可接受。
   console handler 先解析外层 JSON body，再转发给 gateway；gateway 后续调用 `body()` 时读取同一个已解析对象。连接仍在每次响应后关闭，没有跨请求缓存复用。当前路径只用于 console 转发设备 request / streams，未发现重复读取 socket body 或 Content-Length 错配导致的语义缺口。

7. known-account 自动绑定的权限边界可接受。
   `members_cli.exchange` 的 `known-accounts` 根据当前目标 binding 推导同云 URL，避免桌面成员管理页额外传 URL。桌面 `WorkspaceMembersView` 只显示同云其他工作区中已确认的账号；grant 时传 `sourceDirectory` / `sourceBindingId`，后端仍通过 source workspace 的 device token 验证该 accountId 已在本机确认，不信任 UI 选择本身。`InitializationView` 在云端地址变化时清空已加载账号与选择，避免把旧云端账号误用于新 URL。

8. knownRequest 持久记录已有限制。
   已确认账号自动绑定保留幂等记录以避免超时重建；当前实现增加 1024 上限，并在 source workspace 已撤销时删除对应记录。该策略可接受。仍建议后续在维护任务中考虑更明确的清理可观测性，但不是当前阻断项。

## 本次实际运行检查

我在当前工作树运行并观察到通过：

```text
python3 -m unittest discover -s tests -p 'test_onboarding.py'
Ran 29 tests in 21.959s
OK

python3 -m unittest discover -s tests -p 'test_multi_cloud.py'
Ran 9 tests in 6.569s
OK

python3 -m unittest discover -s tests -p 'test_push_console.py'
Ran 12 tests in 6.266s
OK
```

此前同一轮审查中还独立运行通过了相关 Python 子集：

```text
test_console_socket.py: 16 tests OK
test_push.py: 15 tests OK
test_console_auth.py: 9 tests OK
test_images.py: 6 tests OK
test_artifacts.py: 3 tests OK
```

这些检查覆盖了账号隔离、旧管理员/legacy 访问边界、成员邀请确认、撤权后访问拒绝、转发后撤权 uncertain、stream 清理、多云绑定隔离和 push 控制台路径。

## 剩余风险

- 独立 app-server 未适配完成，不能对外宣称支持。
- 真实设备和生产路径未由本审查验证：iPhone 扫码、真实 APNs、生产代理、TLS、公共托管地址策略、账号恢复均仍需专项验收。
- 桌面 `WorkspaceMembersView` 为新 UI 面，当前审查只检查权限数据流和 source 验证边界，没有做完整视觉和交互验收。
- 成员权限变更不会撤销已经执行的任务，也不保证停止正在执行的任务；UI 文案已有说明，验收时仍需向用户保持这一边界。

## 最终判断

当前切片在本地代码与测试证据层面达到 R2 条件通过：可继续进入最终汇总或更大范围回归。不得把未验证的 app-server、生产部署或真实设备交付写成已完成。
