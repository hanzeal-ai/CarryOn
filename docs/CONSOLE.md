# example 云端控制台

当前连接使用[工作区初始化](ONBOARDING.md)：电脑生成二维码，手机扫码确认，或选择已确认账号直接分配。默认云端无需填写地址。

现在有两种使用方式，复用同一份 example 界面：

- 本机：`carryon start`，浏览器直接访问本机服务，CarryOn 通过 IPC 连接 Codex App。
- 云端：`carryon-console serve` 同时托管 example、控制台会话和设备连接模块；本机主动建立 WSS。无需另启动独立 Gateway 进程。

```
云端 example 网页 → 云端控制台后端（内置设备连接模块）
                              ↕ WSS，本机主动连接
                      本机 CarryOn → Codex App
```

## 首次本机联调

在项目目录执行，选择新的专用配置目录（已有设备配置可直接跳过 init）：

```sh
python3 -m carryon.console configure --config /tmp/carryon-console-demo/gateway.json --public-url http://127.0.0.1:8780 --username admin
python3 -m carryon.console serve --config /tmp/carryon-console-demo/gateway.json --port 8780
```

configure 会交互询问两次密码（至少 12 位），不回显；配置只保存 scrypt 加盐哈希。浏览器打开 `http://127.0.0.1:8780/`，默认使用设置的账号密码登录。账号与设备 Token、后端 API Token 分离；登录后只使用 HttpOnly、SameSite=Strict Cookie，不把设备长期凭证交给浏览器。HTTPS 环境另启用 Secure Cookie。

部署到 HTTPS 后使用 `carryon init --url https://实际控制台地址` 完成工作区绑定。上面的 loopback HTTP 服务用于后端协议联调；普通初始化要求 HTTPS，不使用跳过 TLS 校验的方式。

控制台支持邀请码注册、账号密码和已登录会话确认的扫码登录，账号按工作区成员权限访问。设备登记持久化到独立可写状态目录，确认后无需重启。退出登录撤销当前 Cookie；会话最长 30 天，摘要和到期时间保存在 `console-state/sessions.json`。管理员密码轮换撤销旧会话；不要通过恢复旧文件绕过撤销记录。

旧配对码兑换 API 继续供既有脚本使用，当前网页不再生成备用配对码。账号初始化/恢复、工作区扫码绑定、注册邀请码和扫码登录分别有自己的凭证与权限边界，不能混用。

## 云端部署与已有网关升级

现有网关配置里的设备凭证可以保留。运行 `configure --username admin` 设置账号密码和准确的外部地址，例如 `https://你的域名/carryon`。随后将服务启动模块由 `carryon.gateway` 改为 `carryon.console`；端口、设备 WSS 地址、原后端 `/v1/` API 与现有反向代理前缀均可保留。必须由反向代理剥离 `/carryon/` 前缀，示例见 deployment/README.md。

`deployment/console.service.conf` 是现有服务的可选 systemd drop-in 模板，应用前先备份配置并完成审查。不要启动两个进程争用 8780。部署账号的流水线不自动覆盖特权服务配置；本次代码修改不会自动切换服务器。configure 的密码只通过不回显的交互提示输入，不通过命令行参数传入。旧 `consoleToken` 配置在迁移前仅供旧客户端继续使用；设置账号密码时移除 `consoleToken`，新版登录界面使用账号密码。

原生 bridge 开关仍只在本机管理。云端下发的任务和审批都受本机 control 授权与同一套 requestId/Journal 约束。Web、移动 Web 与 iOS 通过 `/console/devices/{deviceId}/ws` 消费设备事件（Cookie 登录、同源 Origin 校验、15 秒心跳、断线重新订阅），不直接连接本机端口；离线期间不排队重发任务。不同设备的浏览器待确认请求 ID 分开保存，切换设备不会误投到另一台电脑。

## 接入自己的后端

- 设备协议、连接注册与请求转发仍由 `carryon.gateway.Gateway` / `Device` 提供，Gateway 支持传入自定义 Handler。
- `carryon.console.ConsoleServer` 展示了在同一进程中组合设备传输、网页托管与后端登录会话。
- 替换 `ConsoleHandler` 的登录与设备授权为自己的账户系统；浏览器只能访问已授权设备，设备 API Token 应留在后端。
- `cloud-console-client.js` 是 example 的云端传输适配层；本地 `client.js` 的独立使用能力保留。
- `carryon.gateway` 仍是无网页的独立协议示例，可供已有后端的开发者联调，不是普通用户必须部署的组件。

