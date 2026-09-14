# 2026-09-12 编译优化与当前变动审查

> 此文是修复前的审查快照。后续处理结果见 [修复与复核记录](2026-09-12-vibe-coding-fixes.md)，不要把以下缺陷状态当作修复后的状态。

## 结论

ConversationView 编译优化接受；当前整批变动按 R2 评估，结论为**要求修改**。测试通过不替代权限恢复、真实产品流程和独立审查发现的修复。

本次只修改 ConversationView 的表达式组织，并新增本报告；未修复其他任务的业务实现，未提交、推送、部署、安装 App 或发送真实通知/远程操作。共享工作区在审查期间持续写入认证/扫码改动，以下结论只覆盖已读取快照；文件清单与哈希见 `.runtime/vibe-review-20260912/snapshot.json`，不能视为后续改动也已通过。

## 本次完成的优化（R1）

- `iOS/CarryOn/App/ConversationView.swift:102`：消息行提取为显式 `MessageBuilderParameters` 参数的方法，缩小泛型推断范围。
- `:112`：输入区提取为 `@ViewBuilder composerView`，局部保留 `@Bindable`；发送与停止提取为方法。
- 未改变消息、草稿、图片入口、禁用条件和 expectedTurnId 传递。未引入 AnyView、替身依赖或新业务状态。
- 独立 iOS 审查者直接对比优化前快照和最终源码，未发现该优化新增 P1/P2；完整 iPhoneOS 构建已通过。原截图中的类型检查超时在完整构建中不再出现。
- 恢复时仅反向应用本次提取差异，不覆盖该文件此前的用户改动；本次不涉及数据迁移。人工输入、发送/停止和照片选择抽查仍由用户完成。

## 审查发现

### P1：重设管理员密码没有撤销旧 APNs 授权

位置：`carryon/console_auth.py:40-49`、`carryon/push.py:103-129`。

账号指纹改变会使旧持久登录会话失效，但 push.sqlite 中的安装登记没有绑定账号授权代次；重启后继续使用原登记投递。若旧密码泄露期间曾注册通知设备，重设密码后该设备仍可能收到任务标题、threadId 等元数据，直至原安装显式注销、工作区撤销或登记到期。

独立后端审查者用临时状态目录和模拟发送器复现：账号指纹改变，活跃 sessions=0，重启后 installations=1，tick 仍发送 1 次任务标题。没有网络投递或真实用户数据。复现脚本与结果位于 `.runtime/vibe-review-20260912/reproduce_password_rotation_push_grant.py`、`password-rotation-push-grant.txt`；可用 `PYTHONPATH=. .venv-apns/bin/python .runtime/vibe-review-20260912/reproduce_password_rotation_push_grant.py` 重现。

要求：推送授权绑定账号凭证代次，密码轮换时使旧代次失效，保留普通 Cookie 自然过期不影响后台推送的现有契约；补充跨重启和密码轮换的负向测试及恢复说明。

### P2：登录初始化失败仍保存新会话凭证

位置：`iOS/CarryOn/Core/ConsoleAPI.swift:82-87`、`iOS/CarryOn/App/AppModel.swift:125-159`。

login 或已认证 qr/poll 一成功就写 Keychain；随后 GET session 失败、目录格式错误或扫码任务取消时，界面未完成登录，但新会话未被撤销，凭证也仍持久保存。后续启动可能自动恢复，状态与用户看到的失败/取消不一致。

要求：明确认证成功但初始化待重试的状态，或为失败/取消增加定向撤销与凭证清理；不要让“登录失败”与持久有效凭证隐式并存。需要覆盖非 401 错误、坏目录和扫码取消。当前为代码路径证据，未做真机 Keychain 复现。

### P2：无推送能力时提前申请系统通知权限

位置：`iOS/CarryOn/App/PushNotifications.swift:55-62`、`iOS/CarryOn/App/CarryOnApp.swift:13-14`。

登录前台同步会先 requestAuthorization，之后才检查 /console/push enabled。未配置 APNs 的云端也会触发通知授权，无法提供相应能力。

要求：先验证服务端能力，再申请相关权限；保持现有通知入口和产品授权意图。当前为确定调用顺序的源码证据，未实际触发系统权限弹窗。

### 交付证据需要更新或标明历史适用范围

`iOS/docs/DELIVERY.md` 仍描述最初“不引入生产依赖、仅 iOS 改动、凭证只存内存、8 项测试、APNs 后端未提供”的基线。`docs/APNS.md` 的旧测试数量与“无 P1/P2”仅属于其当时快照，不能覆盖后来加入的密码认证和当前跨模块问题。

要求：将旧记录明确标为历史交付，当前门禁引用本次可复现证据及未完成项。不要通过修改测试数量把旧独立审查结论扩展到当前全部代码。docs/CONSOLE.md 的旧 configure 指引已在并发任务中修订，故不列为未解决问题。

## 本次验证

| 检查 | 结果 | 日志 |
|---|---|---|
| `./iOS/scripts/compile-device.sh` | BUILD SUCCEEDED，完整未签名 iPhoneOS App | `.runtime/vibe-review-20260912/ios-build.log` |
| `swift test --package-path iOS --scratch-path /tmp/carryon-review-swift-clean` | 3 项 XCTest + 23 项 Swift Testing 通过 | `.runtime/vibe-review-20260912/swift-tests.log` |
| `python3 -m unittest discover -s tests` | 278 项运行，277 通过、1 跳过 | `.runtime/vibe-review-20260912/python-tests.log` |
| `node --test tests/test_*.js` | 36 项通过 | `.runtime/vibe-review-20260912/javascript-tests.log` |
| `git diff --check` | 通过 | 本地命令 |
| App 产物检查 | Mach-O arm64、com.hanzeal.carryon，聊天/高亮/媒体资源 bundle 存在 | `iOS/.build/device-check-products/Debug-iphoneos/CarryOn.app` |

独立后端审查另在已安装 httpx/cryptography 的 `.venv-apns` 运行认证、APNs、push、push-console、workspace 聚焦测试 50 项通过，包含系统 Python 环境跳过的 APNs 签名检查；这仍不证明真实 Apple 投递成功。

最初主机测试使用从 ConnectNow 路径带来的旧缓存而报 SwiftShims 路径冲突，改用独立 scratch 后通过，未删除原缓存。首次全量 Python 测试的静态资源和 configure 三项失败在并发任务更新后，已全量复测通过。

## 独立审查与剩余门禁

用户明确允许其他模型后，两个 gpt-5.6-sol 审查者分别直接读取后端和 iOS/Web 原始差异、源码及测试，具有要求修改和否决权；审查者未修改实现。后端审查提供隔离复现；iOS 审查接受编译优化，但要求修改整批 R2 变动。最初因额度失败的 Agent 不计入有效审查。

已具备部分正向控制：服务端仍执行权限裁决；草稿沿用 scope 和服务端确认清理；Keychain 按云端地址隔离；请求结果不确定时保留原请求编号；APNs 有持久游标与重试边界。本次优化仅建立编译边界，没有建立第二套业务状态。

未完成：上述缺陷修复与复核；当前全部新增能力的历史授权核对（本轮审查授权不等于追认此前新增依赖/功能）；本轮未执行真实原生聊天交互、二维码双端、Keychain/锁屏/后台恢复、真机 APNs 与真实云端链路验收；其他任务随后新增的验证文档不自动计入本次证据。既有截图或局部渲染器测试不等于完整 App 流程验收。R2 人类风险接受和目标环境发布批准未执行，本次也未请求发布。
