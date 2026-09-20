# 初始化、账号与工作区

## 产品配置

正式云端地址只维护在 `carryon/product.json` 的 `cloudURL` 中。Python 从包资源读取；iOS 工程直接把同一文件加入资源；桌面初始化从 CLI 状态获取默认值。修改该配置后重新打包客户端。`init --url` 和客户端高级设置用于自托管覆盖，主流程不要求输入地址、目录或端口。

## 首次接入

1. 在 iOS 首页注册 CarryOn 用户账号，或使用账号密码／账号登录码登录。
2. 电脑打开并登录 Codex App，执行 `carryon init`，或打开桌面初始化向导。
3. 初始化默认工作区使用实际 `CODEX_HOME`（未设置时为 `~/.codex`）中的 `ipc/ipc.sock` 和会话；CarryOn 配置目录不作为会话来源。本机只允许运行一个 IPC 工作区。
4. 任选一条绑定路径：已登录手机扫描电脑的工作区二维码，核对并确认；或电脑填写目标账号，手机在接入页／连接申请中核对工作区及权限并确认。
5. 云端确认后才登记授权、签发凭证。电脑保存并默认启动；后续启动复用凭证、自动重连。没有工作区的手机直接进入接入页。

CarryOn 用户账号可授权多台电脑和多个工作区。新工作区须单独确认。Codex 模型账号属于本地模型运行环境，与 CarryOn 用户账号分别认证。

## 独立工作区

桌面「添加工作区」只填写名称（默认“新工作区”）。CLI 使用 `carryon services create --name 名称`，返回该工作区的内部定位信息。工作区拥有独立 `CODEX_HOME`、配置、会话存储和 app-server 进程；HTTP 监听端口由操作系统分配。进程通过私有 stdio 接入 Codex，不复用默认 IPC 的会话。

桌面初始化中的「登录 Codex 模型账号」打开 Codex 官方认证页面；CLI 可对返回的目录执行 `carryon services login --state-dir 目录`。账号认证仅写入该工作区。目录下 `projects` 是默认执行目录，Codex 使用 `workspace-write` 与 `on-request`。工作区隔离是会话与配置隔离，不是不同 OS 用户或容器级文件系统隔离。

独立工作区支持直接创建会话，无需 IPC 控制会话。发送、停止、引导、压缩、编辑、审批通过 app-server 原生协议适配。该版本 app-server 没有可用的排队编辑公共接口，相关操作明确返回不支持，不伪造原生队列。

## 两种二维码

- 工作区绑定码：手机先登录，扫码并确认后增加当前账号的工作区权限；目标账号申请不能由其他账号确认。
- 账号登录码：电脑明确输入目标 CarryOn 账号及密码，验证后生成短期登录码；手机扫描后电脑核对手机上的六位确认码并批准。工作区设备凭证不能签发任何成员的账号登录码。登录后读取该账号全部已授权工作区。

二维码短时有效。确认重试是同一授权结果的幂等读取，不创建重复工作区；其他账号、错误认领凭证及到期请求均拒绝。

## 恢复与删除

断网、超时或非凭证错误保留绑定并等待重试。只有云端明确返回设备凭证失效才进入重新绑定。扫码确认前保留旧配置；确认结果先私密保存，再使用旧绑定指纹进行对应替换，保留其他云端。并发更改导致指纹不匹配时须核对后应用，不能静默覆盖。

桌面删除工作区先停止对应服务，再移除目录条目，保留会话及配置文件。CLI `services remove --state-dir 目录` 要求服务先停止。撤销云端成员授权与删除本地工作区是不同操作。

## iPhone 密码集成

登录字段使用 username/password，注册和修改字段使用 newPassword。系统密码关联配置由 `scripts/apple_association.py` 从产品地址生成；Xcode 签名构建阶段生成 webcredentials entitlement。

服务端关联文件生成命令：

```sh
python3 scripts/apple_association.py --aasa output/apple-app-site-association --app-id TEAM_ID.BUNDLE_ID
```

发布时必须核对实际签名 Team ID 和 Bundle ID，并在正式域名根路径 `/.well-known/apple-app-site-association` 通过 HTTPS 返回此 JSON，无跳转。还需启用关联域名能力的 provisioning profile，并在真机确认「密码」保存、选择、自动填充和修改密码后的更新。Keychain token 保存不构成这些条件的完成证据。

## 验证与恢复边界

本任务只授权本地实现与验证；不提交、推送、部署、修改真实用户授权或代替用户进行生产扫码确认。恢复前停止新版本服务，保留每个工作区目录、云端 users/sessions/binding-invites 文件及设备注册表备份。含多账号授权的数据不能直接交给旧单管理员程序公开运行。详细验证结果和未完成门禁见 `implementation-onboarding.md`。
