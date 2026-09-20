# 不活跃会话显示偏好

目标：手机端默认显示桌面可用会话；全局开关开启后显示全部。进入未加载会话显示桌面加载提示，不改变操作权限。

影响分析：沿用 IPC 当前完整快照和 project_status；idle/running/waiting 属于可用状态，不以年龄或未读推断。无快照、metadata-only、notLoaded、unknown、error 不作为当前可用证据。设置跨工作区保存于当前手机，不变更服务器账户偏好。服务端 availableOnly 显式过滤，默认保持已有 API 行为；过滤先于项目聚合和分页。通知直达不受列表偏好限制。RootView 快捷切换不变。

验证：workspace 32 项通过（包含过滤前分页、项目数量、未加载/metadata/丢失快照、待处理保留），Swift 101 项通过，iOS 模拟器构建通过。设置页截图已检查。独立源码审查通过；未扩大写权限。本轮未提交、部署或安装真机。

恢复：仅移除本轮 AppStorage 开关、列表 availableOnly 参数和服务端可选过滤；不回退此前未提交的同步与交互改进。

最终模拟器 27 项通过（/tmp/carryon-available-simulator.log），包括开关切换后列表自动重新查询、默认可用过滤的项目缓存复用、已有后台/通知/隔离回归。最终 git diff --check 通过。
