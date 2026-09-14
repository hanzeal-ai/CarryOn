# 2026-09-12 审查问题修复与独立复核

## 当前结论

已修复前轮报告的 P1/P2，并通过两个 gpt-5.6-sol 审查者的独立复核。接受本次本地修复；这不是生产发布或真机端到端验收通过。

用户在前轮审查后明确要求“修复一下”，本轮授权覆盖下列源码修复、回归测试、构建及文档更新。风险 R2：涉及认证持久化与推送授权代次。未新增依赖、未操作生产数据库、未删除真实安装登记、未提交/推送/部署、未发送真实 APNs 或远程任务。

## 已修复

1. **密码轮换后旧推送失效**：installations.authority 复用 ConsoleAuth.fingerprint；扫描及发送前只信任当前账号代次。保留旧 cursor/记录，不重新授予旧记录权限。同代 Cookie 自然过期仍允许后台推送。
2. **重新授权可恢复**：注册高水位按 (authority, installationId) 隔离；账号轮换后允许 revision=1，新授权重新建立当前 baseline。同代迟到请求继续被拒绝。旧代记录不占用当前代 256 个安装配额；已有旧代 ID 重新授权也不能绕过配额。
3. **登录初始化事务**：login/qr poll 的 Cookie 先放内存；完整解析设备目录、检查取消后才保存。AppModel 仅在成功后一次性应用登录状态。非 401 错误、坏目录和扫码取消会针对新会话执行撤销。
4. **撤销与迟到响应隔离**：清理请求脱离已取消的 UI Task；本机凭证以 token 条件删除，Keychain 跨实例共用锁。旧 client 的 401/logout 不能删除新登录凭证。服务端撤销不可确认时，仍清理匹配的本机凭证并明确记录失败；不承诺网络故障时服务端已撤销。
5. **通知权限顺序**：先查询云端推送能力，再申请权限；异步边界检查任务取消、认证状态和 scope，避免旧工作区流程继续执行。
6. **文档**：初始 DELIVERY 标为历史基线；APNS 去除旧完成断言，增加当前代次、升级、备份和回退契约；更新本地存储和部署注释。前轮审查保留为历史，并链接本报告。

## 影响与恢复

唯一授权来源为 ConsoleAuth 的账号指纹，不新增独立账号状态。安装 generation 继续用于单次注册/注销的在途隔离；它与账号 authority 各自服务于不同生命周期。

SQLite 变更仅在 APNs 启用后的初始化生效：旧 installation 加空 authority，旧 registration_versions 在事务内迁移为复合主键，旧 revision 归空代次保留。首次升级后旧安装必须重新登录/登记；不自动继承未知授权。迁移只在临时测试库验证，未执行实际升级。

升级应先停用 APNs 并备份 SQLite。回退到不理解 authority 的代码必须保持 APNs 停用，保留新数据库、游标和高水位；不能用旧代码直接打开新结构，或用删库/恢复旧授权绕过撤销。详见 [APNs 文档](../APNS.md)。已经进入 Apple 的在途通知无法撤回。

iOS 恢复不清空系统 Keychain、不删用户草稿或待确认请求。只在新登录失败/取消或相应请求失效时定向删除匹配 token。恢复已有会话的临时网络故障不会销毁已保存会话。

## 验证证据

执行环境：当前 macOS 工作区、已有 Xcode/iPhoneOS SDK、已有 `.venv-apns`（httpx/cryptography），没有新增生产环境依赖。

| 命令/验证 | 结果 | 证据 |
|---|---|---|
| `.venv-apns/bin/python -m unittest discover -s tests` | 284 项全部通过，无跳过 | `.runtime/vibe-fix-20260912/python-tests.log` |
| `PYTHONPATH=tests .venv-apns/bin/python -m unittest test_push test_push_console test_console_auth test_apns` | 37 项全部通过，含 APNs 签名 | `.runtime/vibe-fix-20260912/backend-focused.log` |
| `swift test --package-path iOS --scratch-path /tmp/carryon-review-swift-clean` | 3 XCTest + 30 Swift Testing 全部通过 | `.runtime/vibe-fix-20260912/swift-tests.log` |
| `./iOS/scripts/compile-device.sh` | BUILD SUCCEEDED | `.runtime/vibe-fix-20260912/ios-build.log` |
| `.app` 检查 | CarryOn 为 arm64 Mach-O，完整构建资源已打包 | `iOS/.build/device-check-products/Debug-iphoneos/CarryOn.app` |
| `git diff --check` | 通过 | 本地执行 |

新增后端测试覆盖密码轮换/重启/旧记录直接投递拦截、同代会话过期继续推送、旧 schema 迁移保留游标、重新授权 baseline、新代低 revision、旧代容量及当前代配额。新增 Swift 测试覆盖非 401/坏 Record、取消、提交后取消、服务端撤销失败和旧客户端 401/logout 的凭证隔离。测试使用临时 SQLite、URLProtocol 和内存凭证存储；无真实通知发送。

旧漏洞独立复现由发送 1 次变为 0 次，同时保留原安装行。修复前后证据分别在 `.runtime/vibe-review-20260912/password-rotation-push-grant.txt` 和 `password-rotation-push-grant-fixed.txt`。

## 独立复核与剩余边界

后端与 iOS 审查者直接读取源码/测试并可要求修改，分别接受最终代码，未发现本次范围内新的 P1/P2。审查追加的旧代容量、高水位及迟到 401 问题已经修复并验证。审查并不替代用户的 R2 风险接受与发布批准。

仍未验证：实际 Keychain/锁屏文件保护、真实系统授权弹窗、真机后台/扫码双端、真实 Apple 投递和云端完整链路。本轮不宣称这些流程已通过。

非阻断容量边界：当前账号代次恰好满 256 条时，使用新 installationId 但相同 APNs token 的登记会先被配额拒绝，尚未按后续去重后的最终条数计算；正常持久 installationId 流程不受影响。

共享工作区存在其他未提交工作；本次补丁未回退它们。文件快照与哈希在 `.runtime/vibe-fix-20260912/snapshot.json`，未来改动需按其影响重新验证。
