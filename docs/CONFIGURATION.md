# CLI 与桌面端配置

CarryOn CLI 和 macOS 桌面端是同一套本机服务的两个操作界面。默认均使用 `~/Library/Application Support/CarryOn`；CLI 指定 `--state-dir` 或 `CARRYON_HOME` 时，桌面端需选择同一目录。配置由服务写入，桌面端定期刷新服务状态，不维护另一份连接或权限配置。

本地网页提供会话查看和交互；云端网页仍负责管理员确认连接申请、设备撤销和会话交互。本机服务配置只能通过 CLI 或桌面端修改。浏览器即使持有本机 Token，也不能调用本机配置写接口。

| 配置 | CLI | 桌面端 |
|---|---|---|
| 启动服务 | `carryon start --no-open` | 启动服务 |
| 停止服务 | `carryon stop` | 停止服务 |
| 服务状态 | `carryon status` | 顶部服务状态 |
| 桥接 | `carryon bridge on/off/status` | 连接本机 Codex |
| 远程待机 | `carryon standby on/off/status` | 远程待机 |
| 连接云端 | `carryon cloud connect --url https://云端地址` | 云端连接，申请连接 |
| 查询绑定 | `carryon cloud status` | 云端连接列表 |
| 查询申请 | `carryon cloud link-status` | 云端申请结果 |
| 允许控制 | `carryon cloud control --binding-id ID --allow-control` | 对应绑定的允许远程控制 |
| 改为只读 | `carryon cloud control --binding-id ID --read-only` | 关闭对应绑定的允许远程控制 |
| 解除绑定 | `carryon cloud disconnect --binding-id ID` | 对应绑定的解除绑定 |
| 控制会话 | `carryon controller set --thread-id ID` | 创建任务的控制会话 |
| 本机通知偏好 | `carryon notifications status` / `set --no-message --done --failed --approval` | 本机会话通知 |
| 查看控制会话 | `carryon controller status` | 当前控制会话 ID |

表中的 `on/off/status` 表示三个独立子命令，例如 `carryon bridge on`。多绑定时，权限修改和解除绑定必须选择绑定 ID；只有一个绑定时可省略。新连接默认只读，授权控制需显式加 `--allow-control` 或在桌面端勾选。

连接命令返回表示申请已提交，云端管理员核对确认后本地服务自动绑定。`link-status` 的 state 为 idle、pending、bound、expired 或 failed；failed 显示失败原因，bound 不代表 Codex 桥接必然开启，需结合 bridgeEnabled 与当前 `bridge status`。此申请状态是当前服务进程的投影，重启后申请失效，已保存绑定继续保留。

端口和 Codex 数据目录是启动参数。更改前停止服务，再用 `start --port 端口 --codex-home 路径`，或在桌面端停止后填写并启动。新建任务需先在 Codex App 中加载专用空闲控制会话，再设置其 ID。

## 本次变更恢复

未迁移用户数据或修改 Codex 数据库。回退前停止对应数据目录的服务，保留整个数据目录，再使用原程序启动同一目录。回退会恢复旧网页配置行为；不复制或恢复已撤销的云端设备凭证。不要为重试未知结果更换数据目录或请求 ID。

本机通知偏好需开启桥接后配置。云端读者各自的通知偏好仍由云端会话管理，与本机读者的偏好相互独立。

## 验收边界

本次按 R2 处理：变更涉及本机配置写入口和控制会话权限。影响范围为 CLI、桌面展示、HTTP 浏览器限制和网页配置入口；绑定凭证持久化、审批、云端授权仍由现有服务负责。

自动验证使用项目 Python/JS 回归、带有效 Token 的浏览器拒绝用例和 `tests/run_desktop_smoke.py` 的打包入口共享配置验证。原生桌面窗口实际点击、真实云端 HTTPS 配对、独立审查与人类验收需另行完成；构建产物不等于已批准安装或生产发布。


## 多工作区与桌面命令

一个工作区对应一个 `--state-dir` 服务数据目录。桌面左侧列出本机服务，显示名称、路径、端口和状态；点击后，所有配置、云端绑定、诊断和启停操作只针对所选目录。相同 Codex 目录下的两个服务仍能读取相同 Codex 会话；独立服务配置不等于隔离原生 Codex 数据。

点击「添加工作区」，填写名称并创建或选择已有数据目录；端口默认 0（自动分配）。添加后点击「启动服务」，再点击「连接云端」输入 HTTPS 地址发起申请，在云端核对并确认。导入正在运行的目录时保留实际端口与 Codex 目录。

| CLI | 桌面入口 |
| --- | --- |
| `start` | 工作区 → 启动服务（后台） |
| `serve` | 工作区 → 前台运行，或运行日志 → 前台启动 |
| `open` | 工作区 → 打开会话 |
| `status` | 工作区状态、侧栏状态与刷新；诊断中的当前服务 |
| `stop` | 工作区 → 停止服务 |
| `doctor` | 诊断 → 运行诊断 |
| `cloud` | 云端连接 → 连接云端、申请状态、控制授权、解除绑定 |

前台服务由桌面进程持有，输出显示在「运行日志」，退出应用时停止；后台服务独立运行。关闭窗口与退出应用不同。

```sh
carryon services list
carryon services add --name "工作区 B" --state-dir "$HOME/.carryon/b" --port 0
carryon start --state-dir "$HOME/.carryon/b" --port 0 --no-open
carryon cloud connect --state-dir "$HOME/.carryon/b" --url https://你的云端地址/carryon
```

服务启动后自动登记。旧 CLI 已启动的服务通过当前用户的进程参数发现，再用已有 Token 和实例校验确认。停止的已登记目录保留在列表中，未运行且从未登记的旧目录需要手动添加。注册表 `~/Library/Application Support/CarryOn/services.json` 只存目录、名称和启动参数；在线状态始终由实际服务确认，配置仍保存在各自目录中。无法确认但留有服务记录时显示「暂不可用」。
