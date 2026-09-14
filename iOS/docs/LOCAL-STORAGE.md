# iOS 本地存储

本次范围为现有 iOS 客户端的存储生命周期，不变更服务端认证、通知偏好、绑定权限或待确认请求协议。

| 数据 | 权威与生命周期 |
|---|---|
| 云端地址、视图选择 | 既有 UserDefaults；视图由首页的 AppStorage 管理 |
| 上次工作区 | UserDefaults 的 carryon.selectedDevices.v1，按规范化云端完整地址保存；恢复必须匹配服务端返回的可访问设备目录 |
| 会话凭证 | Keychain 通用密码项，service=com.hanzeal.carryon.console-session，account=规范化云端完整地址；WhenUnlockedThisDeviceOnly；不保存输入的登录口令，不跨服务器或路径复用 |
| 登录恢复 | 从 Keychain 读取后 GET session 验证，再置 authenticated；新登录先在内存接收 Cookie，设备目录校验成功且未取消才写 Keychain；失败/取消定向撤销新会话，无法确认撤销时写入运行日志；不恢复缓存运行状态、不自动重发写操作。401/退出仅原子清除与该请求 Cookie 匹配的凭证，旧响应不能删除新登录 |
| 草稿 | Application Support/CarryOn/drafts-v1.json，文字和附件按云端/设备/会话隔离；新建会话使用 new；250ms 合并写入，切换工作区、退后台、退出与确认发送后立即保存；退出清内存但保留磁盘草稿 |
| 运行日志 | Application Support/CarryOn/runtime-log-v1.json，最近 200 条，每条最多 2048 字符；过滤已知口令、Bearer 和常见凭证字段；不主动采集请求正文 |
| 待确认请求 | 保留既有 UserDefaults 请求编号和内容哈希，不迁移、不清空，继续由原 PendingWrites 规则解决 |
| 通知开关 | 服务端绑定范围的 SQLite 为权威；本次不增加独立本地副本 |

草稿和日志文件使用原子写入、iOS Complete File Protection，并排除设备备份。日志读取损坏时停止覆盖该文件，页面显示存储问题；草稿读取损坏时保留原文件，记录当前编辑无法持久保存。写入失败保留内存内容并记录问题。杀进程前最后 250ms 内的未落盘输入仍可能丢失。

## 验证与交付门禁

- 风险 R2：新增本机凭证存储和会话恢复，涉及认证生命周期。授权仅覆盖本地实现与测试，不含部署、签名安装或生产更改。
- `swift test --package-path iOS --scratch-path iOS/.build/storage-tests`：21 项通过；新增覆盖跨云端路径隔离、进程重建后的会话恢复、403 保留/401 清除/退出清除、草稿与附件恢复、工作区目录校验、日志脱敏与损坏文件保留。
- iOS 17 / Swift 6 目标：CarryOnCore 编译和 AppModel、Design、RuntimeLogView 类型检查通过。
- 测试的凭证存储使用内存替身；未验证真机 Keychain 访问、锁屏文件保护、终止进程恢复和完整 App。当前共享工程的 ExyteChat 依赖与页面改动由主任务处理，本次不覆盖它们。
- 上述测试数量属于初始存储实现快照。当前修复和独立复核见 [修复验证记录](../../docs/reviews/2026-09-12-vibe-coding-fixes.md)；真机 Keychain、锁屏文件保护和后台恢复仍需验收。

## 恢复

没有迁移或删除既有设置、请求日志、服务端数据。恢复本次代码时保留草稿、运行日志和原 PendingWrites 数据；旧版本忽略新增文件和偏好。已产生的 Keychain 项只能经正常退出或按本应用 service/account 定向清除，禁止清空系统 Keychain。回退客户端代码不撤销服务端有效会话，必要时在服务端撤销相应会话。
