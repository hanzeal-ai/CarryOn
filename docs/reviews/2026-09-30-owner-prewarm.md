# Owner 预启动

用户授权按单个未加载备用 app-server 优化冷接管；保持桌面当前页面、不新增兼容分支、不复用已加载或持锁的会话进程。

风险 R2：执行进程获取、并发补充和关闭生命周期。当前 main 起点 1220e243cdcee16ac61b175f7a9263b8651f7f15；直接修改，无 worktree/提交。原 manager continuity、异步 compose、iOS 及工作区状态修改均已存在，保持原样。本轮基线 `.runtime/source-backups/2026-09-30-owner-prewarm/`。

影响：OwnerBridge 启用构造 OwnerManager；manager 管理一个 PrewarmedRuntime；load/_resume 消费已初始化但从未加载会话的进程，消费即异步补充。独立 app-server 工作区与新建会话的创建进程不接入。每个消费进程使用独立运行目录，任务完成仍 close 释放 native writer；备用不执行 thread/start/resume。失败明确返回，不切换到旧的现场创建方案、不重发执行请求。关闭先停止预启动并等待初始化收尾，再关闭已拥有执行进程。

原始证据：当前原生 thread/unsubscribe 取消订阅后仍 loaded，第二 app-server 恢复报 active writer；因此不以取消订阅作为写锁释放。优化只覆盖启动/initialize/account/read，Owner 发现、恢复及全量历史保持原契约。

验证：Owner 54 项、创建 13 项通过；全量 Python 603 项通过（1 跳过，156.327 秒），既有 zip 重复条目和 SQLite ResourceWarning，无失败。真实隔离 Owner 与 creation 两项回归通过：备用没有 loaded 会话，初次 load 与 suspended resume 使用同一个预启动实例，补充新备用，终态释放后另一进程可归档，不发送真实用户任务。最终夹具启动初始化 84.375 毫秒、领取备用 0.066 毫秒，仅此阶段实测，不等于手机端总耗时；首次夹具为 69.244/0.067 毫秒。日志 `.runtime/prewarm-owner-integration-final.log`、`.runtime/prewarm-creation-integration.log`、`.runtime/prewarm-python-full.log`。compileall、git diff --check 通过。

独立审查 review_send_experience 基于原始代码与本轮基线独立检查，重跑 Owner 54 项通过，接受实例/worker 互斥、消费补充、初始化失败、关闭收尾与授权/原生写锁边界，未发现阻断。

沿用本任务服务重启授权，重启前 PID 43770 无执行 app-server（仅 caffeinate），首轮启动 PID 68744 后曾观测到服务记录被移除，两个日志均无异常，原因未定位；已再次启动为 PID 69661，端口 8769，多次查询桌面 IPC 与云端连接成功，观测到单个 Codex 备用子进程 PID 69663。未导航桌面页面、未发送用户任务、未部署云端、未改 iOS 包。用户实际手机发送耗时仍待人工验收。

恢复：先等待会话空闲、停止服务，按基线比较仅撤销本轮修改并移除新 prewarm 模块，保留 Journal/CODEX_HOME 和其他会话修改；不回退整个文件或删除原生数据。重新启动原版本。无数据迁移、云端部署或真实任务发送。
