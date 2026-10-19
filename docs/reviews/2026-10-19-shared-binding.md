# 共享工作区绑定实施记录

## 范围与契约

在原有工作区分组上统一账号授权。首次手机扫码后，电脑端新增同机同 CODEX_HOME 的
CLI/桌面连接可以选择已有绑定，预览成员、权限及本地远程操作开关，并明确确认加入；
手机无需再次扫码。既有独立扫码的连接不自动合并权限。

CLI、桌面 IPC、自有 app-server 保持独立生命周期和传输，公共协议组件继续复用。
共享的是工作区成员权威；每个连接保留独立 device ID/token、本地操作开关、会话实时状态、
订阅、草稿及审批目标。相同 thread ID 不表示可跨运行时投递审批。

R2：涉及账号授权。工作直接在 main 的既有未提交改动上完成，起点
49729a469bf9ae7f7d9a2b9283735886d8bf3c3a；未提交、推送或部署。

## 实现与影响

- `workspaces/authorization.py` 在现有 devices.json 内保存单跳 workspaceAuthority；
  只在权威记录保存成员。缺失或循环引用拒绝授权。
- `accounts/member_management.py` 的授权读取、修改和订阅撤销解析同一权威；
  原生 manage 接口提供 preview/attach，浏览器 Origin 请求拒绝。
- `accounts/shared_binding.py` 用来源 token、预览 revision、显式确认和同工作区验证加入。
  新连接生成独立凭证，不复制成员。响应丢失保留原 request ID，重试不重复创建；
  已删除连接的旧请求不能复活它。未提交预览可取消，结果未知的请求保留以恢复。
- 移除权威所在连接，在同一次原子保存中向剩余连接转移成员及幂等记录；仅撤销被删连接。
- 公共协议 refresh_snapshot 增加投影身份检查：读取期间如通知或完整快照已更新状态，
  保留新投影，防止旧 thread/read 的 active 覆盖刚收到的 idle。独立复现及确定性线程交错测试覆盖。
- CLI 和桌面初始化 UI 支持成员预览、确认、取消与未完成请求恢复；
  已绑定其他云端不隐藏待恢复请求，各云端独立处理。

## 验证

- 最终 Python 全量：913 项，109 项环境依赖跳过，804 项通过（172.995 秒）。
  包含共享绑定专项 16 项及同步竞态确定性回归；日志 `/tmp/carryon-shared-final-all-python.log`。
- Swift：151 项 Swift Testing、10 项 XCTest 通过。桌面 Swift 可执行文件编译通过。
- 独立审查：基于实现、原始接口及测试证据审查，修复多云端恢复与重试入口问题后无阻塞项；
  最后取消分支补审及测试通过。同步竞态修复补审通过，独立运行相关 12 项测试通过。
- 手机链路：使用隔离 CODEX_HOME、真实 Codex CLI/daemon、HTTPS/WSS 和 iOS 模拟器；
  桌面连接使用 IPC 协议测试夹具，模型使用本地确定性 Responses 夹具。
  曾完整通过 38 项检查；其中一次复测出现重连审批后完成状态超时，该次保留为失败。
  增加原生事件、手机与桥接快照诊断后两次完整通过。审查发现并修复确定可复现的旧读取覆盖新事件竞态；
  不能追溯确认它就是原失败根因。修复后最终手机复测 38 项全部通过，源码哈希一致；原生事件及双端快照保存在
  `.runtime/shared-binding/`，并核对 107 个生产 Swift 文件与构建输入一致。
  日志：/tmp/carryon-shared-mobile-delivery.log；失败结果保留在
  /tmp/carryon-shared-mobile-failed-result.json。

## 升级与恢复

本次未修改个人绑定或重启个人服务，未部署云端与客户端。
启用需更新 Console、本机服务及相应客户端，并重启本机连接重新发布工作区信息。
保留 devices.json、services.json、各连接凭证目录和 Journal；不复制 members 来兼容旧版本。
旧 Console 不认识 workspaceAuthority 时新增子连接失去授权读取能力，恢复支持该契约的版本后核对。
不确定的加入请求须重试原 request ID，不删除日志后重新加入。

未覆盖物理手机、公网网络和真实桌面应用的双端操作链路；不将协议夹具结果视为这些环境验证。
