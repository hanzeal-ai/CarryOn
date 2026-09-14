# iOS 系统通知

云端 console 的 PushService 独立于手机登录页面和手机 WS，每 5 秒通过已有电脑 WS 读取增量通知快照。此频率是采集频率，不是 APNs 到达保证。iOS 前台仍使用 WS 显示完整进度，写操作仍走原有 HTTPS 门禁。本次不包含 ActivityKit / 灵动岛。

## 事件与授权

- 复用 Workspace 的 notification_events、通知偏好、有效已读游标和 activity 投影；不把任务投递成功当作 Codex 完成。
- 完成、失败、审核、新消息均按开关筛选。同一轮有开启通知的完成／失败事件时，不再发送其新消息提醒；流式 token 不推送。
- 每个 iOS 安装绑定一个当前工作区；切换工作区重新登记，角标为该工作区动态数加连接申请数。点击通知按 payload 的 server、deviceId、threadId 核对当前云端及授权后打开会话，不执行审批。
- 首次在线注册读取当前事件上限作为基线；不会补发注册前的历史。离线注册在首次连接时建立基线。已经登记的安装保留读游标，断线重连继续采集。
- 注册和取消注册携带本机持久递增的 revision；服务端在读取 baseline 前预留版本，迟到请求不能覆盖更新版本。请求高水位仅用于排序，准备失败不会停用已提交的有效绑定。相同安装和工作区换 Token 不请求 baseline，保留 cursor、失败重试状态；切换工作区才重建 baseline。取消登记保留版本高水位，防止旧请求复活。iOS 注册暂时失败最多尝试 3 次（间隔 1 秒、3 秒），取消或切换作用域时停止；服务端临时连接故障返回 503，参数和权限错误不重试。
- 安装注册是独立于短期登录 Cookie 的持久推送授权，普通 Cookie 过期不会停止后台推送。显式退出登录注销该登录会话登记的安装，iOS 同时携带安装 ID 和版本以撤销旧登录留下的同一安装授权；通知权限拒绝也按安装撤销，版本较旧的请求不生效。工作区撤销、通知权限拒绝、Token 失效也停止相应推送。90 天未重新登记的安装到期清理。管理员账号密码轮换并重启服务后，旧账号代次的安装授权立即失效；手机必须用新账号会话重新登记。系统通知权限仅在云端报告已启用推送后申请。
- GET/POST/DELETE /console/push 复用 console 的会话认证和 Origin 校验。客户端不得指定 provider topic、Team ID 或密钥。push.sqlite 以 0600 存储 Token、作用域和游标，不放入发布包。

## 没有付费开发者账号

可以先运行全部服务端测试及 Swift Core 测试。HTTP/2 客户端用 MockTransport 验证签名和请求，另外有真实电脑 WS → 云端 → 模拟 APNs 发送器测试，不需要手机保持连接。

```sh
python3 -m venv .venv-apns
.venv-apns/bin/python -m pip install '.[apns]'
.venv-apns/bin/python -m unittest discover -s tests
swift test --package-path iOS --scratch-path iOS/.build/apns-tests
```

在安装了 App 的模拟器中，允许系统通知后：

```sh
xcrun simctl push booted com.hanzeal.carryon iOS/fixtures/task-completed.apns
```

测试展示可以直接使用样例；测试点击跳转需要先将 server、deviceId、threadId 换成当前有权限的真实会话，否则 App 会拒绝跳转。模拟器注入不经过 APNs，也不证明真机锁屏或后台投递成功。

默认不启用推送签名 entitlement，因此不要求先购买开发者账号。启用前不要宣称已具备系统后台通知。

## 后续真实 APNs 配置

需要 Apple Developer 账号、启用 Push Notifications 的 App ID、匹配的签名描述文件、Team ID / Key ID 和 P-256 .p8 推送密钥。

云端安装可选依赖 `.[apns]`，建议使用专门的 Python 虚拟环境。现有 systemd console drop-in 的 ExecStart 使用系统 Python；启用 APNs 时将解释器改为安装了该 extra 的虚拟环境 Python，保留原配置路径、state-dir、WorkingDirectory 和其他安全设置。没有 apns 配置时无需安装此 extra。

在现有 console 配置 JSON 中增加以下对象，保留所有既有配置与 devices：

