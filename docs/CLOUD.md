# 接入自定义云端控制台

ConnectNow 主动通过 WSS 连接你的网关，不需要用户配置公网 IP、端口映射或 SSH。本机 HTTP 与云端命令复用 `connectnow.api.dispatch`；原生状态与本地投递日志仍是业务权威。网关不会替代本地权限检查和幂等记录。

```text
你的浏览器控制台 → 你的账号后端 → ConnectNow 网关
                                     ↑ WSS
                               用户电脑 ConnectNow → Codex IPC
```

本项目提供设备连接器、传输协议和可运行的参考网关；没有提供 SaaS 账号系统、自动域名/TLS 部署或公网托管。账号后端应验证登录用户有权访问指定 deviceId，API Token 仅留在后端。设备 Token 只交给对应电脑；两种 Token 不通用。

## 先在本机完成闭环验证

以下网关和设备都只监听/连接 loopback；生产环境必须使用 WSS。

```sh
# 终端 A：在项目根目录启动参考网关。目录应为本次测试专用。
python3 -m connectnow.gateway init --config /tmp/connectnow-demo/gateway.json --device-id my-mac
python3 -m connectnow.gateway serve --config /tmp/connectnow-demo/gateway.json --port 8780

# 终端 B：启动设备服务并绑定。只有显式 --dev-local 才允许本机 ws://。
python3 -m connectnow start
python3 -m connectnow cloud connect \
  --url ws://127.0.0.1:8780/device --device-id my-mac \
  --token-file /tmp/connectnow-demo/device-token.txt --dev-local
python3 -m connectnow cloud status
```

然后在本地页面「开启桥接」。默认云端只读。如确实需要投递、编辑、设置或审批，重新执行 connect 时加入 `--allow-control`，或在本地页面勾选允许远程控制。授权意味着你信任该网关及其账号后端执行这些能力。

断开与清除设备凭证：`connectnow cloud disconnect`。仅取消桥接也会拒绝云端任务操作；云端没有重新开启桥接、绑定网关或停止本地服务的权限。

## 放到自己的云端

在服务器安装本项目 wheel（Python 3.10+），使用 `connectnow-gateway init/serve`，或使用下述协议实现自己的网关。参考网关默认监听 `127.0.0.1:8780`，在其前方配置受信任证书的 HTTPS/WSS 反向代理。设备使用：

```sh
connectnow cloud connect --url wss://你的网关域名/device --device-id my-mac --token-file /本机/device-token.txt
```

也可在本地控制台的「云端接入与本地服务」中填写地址、设备 ID 和设备 Token，无需终端。页面不支持明文公网地址。设备会自动重连，但不会自动重发任务或恢复旧的云端订阅。

参考 Nginx 配置（证书、进程管理与域名由部署方配置）：

```nginx
location /device {
    proxy_pass http://127.0.0.1:8780;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 90s;
}
location /v1/ {
    proxy_pass http://127.0.0.1:8780;
    proxy_read_timeout 35s;
}
```

将 `/v1/` 尽可能限制为自有账号后端可达。网关配置中的每个设备都有独立 `deviceToken` 与 `apiToken`；向配置添加设备后重启参考网关。参考实现为单进程，不支持直接部署多个相互独立的副本；扩容需要实现连接归属与请求路由，不应靠负载均衡随机转发。

## 云端后端 HTTP API

全部接口使用 `Authorization: Bearer <该设备 apiToken>`，JSON 请求体最多 100 KB。不同设备 Token 不能串用。参考网关拒绝带 Origin 的浏览器直连，不提供 CORS；你的前端访问自己的后端。

| 方法 | 路径 | 输入与结果 |
|---|---|---|
| GET | `/v1/devices/{deviceId}` | `{deviceId, online}` |
| POST | `/v1/devices/{deviceId}/request` | `{method,path,body}`，返回本机 HTTP 状态码和原始 JSON |
| POST | `/v1/devices/{deviceId}/streams` | 本地 WS 的 selection 字段，返回 `{streamId}` |
| GET | `/v1/devices/{deviceId}/streams/{streamId}?after=N` | 最多等待 20 秒，返回 `{revision,body}`；body 为原生 update 投影 |
| DELETE | `/v1/devices/{deviceId}/streams/{streamId}` | 释放该订阅 |

