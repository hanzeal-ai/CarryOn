# example 云端控制台

当前推荐使用[多设备与多云端绑定](MULTI_CLOUD.md)：本机输入地址申请，云端收到通知并确认后动态登记设备。以下一次性配对码用于已有设备的备用接入。

现在有两种使用方式，复用同一份 example 界面：

- 本机：`connectnow start`，浏览器直接访问本机服务，ConnectNow 通过 IPC 连接 Codex App。
- 云端：`connectnow-console serve` 同时托管 example、控制台会话和设备连接模块；本机主动建立 WSS。无需另启动独立 Gateway 进程。

```
云端 example 网页 → 云端控制台后端（内置设备连接模块）
                              ↕ WSS，本机主动连接
                      本机 ConnectNow → Codex App
```

## 首次本机联调

在项目目录执行，选择新的专用配置目录（已有设备配置可直接跳过 init）：

```sh
python3 -m connectnow.console configure --config /tmp/connectnow-console-demo/gateway.json --public-url http://127.0.0.1:8780
python3 -m connectnow.console serve --config /tmp/connectnow-console-demo/gateway.json --port 8780
```

浏览器打开 `http://127.0.0.1:8780/`，使用配置文件中新生成的 `consoleToken` 登录。此凭证与设备 Token、后端 API Token 分离；登录后只使用 HttpOnly、SameSite=Strict Cookie，不把设备长期凭证交给浏览器。HTTPS 环境另启用 Secure Cookie。

生产环境推荐在本机输入 HTTPS 控制台地址申请，云端确认后自动登记，无需预建设备。本机 HTTP 联调用于协议测试；若配置中已有设备，可选择设备点击“获取备用配对码”。配对码 5 分钟过期、仅能兑换一次，然后在本机执行：

```sh
python3 -m connectnow start
python3 -m connectnow cloud pair --url http://127.0.0.1:8780 --dev-local
# 在不回显的提示中输入配对码。
```

本机必须开启桥接。默认远程只读；如确实需要云端投递和操作，配对命令增加 `--allow-control`。桌面端采用 HTTPS 地址申请连接；备用配对码和已有设备凭证通过 CLI 使用。

这不是扫码登录 SaaS：example 使用单管理员登录凭证，设备可以通过连接申请动态登记，并在云端移除；尚未提供多用户账户和组织权限。设备登记持久化到独立可写状态目录，确认后无需重启服务。退出登录立即失效当前 Cookie，会话最长 12 小时；服务重启会失效全部浏览器会话和未使用配对码。云端订阅绑定登录会话，退出时释放；网页关闭后超过 60 秒未续读的订阅自动回收。重新登录不丢失本机 Journal。

## 云端部署与已有网关升级

现有网关配置里的设备凭证可以保留。运行 configure 添加独立 consoleToken 和准确的外部地址，例如 `https://你的域名/connectnow`。随后将服务启动模块由 `connectnow.gateway` 改为 `connectnow.console`；端口、设备 WSS 地址、原后端 `/v1/` API 与现有反向代理前缀均可保留。必须由反向代理剥离 `/connectnow/` 前缀，示例见 deployment/README.md。

`deployment/console.service.conf` 是现有服务的可选 systemd drop-in 模板，应用前先备份配置并完成审查。不要启动两个进程争用 8780。部署账号的流水线不自动覆盖特权服务配置；本次代码修改不会自动切换服务器。configure 不向终端输出长期凭证，请用私有文件交付给管理员。

原生 bridge 开关仍只在本机管理。云端下发的任务和审批都受本机 control 授权与同一套 requestId/Journal 约束。Web、移动 Web 与 iOS 通过 `/console/devices/{deviceId}/ws` 消费设备事件（Cookie 登录、同源 Origin 校验、15 秒心跳、断线重新订阅），不直接连接本机端口；离线期间不排队重发任务。不同设备的浏览器待确认请求 ID 分开保存，切换设备不会误投到另一台电脑。

## 接入自己的后端

- 设备协议、连接注册与请求转发仍由 `connectnow.gateway.Gateway` / `Device` 提供，Gateway 支持传入自定义 Handler。
- `connectnow.console.ConsoleServer` 展示了在同一进程中组合设备传输、网页托管与后端登录会话。
- 替换 `ConsoleHandler` 的登录与设备授权为自己的账户系统；浏览器只能访问已授权设备，设备 API Token 应留在后端。
- `cloud-console-client.js` 是 example 的云端传输适配层；本地 `client.js` 的独立使用能力保留。
- `connectnow.gateway` 仍是无网页的独立协议示例，可供已有后端的开发者联调，不是普通用户必须部署的组件。

## 验证边界

隔离测试使用真实 HTTP/WS 和假 Codex IPC，不访问用户真实会话。覆盖控制台登录/退出、来源校验、Cookie、设备授权、配对码单次使用/过期、远程只读、订阅和离线；浏览器检查登录、设备列表、会话读取、只读操作禁用和配对码弹窗。上线前仍需对新的登录/配对协议做独立 R2 审查，并验证目标域名 HTTPS/Cookie/代理路径。本侧会话不操作主任务的部署、GitHub 或现有 Agent。

## 简化连接与权限切换

通过 CLI `connectnow cloud connect --url https://控制台地址` 或桌面端「云端连接」申请。登录云端后在「连接申请」查看通知，核对两端确认码，再点击确认。本地服务自动保存绑定并尝试开启桥接；CLI `cloud link-status` 与桌面端均可查看申请结果。申请五分钟过期，轮询秘密与设备 Token 不进入浏览器；同一申请可在有效期内重试领取凭证。

已连接时，在对应云端绑定中勾选或取消「允许此云端远程控制」，点击「保存权限」即可，无需重新配对。此操作会短暂重连设备通道；云端不能改变本机权限。保留「使用一次性配对码」作为备用连接方式。

本机重新运行 `connectnow start` 启动一个新服务时，如果已有云端连接配置，会自动开启桥接。已经运行的服务不会因再次执行 start 而重新打开已手动关闭的桥接；`connectnow open` 仅打开页面。

会话的停止、补充指令、编辑、设置和排队操作集中在顶部「会话操作」菜单。原生 `item/tool/requestUserInput` 请求会弹出问题窗口，支持选择建议答案或输入文本；可以暂时关闭并从「回答 Codex 的问题」重新打开。只读连接无法提交，服务端仍验证请求 ID 和指纹，已处理的请求不能重复回应。


### 会话 WebSocket 协议

连接 `/console/devices/{deviceId}/ws`，首帧发送 `{type:"subscribe", subscription:"客户端唯一ID", threadId, threadIds}`。响应 `{type:"update", revision, subscription, body}`，body 复用设备实时投影。服务器每 15 秒空闲发送 `{type:"ping"}`，客户端回复 `{type:"pong"}`；45 秒无消息关闭并重新订阅。新连接获取当前快照，旧订阅的迟到响应不得覆盖当前会话。会话注销、过期或设备撤销会关闭订阅。

Cookie 与 HTTP 控制台共享，Origin 必须匹配部署源，地址不接受查询参数。提交、登录、附件读取和目录查询仍走 HTTP；已有 HTTP streams API 保留供其现有消费者使用。连接申请与设备目录刷新保持现有 HTTP 行为。