```json
{
  "apns": {
    "teamId": "YOURTEAMID",
    "keyId": "YOURKEY_ID",
    "topic": "com.hanzeal.carryon",
    "keyPath": "/etc/carryon/apns/AuthKey.p8"
  }
}
```

上例 ID 为占位符，均需换成 Apple 提供的 10 位 ID。私钥归服务运行用户所有、权限 0600，不能加入 Git、日志或 iOS 包。`.p8` 已加入忽略规则。provider 通过 TLS HTTP/2 连接苹果固定域名，不跟随重定向，ES256 JWT 缓存不超过 50 分钟。

Xcode 构建设置增加 `CARRYON_PUSH_ENTITLEMENTS=CarryOn/CarryOn.entitlements`。`CARRYON_APNS_ENVIRONMENT` Debug 默认为 sandbox、Release 默认为 production；需要与实际签名 entitlement 匹配，TestFlight 使用 production。iOS 请求 alert/sound/badge 权限，APNs 返回 Token 后向登录的云端登记。曾只授权角标或拒绝通知的用户需检查 iOS 设置中的横幅和声音权限。

## 投递、恢复与验证边界

通知快照用 workspaceRevision 校验投影和事件窗口的一致性，期间变化就重新读取，连续变化则报错且不推进游标，避免新事件被旧可见集合过滤。成功投递后逐事件持久推进游标；暂时失败采用有上限的指数退避，401/403 配置问题不会删除设备，410 / BadDeviceToken / DeviceTokenNotForTopic 删除失效登记。新消息和终态去重由本机权威事件判定，云端保留稳定 apns-id；网络不确定时可能重复，不能承诺 exactly-once。APNs 可能延迟或合并同一会话提醒，App 打开后必须重新同步最新状态。

发送前再次检查安装 generation，避免 Token 换绑或注销后的旧队列继续发送；已在途的苹果投递无法撤回。重试前重新读取当前偏好与已读状态。持久数据库保留每个安装最近的失败原因与下次重试时间，排查时仅查询 id/error/failures/retry_at，不输出 token。

回退时停用 console 配置中的 apns 对象并恢复原解释器启动方式；保留 push.sqlite 和本机 Journal，不通过删除游标重发。密钥泄露时需在 Apple 后台撤销。重启、部署、真实推送和签名发布仍需对应授权，本次未执行。

开发验证命令：`.venv-apns/bin/python -m unittest discover -s tests`（需该环境已安装可选 APNs 依赖）、`./iOS/scripts/compile-device.sh`。覆盖签名、请求环境、失效 Token、重试、游标持久化、偏好/已读去重、认证与 Origin、注销和本地 WebSocket 到模拟发送器。具体执行快照、结果与独立审查结论见 [修复验证记录](reviews/2026-09-12-vibe-coding-fixes.md)，不以历史测试数量或旧审查替代当前验收。真实 Apple 投递和真机后台流程需单独验收。

## 授权代次与升级恢复

安装登记的 authority 取自 ConsoleAuth 的账号指纹，与登录会话使用同一权威来源。读取待投递记录和发送前均校验当前代次；普通 Cookie 自然过期不影响同代次后台推送。注册数量只统计当前代次。

启用 APNs 时会检查 SQLite schema：为 installations 增加 authority（默认空，表示旧登记尚未证明属于当前账号），registration_versions 改为按 (authority, id) 保存高水位。旧单列主键表在事务内复制到新结构，原版本保留在空代次，不静默继承为当前授权。原 cursor 不删除；新会话重新登记时以最新通知快照建立 baseline，避免重放旧任务。账号轮换后的新代次可从 revision=1 开始，同代次的迟到请求仍被高水位拒绝。

首次升级时原有安装不会继续投递，手机需重新登录后登记。升级前停用 APNs 并备份 push.sqlite（运行中的 SQLite 应使用 backup API 或停服后复制，不能只复制活跃数据库主文件）。本次只验证临时测试数据库，未操作运行环境。

回退到不识别 authority 的旧版本前必须保持 APNs 停用，否则旧版本可能重新投递已失效授权；保留新结构数据库、原游标和高水位，不直接用旧程序打开新结构，不通过删库绕过检查。若需恢复备份，应先完成恢复审查并确保未恢复已撤销授权。密码轮换不能撤回已经进入 Apple 在途队列的通知；Apple 密钥泄露仍需在 Apple 后台撤销。