request 的 `path` 是 `/api/...` 相对路径，不能提供任意 URL。支持现有会话、历史、队列、请求记录及操作接口，见 [API.md](API.md)。`/api/bridge`、`/api/cloud` 和服务管理接口禁止远端使用；POST 另需本机 control 授权。

Node 后端示例，凭证来自后端环境变量（不打包到浏览器）：

```js
const endpoint = process.env.CONNECTNOW_GATEWAY;
const deviceId = process.env.CONNECTNOW_DEVICE_ID;
const apiToken = process.env.CONNECTNOW_API_TOKEN;
async function deviceRequest(method, path, body) {
  const response = await fetch(`${endpoint}/v1/devices/${encodeURIComponent(deviceId)}/request`, {
    method: 'POST',
    headers: {Authorization: `Bearer ${apiToken}`, 'Content-Type': 'application/json'},
    body: JSON.stringify({method, path, body})
  });
  return {status: response.status, body: await response.json()};
}
// 在你的业务路由中先校验登录身份和设备归属。
const threads = await deviceRequest('GET', '/api/threads');
// 写入须先在本机授权；请求 ID 在业务后端保存，重试必须沿用。
const job = await deviceRequest('POST', `/api/threads/${threadId}/messages`, {
  requestId: savedRequestId, prompt: '你的任务'
});
```

历史实时更新：创建 stream（例如 `{threadId,threadIds:[threadId]}`），循环 GET 携带上次 revision；没有新记录时仍可能返回相同 revision，应继续等待而不是重复渲染。由你的后端通过 SSE/WS 转发给浏览器。每个设备最多 8 个独立 stream，每个 stream 最多 100 条侧边栏订阅。用户离开时 DELETE；设备重连或网关重启后旧 stream 失效，重新创建。

## WSS 设备协议 v1

可以完全替换参考网关，只要实现以下协议。传输为 RFC 6455 UTF-8 JSON；设备发送 masked 帧，网关发送 unmasked 帧。设备命令最大 100 KB，事件/结果最大 32 MiB。网关每 15 秒发送应用 ping；设备返回 pong，连接读超时 45 秒。

设备握手：

```json
{"type":"hello","protocol":"connectnow/1","deviceId":"my-mac","token":"设备凭证"}
```

网关验证设备凭证与归属后回复：

```json
{"type":"ready","protocol":"connectnow/1","deviceId":"my-mac"}
```

认证前设备不上传会话信息。设备凭证不得放 URL。`id`、`deviceId`、`streamId` 使用 1–100 位字母、数字、横线或下划线。

```json
{"type":"request","id":"transport-001","method":"GET","path":"/api/threads"}
{"type":"response","id":"transport-001","status":200,"body":{"threads":[]}}
{"type":"subscribe","id":"transport-002","streamId":"view-1","selection":{"threadId":null,"threadIds":[]}}
{"type":"event","streamId":"view-1","body":{"type":"update","status":{"enabled":true},"subscription":"view-1"}}
{"type":"unsubscribe","id":"transport-003","streamId":"view-1"}
{"type":"ping","id":"heartbeat-1"}
{"type":"pong","id":"heartbeat-1"}
```

subscribe/unsubscribe 均返回相同 id 的 response。传输 id 用于匹配响应；任务的 `body.requestId` 才是持久幂等键，二者不能混用。

## 失败语义与运维边界

- 设备离线：503，参考网关不排队任务。
- 已发出但响应超时/断线：409 + `uncertain:true`，不能认定未执行。保留原 requestId，设备恢复后 GET `/api/jobs/{requestId}` 核对；不要自动生成新 ID。
- 本地 POST 返回 202：仅登记，继续查询 Job 或订阅更新，不能当成 Codex 已完成任务。
- 本机关闭桥接：本地业务门禁拒绝后续操作；关闭云端绑定会断开连接并清除凭证，不会撤销已接收任务。
- 云端可以看到通过其传输的原文、工具输出、设置和审批信息。参考网关不落盘会话内容，但在内存中保留每个订阅的最新快照，释放订阅/设备断线时清除。
- 自有账号后端负责身份、设备归属、会话访问策略、审计和数据保留。参考网关的静态 Token 配置适合自托管验证；生产多租户应接入自己的凭证签发、轮换与撤销体系。
- 参考网关重启后连接与内存订阅丢失，设备自动重连。日志不输出 Token 或任务原文。TLS、证书续期、监控、限流、持续部署与目标环境验收由部署方负责。
