# 多设备与多云端绑定

同一本机可绑定多个云端，每个绑定独立保存凭证、控制授权与连接状态。默认使用 CarryOn 云端；自托管及多云场景需要显式选择目标。新账号仅能访问已授予权限的工作区，工作区内目前不按项目或会话划分权限。

## 用户流程

1. CLI 执行 `carryon init`，或在桌面「添加工作区」后进入绑定向导。
2. 选择权限与是否自动启动，生成二维码，用已登录的 CarryOn iOS App 扫码核对账号和权限后确认。电脑已有同云端已确认账号时可直接分配。
3. CLI 或桌面保存绑定；按选项自动启动。再次打开可以继续同一初始化进度。
4. 添加其他云端使用 `carryon init --url HTTPS地址`，继续使用同一套扫码绑定。
5. 修改权限、解绑或恢复失效绑定时，明确选择对应云端，不影响其他绑定。

## CLI

```sh
carryon init
carryon init --url https://你的云端域名/carryon
carryon cloud status
carryon cloud control --binding-id 绑定ID --allow-control
carryon cloud disconnect --binding-id 绑定ID
```

多个本地工作区分别指定 `--state-dir`。默认无需先执行 start 或 bridge on。初始化的绑定状态持久保存；绑定完成不代表 Codex 已就绪，运行状态单独检查。失败与恢复详见 [初始化和工作区授权](ONBOARDING.md)。

已有自托管配置的目标地址会被保留；新地址不会被误当作已有绑定直接返回成功。正在等待扫码或待应用确认结果时不切换目标，指定旧绑定恢复时也不能更改它的云端地址。

旧 `cloud connect` 申请、`cloud pair` 兑换，以及直接配置 WSS 设备凭证的接口保留给既有外部脚本。当前桌面/Web/iOS 正常连接入口不再使用这些方式；旧申请仍可在云端「连接申请」中处理。

## 状态与失败语义

- 云端登记记录：`--state-dir/devices.json`，原子替换写入、0600 权限；启动时以该文件为权威。第一次登记前从旧配置中的 devices 导入，后续不再将被移除的旧设备从配置中复活。
- 本机 `cloud.json` 为 version=2，bindings 按独立 ID 保存配置。每条连接共用同一个 Bridge、Journal 和原生会话状态。
- 工作区二维码确认和电脑领取分离，重复领取不重复创建设备。电脑保存已确认结果后，安装失败可继续恢复，不因二维码到期丢弃授权结果。
- 扫码绑定创建限制为每分钟 6 次，最多 64 个有效待确认邀请。本机最多绑定 16 个云端，同一规范化设备地址不允许重复绑定。旧连接申请另有独立限流。
- 云端提交的 requestId 按本机绑定 ID 隔离；Journal 保存 sourceBinding/sourceRequestId。云端 HTTP 查询和实时订阅仅展示该绑定的投递记录，本机仍可查看全部记录。会话原生历史仍共享，因此其他云端的任务内容可能出现在共同可见的会话中。
- 解除本机绑定或变更权限会取消旧连接的待发送授权；本机检测到云端连接断开时也使该通道待发送请求失效，重连不会恢复旧请求的授权。最终原生写入前再次验证。
- 云端移除设备先持久撤销凭证，再关闭连接。撤销到达本机之前，在途请求可能已执行；删除响应和页面提示要求在本机核对，不能声称跨网络瞬时撤回。已被原生接收的操作不能撤回，也不能自动重发。
- 离线不排队补发任务，超时结果不确定时沿用原 requestId 查询。不同云端同时操作同一会话由共享 Bridge 的既有门禁协调；不承诺与原生 App 跨窗口原子操作。
- 新绑定、新凭证不继承旧绑定的请求命名空间。迁移前未标明来源的旧请求留在本机 Journal，可在本机核对；不会猜测其归属并暴露给某个云端。

## 部署准备

首次可直接运行 `python3 -m carryon.console configure --config /path/gateway.json --public-url https://your-host/carryon` 创建空设备控制台配置，无需 gateway init 预登记设备。

云端运行 `python3 -m carryon.console serve --config /path/gateway.json --state-dir /path/writable-console-state --port 8780`。状态目录必须由服务用户可写；默认是配置文件同级 `console-state`。只读 systemd 服务应单独配置可写 StateDirectory，不能给整个配置目录放宽写权限。运行期新增设备不再编辑 gateway.json。

只有服务入口切换、状态目录权限、HTTPS/WSS 反向代理路径都正确时，线上才能使用新流程。源码变更不自动修改 systemd/Nginx 或重启现有服务。网关仍是单进程，不能直接随机负载均衡到多个独立实例。

## 验证与恢复

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_client.js tests/test_console_client.js tests/test_cloud_settings.js
python3 -m compileall -q carryon examples tests
python3 tests/serve_multi_cloud_smoke.py
```

浏览器夹具仅监听 loopback，使用假原生 IPC。夹具中的 HTTPS 输入映射到本机 HTTP，专用于页面流程，不能用它声称生产 TLS/反向代理已验收。Ctrl+C 停止夹具。

首次迁移本机 cloud.json 前保存 `cloud-v1-backup.json`，其中含旧凭证，应保持私有。恢复时先停止服务，备份当前 version=2 配置和云端 devices.json，再恢复旧程序与对应旧 cloud.json。旧程序只能恢复一个旧绑定；不能用旧格式表达新增的多个绑定。已撤销的凭证不要通过恢复备份重新启用。保留 jobs.sqlite，不删除 uncertain 请求或通过更换 ID 自动重发。无需迁移或改写 Codex 数据。
