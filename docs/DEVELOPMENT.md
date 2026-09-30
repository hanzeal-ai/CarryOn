# 开发、构建与验收

## 开发运行

运行时仅用 Python 标准库。源码入口：`python3 -m carryon start`；开发前台入口：`python3 -m carryon serve --port 8770 --state-dir /tmp/carryon-dev`。隔离目录应保留到所有 uncertain 请求核对完毕，不能拿更换目录当作重试策略。

模块职责和依赖方向见 [项目结构](ARCHITECTURE.md)；会话 Owner 的创建、加载、权限与恢复边界见 [OWNER.md](OWNER.md)。

## 构建

在目标 macOS 架构上运行：

```sh
python3 -m venv .runtime/build-env
.runtime/build-env/bin/python -m pip install -r requirements-build.txt
.runtime/build-env/bin/python scripts/build_release.py
```

输出 `dist/`：Mac `.app`、DMG、独立 CLI tar.gz、Python wheel/sdist、SHA256SUMS。静态页面与 native_contracts.json 包含在产物中，.runtime、tests 和个人凭证不会放入可执行安装包。wheel 构建由 setup.py 从根目录权威静态文件复制，不需要提前生成 web 目录。

构建脚本会覆盖 dist/build 下同名产物；它们是构建目录，不应放用户数据。Python 是按架构打包的，arm64 本机产物不能声称已验证 Intel。升级和回滚必须保留用户状态目录。

正式分发需要配置 `CARRYON_SIGN_IDENTITY` 后构建，使用自己的 Apple Developer 账号执行 notarization/stapling，再在干净设备验证。脚本不会自动上传或发布包。本机没有完成公证时产物只供内部验收，不宣称陌生用户可无提示一键安装。

## 验证

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_*.js
# 本机 Codex App 升级后，先做只读协议检查：
python3 scripts/check_native_contracts.py
python3 -m compileall -q carryon examples tests
node --check app.js
node --check client.js
node --check operations.js
node --check timeline.js
# 对实际独立可执行文件重复 CLI 启停、单实例与资源验证：
CARRYON_TEST_EXECUTABLE="$PWD/dist/carryon/carryon" python3 -m unittest discover -s tests -p test_cli.py -v
```

cloud 测试使用临时网关、临时 SQLite 与模拟原生 IPC，验证真实 HTTP/WS 通道、设备权限、只读/控制、本机撤销、幂等、订阅、离线和错误凭证。不会向真实 Codex 投递任务。生产 WSS、证书、代理、真实云端延迟和实际 App 版本仍需目标环境验收。

任务风险 R2：涉及公开接口、远程访问与生命周期。发布前需独立审查与人类验收；创建安装产物不等于部署或批准生产使用。已生成代码的恢复副本保存在本项目 .runtime/source-backups/，无需迁移原生 Codex 数据。

桌面端使用系统 SwiftUI（macOS 13+），由 `desktop/` 下的 Swift 文件实现，构建需要 Xcode 命令行工具。窗口通过打包的 `carryon-service` 执行相同 CLI 命令，配置与服务共用；开发检查可用 `CARRYON_DESKTOP_CLI` 指向待验证的 CLI 可执行文件。

打包后执行 `python3 tests/run_desktop_smoke.py`，使用隔离目录和禁止连接的测试绑定，验证桌面模型经应用内 CLI 修改权限、独立 CLI 读取并改回、桌面刷新看到相同状态。此测试不替代真实桌面窗口点击、云端 HTTPS 配对和人工独立审查。

多工作区回归同样使用 `python3 tests/run_desktop_smoke.py`：启动两个真实隔离实例，验证发现、切换、跨工作区配置隔离、doctor、独立停止以及桌面创建的前台服务退出生命周期。`tests/test_services.py` 覆盖并发登记、规范路径、旧进程认证发现和导入参数保留。

## Web控件样式

页面由现有DOM和事件处理代码拥有；`web/src/control-styles.js`仅应用Tailwind样式，不替换节点或挂载React。模型和操作等动态区域继续由各自模块负责。修改样式后运行：

```sh
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
cp .runtime/web-build/shadcn-ui.js .runtime/web-build/shadcn.css .
node tests/check_control_styles.cjs
```

浏览器检查需要可用的Playwright；可用`PLAYWRIGHT_MODULE`指定已安装模块路径。根目录两个静态文件为打包入口，应与本次构建产物同步。
