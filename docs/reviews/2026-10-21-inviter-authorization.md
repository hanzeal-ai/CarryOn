# 邀请码电脑远程授权

目标：桌面或 CLI 生成授权链接，管理员核对指纹并验证身份后授权立即生效，随后原电脑可生成普通账号注册邀请码。实现于现有工作目录，保留其他会话未提交改动；未提交或推送。用户随后明确授权部署、更新本机和创建普通账号，现已完成；见下方交付记录。

风险 R2：新增管理员权限写入入口和持久化授权。本地实现与验证经过独立审查；后续生产发布、更新本机和创建账号已获用户明确授权。

## 权威与影响

- `carryon invate --authorize [--url HTTPS地址]` 输出本机公有 SHA-256 指纹和 `#carryon-inviter=` 链接。私有 issuer token 留在既有本机凭证文件中，不进入链接。链接只指认电脑，不携带管理员权限；打开后清除地址片段，不自动提交。
- 浏览器 `POST /console/inviter/authorize` 必须同源，提供管理员账号、密码、64 位小写指纹和 `confirm: true`。复用 `ConsoleAuth.verify` 与节流；普通用户、Cookie 单独凭证、设备凭证、无 Origin 和跨源请求均不能授权。管理员凭证只在此次 HTTPS 请求中使用；关闭或请求结束清空密码输入。
- 日常授权保持唯一生成电脑，立即替换。账号注册及邀请码消费仍走原有契约，不给新账号管理员权限或工作区权限。
- `inviter_authorization.issuer_hash` 是生成邀请码的授权读取入口。状态目录保存 `inviter-<source>.json`，source 绑定服务器恢复账号来源、初始配置指纹及恢复代次。无此记录时使用现有配置指纹；存在但损坏时拒绝请求，不静默恢复旧授权。
- 原有 `authorize-inviter` 作为服务器恢复命令保留，每次产生新恢复代次，包括恢复同一指纹；旧代次记录保留用于调查。新代次无需读取损坏旧文件。远程更新不修改只读 gateway 配置。
- 授权写入与发码读取共用 `account.lock`；原子文件替换，成功前同步目录，幂等确认也同步。提交后存储错误返回不确定结果，先回原电脑核对是否可发码，不自动重放。其他服务实例从同一文件读取有效授权。
- 新增 Web 资源进入统一 ASSETS 和 wheel；桌面入口复用同一 CLI，不复制业务规则。无生产依赖新增。

## 恢复与发布

首次使用需要发布云端代码和桌面/CLI 新版本。发布前备份现有 gateway 配置与完整 state-dir，并核对服务实际路径和持久目录权限。升级发布需要另行授权。

若要恢复某台电脑，在服务器用已有 `authorize-inviter --config ... --issuer-hash ...` 命令产生新代次，再重启云端服务。日常远程授权无须重启。若回滚旧版本，旧版本不读取远程授权文件，可能重新采用 gateway 配置里的旧电脑指纹；必须先由负责人把配置指纹调整为预期授权电脑，再回滚并验证。不得直接删掉授权记录以恢复旧权限。

## 验证记录

- 聚焦 Python：`PYTHONPATH=tests:. python3 -m unittest test_inviter_authorization test_registration_invites test_account_settings -q`，71 项通过。
- 独立审查者基于原始源文件与隔离运行给出“代码审查接受”，独立运行授权测试 32 项通过。审查指出的同指纹恢复、null 损坏回退、幂等同步及 PermissionError 误捕获四项均已修复并覆盖。
- 浏览器：`PLAYWRIGHT_MODULE=<已安装路径> node tests/check_inviter_authorization.cjs`，使用临时状态目录与真实本地 HTTP ConsoleServer，覆盖手机/桌面、普通用户拒绝、显式管理员确认、生效后发码、密码清理及无效链接。截图位于 `.runtime/inviter-authorization/`。
- 既有注册界面：`node tests/check_registration_login.cjs` 通过。
- Swift：`xcrun swiftc -typecheck -parse-as-library -swift-version 5 -target arm64-apple-macos13.0 desktop/*.swift iOS/CarryOn/Core/AppUpdate.swift` 通过；同一源集合已编译链接为 `.runtime/inviter-authorization/CarryOn`（arm64 Mach-O）。后续已更新本机 App，并通过原生界面实际点击「授权本机」验证链接和指纹。
- wheel 构建成功，`deployment/check_wheel.py` 通过；逐字节核验新增授权模块及相关 Web 资源与源码一致。
- 全量检查结果见本文件末尾；后续生产执行结果见交付记录。