## 验证边界

隔离测试使用真实 HTTP/WS 和假 Codex IPC，不访问用户真实会话。覆盖控制台登录/退出、来源校验、Cookie、设备授权、配对码单次使用/过期、远程只读、订阅和离线；浏览器检查登录、设备列表、会话读取、只读操作禁用及连接指引。上线前仍需对新的登录/配对协议做独立 R2 审查，并验证目标域名 HTTPS/Cookie/代理路径。本侧会话不操作主任务的部署、GitHub 或现有 Agent。

## 工作区绑定与权限切换

新工作区通过 `carryon init` 或桌面端初始化生成二维码，在已登录 CarryOn iOS App 上确认账号与权限。默认云端无需手填地址；自托管使用 CLI `init --url HTTPS地址`。已有账号可在电脑端直接确认分配，详见[初始化](ONBOARDING.md)。

已连接时，在对应云端绑定中切换「允许远程控制」，无需重新绑定。云端不能替电脑授权。网页只提供当前扫码绑定指引，不再提供备用配对码生成入口。

旧 `cloud connect` 连接申请和 `cloud pair` 协议为现有脚本保留，未完成申请仍可在「连接申请」核对与处理；这不属于新用户初始化流程。

本机重新运行 `carryon start` 启动一个新服务时，如果已有云端连接配置，会自动开启桥接。已经运行的服务不会因再次执行 start 而重新打开已手动关闭的桥接；`carryon open` 仅打开页面。

会话的停止、补充指令、编辑、设置和排队操作集中在顶部「会话操作」菜单。原生 `item/tool/requestUserInput` 请求会弹出问题窗口，支持选择建议答案或输入文本；可以暂时关闭并从「回答 Codex 的问题」重新打开。只读连接无法提交，服务端仍验证请求 ID 和指纹，已处理的请求不能重复回应。


### 会话 WebSocket 协议

连接 `/console/devices/{deviceId}/ws`，首帧发送 `{type:"subscribe", subscription:"客户端唯一ID", threadId, threadIds}`。响应 `{type:"update", revision, subscription, body}`，body 复用设备实时投影。服务器每 15 秒空闲发送 `{type:"ping"}`，客户端回复 `{type:"pong"}`；45 秒无消息关闭并重新订阅。新连接获取当前快照，旧订阅的迟到响应不得覆盖当前会话。会话注销、过期或设备撤销会关闭订阅。

Cookie 与 HTTP 控制台共享，Origin 必须匹配部署源，地址不接受查询参数。提交、登录、附件读取和目录查询仍走 HTTP；已有 HTTP streams API 保留供其现有消费者使用。连接申请与设备目录刷新保持现有 HTTP 行为。

## 扫码登录

1. 在已登录的电脑网页账户菜单中选择「扫码登录其他设备」。
2. iOS 登录页点「扫码登录」，扫描电脑二维码；核对显示的云端地址后继续。移动 Web 可用系统相机扫描并打开链接，也可在浏览器支持时直接使用登录页相机入口。
3. 两端显示同一六位确认码，在电脑核对后选择「允许登录」或「拒绝」。扫码本身不会获得会话。

二维码 3 分钟有效，一次仅允许一个扫描端领取；关闭电脑弹窗、重新生成、邀请人退出、过期或服务重启会取消尚未完成的请求。只允许创建邀请的登录会话确认；重复领取成功响应复用同一会话，退出后不能重新领取。二维码通过 URL fragment 传递，不发送给 Web 服务器或外部二维码服务。

密码验证每分钟最多 10 次（服务端全局限制，不信任代理传来的 IP）；密码或账号错误使用统一响应。扫码通过现有同源检查，授权后进入发起账号的会话和工作区权限，不改变本机远程控制授权。

### 升级和恢复

先备份现有配置和 `console-state`，在目标服务器交互执行：

```sh
python3 -m carryon.console configure --config /实际路径/gateway.json --public-url https://你的域名/carryon --username admin
```

部署新代码并重启后使用该账号密码。修改密码也用同一命令；不需要清除设备登记。发布需要另行授权和独立审查。回滚时恢复升级前代码与配置，保留设备登记和 Journal；旧版本不读取新会话文件，需重新登录。不要仅恢复旧会话文件来撤销退出记录。

二维码渲染使用本地 `qrcode.js`（qrcode-generator 1.4.4，MIT，Kazuhiko Arase），不新增 Python 运行依赖；来源与许可证见 [第三方二维码组件](THIRD-PARTY-QR.md)。

