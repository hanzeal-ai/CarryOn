# iOS 会话状态探测与过滤修复

范围：只读状态探测调度、会话/项目列表过滤、iOS 下拉刷新。风险 R1；原生运行状态仍是执行状态的权威来源，不改变发送、权限、会话接管或恢复规则。

修复：优先探测可见会话，同优先级按上次尝试顺序轮转，总并发保持 4，并为后台探测保留进展。尚未取得快照的会话保留为检测中或状态未知，确认未加载后隐藏；`available` 仍仅表示已取得可用完整快照。动态列表继续要求已确认可用。HTTP 与实时订阅复用相同快照与探测结果；探测结果变化使工作区版本失效。下拉刷新通过 `refreshStatuses=true` 重新探测缺失快照，保留已有实时快照，不恢复或投递任务。

验证：

- `python3 -m unittest discover -s tests -p 'test_realtime.py'`：21 项通过，覆盖十秒探测/三十秒重试下的尾部会话、可见行优先、后台进展、真实线程池繁忙后恢复、重试和 IPC 更换。
- `python3 -m unittest discover -s tests -p 'test_workspace*.py'`：49 项通过，覆盖未确认/确认未加载、项目聚合、限定项目刷新、动态与已读语义。
- `test_app_server*.py`、`test_http.py`、`test_cloud.py`：分别 16、8、9 项通过。
- `python3 tests/run_ios_navigation_regression.py 4E4AA14D-FBDE-4E94-806C-8585787CB27C statuses`：模拟器构建及 13 项行为检查通过；已检查 `.runtime/statuses-regression/statuses.png`，列表显示执行中。真实刷新动作只在隔离 App 副本中通过测试通知触发。
- `python3 .runtime/statuses-regression/verify-native.py <正在执行的本地会话 ID>`：隔离只读 Bridge、临时通知数据库和真实桌面 IPC 验证。当前会话先在过滤后列表保留为检测中，约 0.06 秒后 HTTP 与订阅均为 running/available=true；未发送任务。结果位于 `.runtime/statuses-regression/native-ipc-result.json`。
- 签名真机 App 源码快照的 Swift 检查：118 项 Swift Testing 与 4 项 XCTest 通过。`xcodebuild` Debug 真机构建通过，`codesign --verify --deep --strict` 通过；IPA 内版本、可执行文件及 SHA-256 已检查。

用户随后明确授权重启服务和更新手机安装包。2026-09-30 18:12（Asia/Shanghai）使用现有 CLI 停止并启动默认本机工作区，端口仍为 8769，新 PID 为 87734，Codex 与云端连接正常。正式服务验证：过滤后列表保留当前执行会话并返回 running/available=true；最终列表包含 3 个 running 与 11 个 idle。

已将 `com.hanzeal.carryon` 1.0（build 4）签名安装到已连接的 iPhone 16 Pro Max，并成功启动。已通过设备已安装应用清单确认版本 4。安装包为 `.runtime/ios-status-device/CarryOn-1.0-build4.ipa`；安装、启动、服务验证和构建日志位于同目录。真实手机上的列表视觉与手动交互尚待人工验收；未上传 TestFlight 或 App Store。

恢复：开始前的相关文件副本位于 `.runtime/source-backups/2026-09-30-ios-status-scheduling/`。工作区还有其他会话的修改，不能整体还原这些副本；应审查并选择性撤销本次差异。`.runtime/statuses-regression/status-scheduling.patch` 保存相对于任务开始时文件的代码差异。服务数据、原生会话数据库及手机容器未删除。本次在共享 main 工作区直接修改，没有创建 worktree、提交或推送。
