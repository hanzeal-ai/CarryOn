# 独立工作区共享本机 Codex 登录

## 需求、边界与风险

用户明确要求多个 CarryOn 工作区共享本机 Codex 登录，不逐个登录；项目和会话保持独立。本次按 R2 实施认证状态接入，未改变 CarryOn 云端成员权限、工作区绑定或远程操作授权。直接修改当前 checkout；保留任务开始时已有的无关未提交改动，没有提交、推送或部署。

## 实现与影响

- `shared_account.py` 统一选择认证来源：已登记且有效的桌面 Codex Home，或启动环境的 `CODEX_HOME` / `~/.codex`。通过 Codex 原生 `getAuthStatus` 读取访问令牌，凭证文件、Keychain 和刷新仍由 Codex 管理。
- 独立 app-server 使用 `cli_auth_credentials_store="ephemeral"`，ChatGPT 使用原生 `chatgptAuthTokens` 协议。API key 同样仅进入内存。没有复制或链接用户凭证文件、原生会话或数据库。
- 原生支持 `workspaceRouting` 时优先使用其账号标识；旧版使用 JWT 的账号标识。所有格式异常返回脱敏错误。令牌不会进入 CarryOn HTTP 返回值。
- 发送前与每 30 秒后台同步认证。退出清除子进程认证；刷新请求校验原账号且不向替换后的进程写回。强制刷新通过跨进程锁串行，普通读取不等待该网络刷新锁。
- 登录按钮、CLI 登录和额度查询/重置指向同一共享来源。额度重置保留原有账号指纹确认及幂等授权。
- 项目配置、会话、数据库、工作目录和 app-server 进程仍按原工作区隔离。辅助运行时继承认证共享策略。
- 已有独立工作区重启新版本服务后生效；旧凭证文件保留但运行时不使用。无需迁移或删除会话数据。

## 验证

环境：macOS；应用捆绑 Codex `0.163.0-alpha.10.2`，独立 CLI `0.155.1`。

| 验证 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -p test_shared_codex_account.py -v` | 17 项通过：真实原生双工作区共享与隔离、退出/切换、无重启登录、旧凭证保留、ChatGPT 外部令牌、错误脱敏、并发及跨进程锁、旧进程保护、登录和额度来源 |
| `test_app_server_workspaces.py` | 13 项通过 |
| `test_workspace_backends.py` | 6 项通过 |
| `test_usage.py` | 9 项通过 |
| `test_cli.py` | 4 项通过 |
| `test_services.py` | 8 项通过 |
| `test_codex_cli.py` | 10 项通过 |
| `test_onboarding.py` | 35 项通过（包括其导入的账号测试） |
| `python3 tests/run_desktop_smoke.py` | Swift 编译通过；桌面模型经实际 CLI 创建两个隔离工作区，共享测试账号且无凭证副本，独立启停和删除保留文件通过 |
| 本机当前登录的临时独立运行时 | 只读验证 `accountReady=true`、工作区无 `auth.json`、原生会话列表为空；未打印账号或令牌，未执行模型 turn |
| `git diff --check` | 通过 |

双工作区测试使用本地 fixture provider 排除公网模型目录查询的波动；没有降低认证或隔离断言。ChatGPT 合成令牌测试固定使用已安装的 0.155.1，避免新版针对合成账号的联网路由校验。当前安装版也通过本机真实认证的只读验证。

独立审查：GPT-5.6 Luna 基于原始源码和独立执行测试，先要求修复畸形原生回执处理，修复后结论为接受；其建议补充的跨进程锁测试也已通过。

## 恢复与交付边界

回退本次认证接入相关差异并重启服务即可恢复原独立登录行为；不要整体重置工作树。共享来源凭证与工作区旧凭证均未删除，原项目和会话无需恢复或迁移。

源码及自动验证已交付；未替换用户已安装的 CarryOn 应用或重启正在使用的服务，未执行真实模型推理或人为过期真实令牌。安装版更新、实际窗口人工验收及发布仍由用户决定。原生外部认证接口属于实验接口，升级 Codex 时应复跑上述原生契约测试。
