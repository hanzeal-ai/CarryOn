# 初始化和工作区授权

本页描述当前本地实现，尚不代表安装包已发布、生产已升级或完成真实手机 HTTPS 验收。独立 app-server 和宿主机沙箱边界仍在专项实现范围内。

## 首次使用

1. 在 iOS 的现有登录页填写云端 HTTPS 地址，用账号密码注册或登录。
2. 电脑安装 CLI、打开 Codex App，执行 `carryon init`（也可用 `--url https://你的云端地址`）。
3. 选择绑定后是否自动启动（默认是）以及成员权限。已有同云端账号可直接选择；新账号扫码确认。
4. 绑定后自动启动本地桥接和云端连接；取消自动启动时配置仍保存，之后运行 `carryon start`。

不再要求依次执行 start、bridge on、cloud connect。未连接 Codex 或云端时不会报告工作区已就绪。`start` 不默认打开浏览器；`open` 或 `start --open` 可打开本地会话页面。

桌面端首次打开初始化向导，使用相同配置、二维码和进度。已有 CLI 绑定直接复用；关闭向导或 Ctrl+C 不删除配置，五分钟内可以续办二维码，过期后重新生成。关闭桌面窗口不停止已启动的后台服务。

## 日常与权限

```sh
carryon start
carryon status
carryon stop
carryon members list
carryon members invite --permissions view,send,stop,files
carryon members grant --account-id 账号ID --permissions view,files
carryon members revoke --account-id 账号ID
```

多绑定通过 `--binding-id` 指定云端；多本地工作区通过 `--state-dir` 指定目录。新账号邀请流程是手机接受、电脑核对账号、电脑确认授权。成员变更不授予电脑管理权或其他工作区权限。撤销会关闭该成员已有实时订阅，阻止后续访问；已经提交的任务不回滚，正在执行的任务也不保证停止。

可选成员权限是 view、create、send、stop、edit、files、approve。操作需要 view；未知权限和操作默认拒绝。底层当前仍连接 Codex App，其运行权限与会话仍由 Codex App 决定。成员权限不构成文件系统、密钥、命令或网络隔离。原有云端绑定的本机远程控制开关仍是额外限制；关闭时授予写权限也不能绕过该开关。

新建第二个本地工作区时，可在 init 中从同云端已确认账号选择，无需再扫码。桌面「工作区使用者」可从已确认账号选择并确认授权；CLI 在 `members grant` 中也可用 `--source-state-dir` 提供已有账号所在工作区。此证明来自该工作区的设备凭证及当前成员记录，不根据用户名猜测身份；来源工作区撤销此账号后，旧的账号选择不能继续用于新增授权。

## 状态与协议

本地 `onboarding.json` 保存初始化进度；实际绑定仍以 `cloud.json` 为准，启动参数仍使用本机服务注册表。手机只取得自己的登录会话；独立设备凭证通过二维码的独立轮询秘密发给电脑，不向手机或 CarryOn 账号服务上传 Codex Token。

`carryon init --input-json` 为桌面共用入口：action 为 status、prepare、poll、known-accounts。prepare 接收 url、autoStart、permissions、name、port、codexHome；已有账号还提供 accountId、sourceDirectory、sourceBindingId。调用返回真实运行、桥接和云端连接状态，不能将 bound 等同于在线。

公开绑定创建按 TCP 来源限制为每分钟 6 次，最多 64 个有效待确认邀请。反向代理下 TCP 来源可能是共享代理，不信任任意 X-Forwarded-For；公网部署需在可信入口配置合理的真实来源限流。已有账号初始化的幂等记录有 1024 条上限，超限明确拒绝，不自动删除记录后重建未知结果。

## 恢复与未完成边界

本次未迁移真实云端数据。使用隔离测试目录验证；发布前需备份云端配置、account.json、users.json、sessions.json、devices.json、binding-invites.json 及本地完整私有目录。回退旧的单管理员服务会失去多账号访问控制，因此不得把包含新多账号设备的注册表直接交给旧程序公开运行。

独立 app-server 探测验证了独立 CODEX_HOME 下读取文件式本机鉴权、创建探测会话，以及原 Codex 数据库未收录该会话；原鉴权文件未改变。尚未验证完整会话操作、Keychain 鉴权、模型调用后的存储和强制目录/网络/审批隔离，尚未作为可选工作区后端提供。控制会话选择、独立工作区调度、暂不分配的完整桌面向导仍需后续完成。
