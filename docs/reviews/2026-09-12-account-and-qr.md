# 云端账号与桌面/CLI 扫码登录

范围：R2。云端统一管理账号，服务器 bootstrap 签发 10 分钟一次性初始化凭证；桌面和本机 CLI 设置/修改账号、生成手机登录二维码并核对六位确认码。修改账号需要当前账号密码，不接受设备 Token 或浏览器 Cookie 替代。没有新增运行依赖或自动开启远程控制。

实现：account.json 将账号及撤销 generation 原子提交，文件和父目录 fsync 完成才确认；配置恢复保留 generation，旧会话不能复活。写入发生后目录同步失败返回结果未确认，并立即应用可见的新授权。CLI/桌面共用 HTTPS 传输，凭证通过标准输入，不进命令行参数或本机配置；禁止代理、重定向及自动重放写操作。二维码三分钟、临时电脑登录五分钟有效，关闭撤销邀请但保留已登录手机的独立会话。

独立审查者基于原始源码和可运行测试提出两个问题：恢复旧认证材料可能复活旧授权；账号文件 rename 后未同步父目录。均已修复，审查者独立重跑账号/认证/QR 和原生桌面 smoke 后接受，无剩余 P1/P2。

可复现验证：

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_client.js tests/test_console_client.js tests/test_cloud_settings.js tests/test_notification_client.js
python3 tests/run_account_desktop.py
python3 -m compileall -q carryon deployment
```

新增测试验证单用/过期/并发初始化、错误密码/设备凭证拒绝、持久化失败、恢复后旧会话失效、目录 fsync 失败结果未确认、TLS 信任/主机名/重定向/代理隔离、无自动重试、QR 接受/拒绝/过期/他人会话拒绝。原生 smoke 实际编译 Swift 模型，通过 CLI 标准输入和隔离 HTTPS 服务完成账号设置/修改及 QR 创建/状态/撤销。终端 QR 编码复用包内库，macOS JavaScriptCore 测试通过。

桌面窗口入口及错误态已实际观察；真实手机扫码、正式签名公证和生产登录往返未验证。发布/部署不由本次本地检查自动授予。

恢复：账号/会话文件及已部署 APNs 扩展的推送文件是授权数据，不能作为缓存删除。旧版本不识别 account.json，不能只回退代码；管理员需先备份配置和状态，以支持账号配置的版本重新设置恢复账号，启动后验证旧会话失效。保留设备登记、控制授权及请求历史。完整回滚账号文件/generation 超出本方案可保证的撤销边界，禁止以此恢复登录。
