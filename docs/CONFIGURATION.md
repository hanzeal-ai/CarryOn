# 配置入口

产品默认地址统一维护在 `carryon/product.json`。主流程使用内置地址，目录和端口自动分配。

| 操作 | CLI | macOS |
|---|---|---|
| 首次初始化 | `carryon init` | 初始化向导 |
| 新建独立工作区 | `carryon services create --name 名称` | 添加工作区，只填写名称 |
| 列举工作区 | `carryon services list` | 工作区列表 |
| 登录独立 Codex 账号 | `carryon services login --state-dir 目录` | 初始化中的登录模型账号 |
| 启停 | `carryon start/stop --state-dir 目录` | 启动／停止服务 |
| 删除本地条目 | 停止后 `carryon services remove --state-dir 目录` | 删除工作区，保留文件 |
| 工作区成员 | `carryon members --state-dir 目录` | 使用者与权限 |
| 账号登录二维码 | `carryon cloud qr` | 绑定菜单中的生成账号登录码 |
| 自托管云端 | `carryon init --url HTTPS地址` | 初始化高级设置 |

CarryOn 数据目录保存连接配置和投递日志。默认 IPC 工作区读取实际 Codex HOME；新增工作区的 Codex HOME 由创建流程单独分配，不接受启动时替换为其他工作区目录。

每个云端绑定保存独立凭证、控制许可和恢复状态。`cloud control --binding-id ID --allow-control/--read-only` 调整电脑侧许可；账号成员权限仍由云端检查。`cloud disconnect --binding-id ID` 只断开该本地连接，不删除其他绑定或会话。

CLI 与桌面使用相同目录注册表和初始化引擎。配置及认证操作通过本机 CLI/原生桌面执行，浏览器不能绕过电脑侧配置授权。更多流程见 [ONBOARDING.md](ONBOARDING.md)。
