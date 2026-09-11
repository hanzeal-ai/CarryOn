# 多设备与多云端绑定

通过 CLI 或桌面端输入云端 HTTPS 地址并申请连接；登录云端的管理员在「连接申请」核对设备名称、时间和两端确认码，点击确认后自动登记设备。本机后台领取独立设备凭证，开启桥接并建立出站 WSS。无需预先填写设备 ID/Token，不需要端口映射。

同一云端可以接收多台本机；同一本机在「已连接云端」中添加多个云端，每个绑定独立显示连接状态、设置只读/远程控制、解除绑定。默认只读。已绑定云端都可查看本机桥接中的全部会话；本版本不提供按项目或会话划分的可见范围。设备名称仅是展示信息，不能作为认证依据。

## 用户流程

1. 启动本机服务，通过 CLI 的 `cloud connect` 或桌面端「云端连接」填写地址并申请，按需允许远程控制。
2. 云端「连接申请」按钮显示待处理数量，点击后核对确认码，确认或拒绝。确认后无需选择预登记设备。
3. 本机后台自动绑定。关闭 CLI 命令或桌面窗口不终止申请；本机服务停止或申请超过五分钟时需重新申请。
4. 添加其他云端重复以上步骤。更改权限和解除绑定必须选择对应项，不影响其他连接。
5. 云端账户菜单可移除当前设备，使其凭证失效并关闭连接。需要再次接入时，本机解除旧绑定后重新申请。

云端通知通过登录页面每五秒刷新，不包含短信、系统推送或邮件。单管理员控制台中所有登录会话均有设备管理权限；多租户账号与组织归属不在本次范围内。

## CLI 连接

先启动本地服务，然后执行（地址包含实际部署的路径前缀）：

```sh
connectnow cloud connect --url https://你的云端域名/connectnow
connectnow cloud status
```

命令显示核对码和云端链接；登录云端，在「连接申请」核对并确认即可。核对码用于比较两端申请，无需输入一次性配对码。命令返回仅表示申请已提交；本地服务会继续等待确认并自动绑定，请保持服务运行，五分钟内完成确认。`cloud status` 查看绑定与连接状态；`cloud link-status` 查看最新申请的等待、成功、过期或失败状态。申请状态只在当前服务进程中保留，服务重启后为 idle，已保存绑定仍可用。

默认只读，需要远程控制时在 `cloud connect` 后加 `--allow-control`。两个实例分别使用自己的数据目录：

```sh
connectnow cloud connect --state-dir ~/.connectnow-test/a --url https://你的云端域名/connectnow
connectnow cloud connect --state-dir ~/.connectnow-test/b --url https://你的云端域名/connectnow
```

查询状态和断开连接也需带对应的 `--state-dir`。已有设备凭证仍可通过 `cloud connect --url wss://你的云端域名/connectnow/device --device-id 设备ID --token-file /路径/device-token.txt` 连接；`cloud pair` 用于旧的一次性配对码流程。

## 状态与失败语义

- 云端登记记录：`--state-dir/devices.json`，原子替换写入、0600 权限；启动时以该文件为权威。第一次登记前从旧配置中的 devices 导入，后续不再将被移除的旧设备从配置中复活。
- 本机 `cloud.json` 为 version=2，bindings 按独立 ID 保存配置。每条连接共用同一个 Bridge、Journal 和原生会话状态。
- 凭证领取允许在申请的五分钟有效期内使用同一秘密重试，始终返回同一绑定，不重复创建设备。管理员重复确认返回同一结果；拒绝后不能确认。未登录不能查看或处理申请。
- 云端申请限制每分钟 30 次，最多保留 64 个未过期请求；最多登记 256 台设备。本机最多绑定 16 个云端，同一规范化设备地址不允许重复绑定。
- 云端提交的 requestId 按本机绑定 ID 隔离；Journal 保存 sourceBinding/sourceRequestId。云端 HTTP 查询和实时订阅仅展示该绑定的投递记录，本机仍可查看全部记录。会话原生历史仍共享，因此其他云端的任务内容可能出现在共同可见的会话中。
- 解除本机绑定或变更权限会取消旧连接的待发送授权；本机检测到云端连接断开时也使该通道待发送请求失效，重连不会恢复旧请求的授权。最终原生写入前再次验证。
- 云端移除设备先持久撤销凭证，再关闭连接。撤销到达本机之前，在途请求可能已执行；删除响应和页面提示要求在本机核对，不能声称跨网络瞬时撤回。已被原生接收的操作不能撤回，也不能自动重发。
- 离线不排队补发任务，超时结果不确定时沿用原 requestId 查询。不同云端同时操作同一会话由共享 Bridge 的既有门禁协调；不承诺与原生 App 跨窗口原子操作。
- 新绑定、新凭证不继承旧绑定的请求命名空间。迁移前未标明来源的旧请求留在本机 Journal，可在本机核对；不会猜测其归属并暴露给某个云端。

## 部署准备

首次可直接运行 `python3 -m connectnow.console configure --config /path/gateway.json --public-url https://your-host/connectnow` 创建空设备控制台配置，无需 gateway init 预登记设备。

云端运行 `python3 -m connectnow.console serve --config /path/gateway.json --state-dir /path/writable-console-state --port 8780`。状态目录必须由服务用户可写；默认是配置文件同级 `console-state`。只读 systemd 服务应单独配置可写 StateDirectory，不能给整个配置目录放宽写权限。运行期新增设备不再编辑 gateway.json。

只有服务入口切换、状态目录权限、HTTPS/WSS 反向代理路径都正确时，线上才能使用新流程。源码变更不自动修改 systemd/Nginx 或重启现有服务。网关仍是单进程，不能直接随机负载均衡到多个独立实例。

## 验证与恢复

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_client.js tests/test_console_client.js tests/test_cloud_settings.js
python3 -m compileall -q connectnow examples tests
python3 tests/serve_multi_cloud_smoke.py
```

浏览器夹具仅监听 loopback，使用假原生 IPC。夹具中的 HTTPS 输入映射到本机 HTTP，专用于页面流程，不能用它声称生产 TLS/反向代理已验收。Ctrl+C 停止夹具。

首次迁移本机 cloud.json 前保存 `cloud-v1-backup.json`，其中含旧凭证，应保持私有。恢复时先停止服务，备份当前 version=2 配置和云端 devices.json，再恢复旧程序与对应旧 cloud.json。旧程序只能恢复一个旧绑定；不能用旧格式表达新增的多个绑定。已撤销的凭证不要通过恢复备份重新启用。保留 jobs.sqlite，不删除 uncertain 请求或通过更换 ID 自动重发。无需迁移或改写 Codex 数据。
