# 登录变更验证（2026-09-12）

范围：单管理员账号密码为默认入口；电脑创建二维码，手机扫描并核对云端地址，电脑核对六位确认码后允许或拒绝；会话保留 30 天并支持服务重启恢复。沿用现有设备与远程控制权限，不添加多用户系统。风险 R2，独立审查和目标环境验收仍是发布门禁。

## 本地证据

- `python3 -m unittest discover -s tests -q`：278 项，1 项跳过，其余通过；最终新增的会话过期与旧配置迁移测试另以 `test_console_auth.py` 运行，9 项全部通过。
- `node --test tests/test_console_client.js`：13 项通过。
- `swift test --package-path iOS --scratch-path .runtime/login-swift-build`：24 项通过，包含扫码格式、安全地址和扫码成功后安装同一会话 Cookie。
- `xcodebuild -project iOS/CarryOn.xcodeproj -scheme CarryOn -configuration Debug -sdk iphoneos -derivedDataPath .runtime/login-xcode-build CODE_SIGNING_ALLOWED=NO build`：通过，不签名、不安装。
- `tests/check_login_ui.cjs` 对隔离的真实 HTTP 控制台和两个独立浏览器上下文验证密码错误/成功、刷新恢复、二维码生成、扫码链接、电脑确认、手机登录及默认登录界面。运行需设置 `LOGIN_TEST_URL`，仅使用测试账号 `admin / fixture-password-123`；不指向真实服务。
- `.runtime/login-mobile.png` 与 `.runtime/login-qr.png` 已人工式图像检查；二维码截图通过 Apple Vision 解码。浏览器自动流程验证的是扫码链接，未冒充 iPhone 相机实测。
- Python 编译、JavaScript 语法、最终差异检查通过。测试日志位于 `.runtime/login-*-tests.log`、`.runtime/login-all-python.log`、`.runtime/login-ios-build.log`。

## 未完成门禁

独立审查 Agent 启动时被模型用量限制拒绝，未产生审查结论；实施者自查不替代独立审查。尚未进行真实 iPhone 相机、目标域名 HTTPS/代理和线上账号配置验收。未部署、提交或推送。完成独立审查和人工验收后方可决定发布。

升级与恢复步骤见 [CONSOLE.md](CONSOLE.md)。现有配置需在服务器交互设置管理员账号密码并重启；本次未读取或修改线上凭证。
