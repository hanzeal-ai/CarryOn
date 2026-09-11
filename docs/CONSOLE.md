# example 云端控制台

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
python3 -m connectnow.gateway init --config /tmp/connectnow-console-demo/gateway.json --device-id my-mac
python3 -m connectnow.console configure --config /tmp/connectnow-console-demo/gateway.json --public-url http://127.0.0.1:8780
python3 -m connectnow.console serve --config /tmp/connectnow-console-demo/gateway.json --port 8780
```

浏览器打开 `http://127.0.0.1:8780/`，使用配置文件中新生成的 `consoleToken` 登录。此凭证与设备 Token、后端 API Token 分离；登录后只使用 HttpOnly、SameSite=Strict Cookie，不把设备长期凭证交给浏览器。HTTPS 环境另启用 Secure Cookie。

选择 `my-mac`，点击“获取配对码”。配对码 5 分钟过期、仅能兑换一次。然后在本机执行：

```sh
python3 -m connectnow start
python3 -m connectnow cloud pair --url http://127.0.0.1:8780 --dev-local
# 在不回显的提示中输入配对码。
```

本机必须开启桥接。默认远程只读；如确实需要云端投递和操作，配对命令增加 `--allow-control`。生产 HTTPS 环境也可以在本机页面“云端接入与本地服务”中填写控制台地址与配对码，不必运行配对命令。原手工填写设备 ID/Token 的方式保留在“高级连接配置”。

这不是扫码登录 SaaS：example 使用单管理员登录凭证，设备在配置文件的 `devices` 中预先登记；尚未提供多用户账户、设备创建/删除页面和组织权限。配置中新加设备后需重启云端服务。退出登录立即失效当前 Cookie，会话最长 12 小时；服务重启会失效全部浏览器会话和未使用配对码。云端订阅绑定登录会话，退出时释放；网页关闭后超过 60 秒未续读的订阅自动回收。重新登录不丢失本机 Journal。

## 云端部署与已有网关升级

现有网关配置里的设备凭证可以保留。运行 configure 添加独立 consoleToken 和准确的外部地址，例如 `https://你的域名/connectnow`。随后将服务启动模块由 `connectnow.gateway` 改为 `connectnow.console`；端口、设备 WSS 地址、原后端 `/v1/` API 与现有反向代理前缀均可保留。必须由反向代理剥离 `/connectnow/` 前缀，示例见 deployment/README.md。

`deployment/console.service.conf` 是现有服务的可选 systemd drop-in 模板，应用前先备份配置并完成审查。不要启动两个进程争用 8780。部署账号的流水线不自动覆盖特权服务配置；本次代码修改不会自动切换服务器。configure 不向终端输出长期凭证，请用私有文件交付给管理员。

原生 bridge 开关仍只在本机管理。云端下发的任务和审批都受本机 control 授权与同一套 requestId/Journal 约束。浏览器通过后端长轮询消费设备事件，不直接连接本机端口；离线期间不排队重发任务。不同设备的浏览器待确认请求 ID 分开保存，切换设备不会误投到另一台电脑。

## 接入自己的后端

- 设备协议、连接注册与请求转发仍由 `connectnow.gateway.Gateway` / `Device` 提供，Gateway 支持传入自定义 Handler。
- `connectnow.console.ConsoleServer` 展示了在同一进程中组合设备传输、网页托管与后端登录会话。
- 替换 `ConsoleHandler` 的登录与设备授权为自己的账户系统；浏览器只能访问已授权设备，设备 API Token 应留在后端。
- `cloud-console-client.js` 是 example 的云端传输适配层；本地 `client.js` 的独立使用能力保留。
- `connectnow.gateway` 仍是无网页的独立协议示例，可供已有后端的开发者联调，不是普通用户必须部署的组件。

## 验证边界

隔离测试使用真实 HTTP/WS 和假 Codex IPC，不访问用户真实会话。覆盖控制台登录/退出、来源校验、Cookie、设备授权、配对码单次使用/过期、远程只读、订阅和离线；浏览器检查登录、设备列表、会话读取、只读操作禁用和配对码弹窗。上线前仍需对新的登录/配对协议做独立 R2 审查，并验证目标域名 HTTPS/Cookie/代理路径。本侧会话不操作主任务的部署、GitHub 或现有 Agent。