## 在本机 CLI 管理管理员账号

管理员账号初始化和改密使用下面的 CLI 命令，直接连接云端，不要求本机桥接服务运行，也不会开启远程控制。当前桌面端的账号相关入口是工作区使用者管理及注册邀请码。

首次设置需要服务器管理员生成一次性凭证。现有部署使用服务账号执行（凭证显示于当前终端，不要写入脚本或日志）：

```sh
cd /opt/carryon/current
sudo -u carryon /usr/bin/python3.11 -m carryon.console bootstrap \
  --config /etc/carryon/gateway.json --state-dir /var/lib/carryon-console
```

凭证有效期 10 分钟，仅能成功使用一次；重新生成立即替换旧凭证。已有管理员账号时拒绝生成。全新部署需加 `--public-url https://实际云端地址`，再用同一 config/state-dir 启动服务；没有默认密码或空口令登录。

在本机交互终端运行：

```sh
carryon cloud account status --url https://实际云端地址
carryon cloud account setup --url https://实际云端地址
carryon cloud account change --url https://实际云端地址
```

`setup` 提示输入初始化凭证、账号和两次密码；`change` 先输入当前账号密码，再输入新账号密码。密码 12–256 字符。凭证及密码不回显、不接受命令行密码参数、不在本机持久保存。自动化原生调用可使用 CLI 的 `--input-json` 标准输入通道。HTTPS 必须通过证书及主机名验证；拒绝重定向、不使用环境 HTTP 代理、不自动重试写操作。超时后先验证新账号能否登录，不能把响应丢失视为未保存。

云端 `GET /console/account` 仅返回 `configured`。`POST /console/account/setup` 使用 `setupToken/username/password`；`POST /console/account/change` 使用 `currentUsername/currentPassword/username/password`。这些是原生客户端管理接口，拒绝携带 Origin 的浏览器请求；Cookie、设备 Token、旧 consoleToken 都不能替代初始化凭证或当前密码。认证尝试与登录共用每分钟 10 次的限制。

设置成功立即生效，无需重启。所有旧登录、二维码、未兑换配对码失效，若部署包含 APNs 扩展，旧账号权限下的推送登记随认证版本失效；设备登记和本机远程控制授权保持原值。已经通过授权并进入执行的在途请求不能撤回。

账号哈希保存在服务可写的 `state-dir/account.json`，权限为 0600，初始化凭证仅保存摘要。账号和新的随机撤销版本在同一文件中原子提交，文件和父目录完成 fsync 后才报告成功。仅恢复旧 gateway.json 也会保留当前撤销版本，旧登录不会复活（APNs 扩展也需使用同一认证版本）；account.json 属于不可当作缓存删除或回滚的授权数据。记录绑定只读 gateway.json 中的恢复认证材料；不会让服务获得修改 `/etc` 配置的权限。服务器 `configure --username` 仍是忘记密码的恢复入口，设置新的认证材料并重启后，旧远程账号记录不再生效。备份/恢复必须将 gateway.json、account.json 与会话状态作为同一授权状态处理。

回退到不支持 account.json 的旧版本会恢复旧 gateway.json 的认证方式，**不能只切换旧代码**。需由管理员先停止服务，私密备份当前配置与状态，在服务器 `configure --username` 设置新的恢复账号并确认目标版本支持，再启动并验证旧登录全部失效。不要恢复旧账号或旧会话文件来修复登录问题。

## 桌面端与 CLI 显示手机登录二维码

网页版已登录账号可使用「扫码登录其他设备」，或通过下列 CLI 命令生成登录二维码。手机扫码后在发起端核对确认码并批准或拒绝；不要将登录二维码与工作区绑定二维码混用。

```sh
carryon cloud qr --url https://实际云端地址
```

CLI 交互读取账号密码，在终端显示二维码。扫描后输入手机上的六位确认码允许，直接回车拒绝。二维码 3 分钟有效；退出或异常结束会尝试撤销临时电脑登录，即使进程崩溃，这个临时登录最多存活 5 分钟。网络错误不自动重放批准操作。

macOS 终端二维码复用安装包内的 qrcode.js，通过系统 JavaScriptCore 生成，不需要 Node；网页二维码使用本地 qrcode.js。两者共用现有云端 QR 创建、领取、电脑确认及兑换协议，二维码不包含账号密码。`cloud qr --input-json` 保留为原生程序的私有交换通道，响应包含短期电脑会话，不能转存到日志。