## 全量检查限制

Node 工作流指定的四组测试共 79 项，78 项通过，1 项失败：`tests/test_client.js` 中 `plugin and skill configuration share client admission guards with immutable bodies`，预期插件 ID，实际为 undefined。将 HEAD 的 `client.js` 与 HEAD 的测试提取到隔离目录后，同一用例仍失败，确认不是本次授权变更引入。未修改这项不相关的插件行为。记录位于 `.runtime/inviter-authorization/node-suite.log` 与 `node-baseline.log`。

Python compileall、相关 JS 语法、安装脚本语法及 `git diff --check` 通过。

Python 全量 `python3 -m unittest discover -s tests -q` 执行 1011 项：901 项通过、109 项跳过、1 项错误。错误来自未修改的 `test_shared_codex_account.SharedAccountTests.test_forced_refresh_is_serialized_across_processes` 子进程 5 秒超时；随后单独复测该用例在 2.706 秒内通过。未声称全量首次运行全部通过。日志位于 `.runtime/inviter-authorization/python-suite.log` 与 `python-recheck.log`。

最终独立复审已接受 UI、真实 HTTP 验收、截图和恢复说明，无新增阻断。此次未使用 worktree，因此未触发必要提交和合回授权；代码保留在当前工作目录。后续生产发布和安装版界面操作验证已完成。


## 已授权部署与账号交付

用户明确要求部署本次优化、更新本机并继续创建 `admin001`。云端候选以实际在线版本 `556e79b61df29e6cb09464654c953584fd63e02d` 为基线，本机候选以当前安装包的源快照为基线，仅叠加本次优化；独立审查核对 manifest 内外文件。为兼容本机既有版本，原先六行专属样式移动到独立 `inviter-authorization.css`，两端统一由 HTML/ASSETS 引入，没有混入其他界面改动。

- 云端发布：`556e79b61df29e6cb09464654c953584fd63e02d-inviter-60e2f193`。这是带优化标记的发布 ID，不冒充新 Git 提交。先核对旧文件与候选哈希，再复制到独立 release。实际 Linux 服务身份下的临时目录 smoke 通过；持有部署锁，停服备份后原子切换并恢复服务。公网 HTTPS 健康版本与授权 JS/CSS 字节哈希通过，既有账号和设备配置哈希未变。
- 云端恢复点：`/var/backups/carryon/556e79b61df29e6cb09464654c953584fd63e02d-inviter-60e2f193`；旧 release 保留。恢复演练覆盖候选已启动但健康失败、停服结果不确定，均先停止候选，再切旧目录并启动核验。
- 本机 App：`/Applications/CarryOn.app`；CLI：`~/.local/share/carryon-releases/556e79b61df29e6cb09464654c953584fd63e02d-inviter-60e2f193/carryon`。旧 App 和 CLI 保留，恢复映射在 `.runtime/inviter-deploy/local-recovery.json`。首次安装后冷启动检查超时，按脚本恢复旧版；同候选独立验证 11.62 秒成功，经复审后重试安装成功。
- 本机后台存在活动任务，未重启这些会话服务。安装前后的实例 ID 与绑定配置哈希一致；桌面已重新打开，两个工作区运行且云端连接正常。实际点击「授权本机」得到与原凭证一致的指纹和云端链接，已关闭面板回到主界面。
- 创建账号：通过已授权云端管理员操作能力调用现有一次性发码方法，邀请码以 RSA-OAEP 加密传回；随后只提交一次正式 HTTPS 注册。`admin001` 注册成功，使用用户确认的密码登录成功，服务端身份不是 owner、工作区数量为 0。验证会话已退出，未更改管理员密码或持久发码电脑授权。密码不写入文件，临时邀请码传输私钥已清理。
- 两端隔离候选、校验清单及执行回执位于 `.runtime/inviter-deploy/`。本机 Python 3.11 的 71 项聚焦测试和隔离浏览器验收通过；App/CLI 签名、私密发链和资产一致性通过。旧打包脚本的 sdist 缺失样式导致末尾 wheel 步骤失败，直接 wheel 构建及部署校验随后通过；App/CLI/DMG 均已构建成功。
