# 初始化和工作区授权

本页描述当前本地实现，尚不代表安装包已发布、生产已升级或完成真实手机 HTTPS 验收。独立 app-server 和宿主机沙箱边界仍在专项实现范围内。

## 首次使用

1. 在 iOS 登录页用账号密码登录；新账号注册还需一次性邀请码。
2. 电脑安装 CLI、打开 Codex App，执行 `carryon init`；默认连接 CarryOn 云端，自托管可显式指定 `--url https://你的云端地址`。
3. 选择绑定后是否自动启动（默认是）以及成员权限。已有同云端账号可直接选择；新账号扫码确认。
4. 绑定后自动启动本地桥接和云端连接；取消自动启动时配置仍保存，之后运行 `carryon start`。

不再要求依次执行 start、bridge on、cloud connect。未连接 Codex 或云端时不会报告工作区已就绪。`start` 不默认打开浏览器；`open` 或 `start --open` 可打开本地会话页面。

桌面端首次打开初始化向导，使用相同配置、二维码和进度。已有 CLI 绑定直接复用；关闭向导或 Ctrl+C 不删除配置，五分钟内可以续办二维码，过期后重新生成。关闭桌面窗口不停止已启动的后台服务。

二维码页面点击「取消」会作废当前二维码，返回上一步权限设置并保留选项；「稍后继续」仅关闭向导，保留待扫码进度。取消失败时保留当前二维码，可重试；手机已确认的绑定不能通过取消撤销。

## 注册邀请码

只有指定电脑的专用凭证可以生成注册邀请码；管理员账号、浏览器会话和工作区设备凭证均不授予生成权。首次在指定电脑执行：

```sh
carryon invate --setup
```

将返回的 `issuerHash` 交给云端运维，在服务器设置唯一授权指纹并重启控制台：

```sh
carryon-console authorize-inviter --config /实际路径/console.json --issuer-hash 指纹
```

之后在该电脑执行 `carryon invate`，或用 `--binding-id` 选择云端；也可直接指定 `--url https://你的云端地址`。桌面端在工作区云端条目点击「生成注册邀请码」，支持复制邀请码和查看本机授权指纹。CLI 与桌面端必须同时升级。

本机凭证保存在 `~/Library/Application Support/CarryOn/invite-issuer/credential.json`，目录权限 0700、文件权限 0600，不随工作区配置传递。不要把此凭证复制到其他电脑；持有凭证即拥有生成权限。更换电脑需重新配置唯一指纹，旧电脑在云端重启后失去生成权限。

Web 和 iOS 注册均必须提交 `inviteCode`。邀请码没有时间到期，成功创建一个账号后永久失效；参数错误、账号重名不会消耗它。账号和核销标记在 `users.json` 同一次原子写入，并发请求最多成功一次。邀请码只用于注册，不附带工作区权限。已有账号登录和管理员初始化保持原流程。

发布前备份云端配置、`users.json`、`registration-invites.json`；先部署云端校验及授权指纹，再升级客户端。未配置指纹时默认拒绝生成，旧客户端不能完成注册。回退应优先前向修复；回滚旧代码会恢复无邀请码注册，恢复旧 `users.json` 会撤销新账号并重新启用其已用邀请码，不得单独回滚该文件。本次源码修改未配置或部署真实云端。

验证：`python3 -m unittest discover -s tests -p test_registration_invites.py`。

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

本地 `onboarding.json` 保存初始化进度，`cloud.json` 保存连接配置；设备凭证是否有效由对应云端验证，不能仅凭本地 enabled 判断已绑定。启动参数仍使用本机服务注册表。手机只取得自己的登录会话；独立设备凭证通过二维码的独立轮询秘密发给电脑，不向手机或 CarryOn 账号服务上传 Codex Token。

`carryon init --input-json` 为桌面共用入口：action 为 status、prepare、poll、known-accounts。prepare 接收 url、autoStart、permissions、name、port、codexHome；已有账号还提供 accountId、sourceDirectory、sourceBindingId。调用返回真实运行、桥接和云端连接状态，不能将 bound 等同于在线。

公开绑定创建按 TCP 来源限制为每分钟 6 次，最多 64 个有效待确认邀请。反向代理下 TCP 来源可能是共享代理，不信任任意 X-Forwarded-For；公网部署需在可信入口配置合理的真实来源限流。已有账号初始化的幂等记录有 1024 条上限，超限明确拒绝，不自动删除记录后重建未知结果。

## 失效绑定恢复

桌面云端条目和成员管理错误页提供「检查绑定」，CLI 再次执行 `carryon init` 使用相同恢复流程。

- 仅云端明确返回 HTTP 403「设备凭证无效」时，进入重新扫码流程。超时、断网和其他错误返回 unverified，可重试检查，不创建替代绑定。
- 多云配置无法确定目标时要求显式选择，不自动取首个云端。
- 新二维码仍使用首次绑定接口，不依赖失效凭证。扫码确认前保留旧连接配置，关闭向导可在有效期内续办。
- 确认后按绑定 ID、云端地址和原凭证指纹条件替换，保留其他云端；并发修改原绑定时拒绝覆盖。重复领取同一结果不重复创建本地条目。
- 手机已确认的结果先保存在本地私有进度文件，再安装连接；安装失败进入 confirming，保留领取的凭证且不受二维码到期清理。临时失败可点「重试」。原绑定并发变化时，可显式选择「应用扫码结果」并确认账号；系统先验证新凭证，再为同一绑定读取新指纹并条件替换。自动轮询不会覆盖并发修改。
- 旧连接停止失败时保持原配置；写盘失败时恢复原连接。新凭证已保存后的恢复应继续使用新凭证，不能通过回退文件让云端已撤销的凭证重新有效。

JSON 初始化可传 bindingId 指定待检查绑定；apply-confirmed 是对应显式确认的冲突解决动作，仅在已保存扫码结果时可用。桌面定期检查间隔为 30 秒，期间的 status 可传 verify=false 读取已保存进度；生成二维码前仍重新验证。该缓存读不作为云端认证成功的证据。

验证使用 `python3 -m unittest discover -s tests -p test_binding_recovery.py`，包括本地 HTTP 云端扫码确认、离线与运行中替换、多云隔离、重复领取、并发拒绝和落盘失败恢复；不代表真实手机和已安装版本已验收。

## 恢复与未完成边界

本次未迁移真实云端数据。使用隔离测试目录验证；发布前需备份云端配置、account.json、users.json、sessions.json、devices.json、binding-invites.json 及本地完整私有目录。回退旧的单管理员服务会失去多账号访问控制，因此不得把包含新多账号设备的注册表直接交给旧程序公开运行。

独立 app-server 探测验证了独立 CODEX_HOME 下读取文件式本机鉴权、创建探测会话，以及原 Codex 数据库未收录该会话；原鉴权文件未改变。尚未验证完整会话操作、Keychain 鉴权、模型调用后的存储和强制目录/网络/审批隔离，尚未作为可选工作区后端提供。控制会话选择、独立工作区调度、暂不分配的完整桌面向导仍需后续完成。
