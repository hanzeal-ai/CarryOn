# CarryOn

产品名为 **CarryOn**。中文宣传语为「换个设备，接着做。」，英文为「Switch devices. Carry on.」。

应用、Swift 工程和模块使用 CarryOn。Python 包为 `carryon-local`，模块为 `carryon`，命令为 `carryon`、`carryon-gateway` 和 `carryon-console`。环境变量使用 `CARRYON_*`，默认状态目录为 `~/Library/Application Support/CarryOn`。

云端路由为 `/carryon`，设备协议为 `carryon/1`。各端必须一起更新，旧名称命令、协议、Cookie 和存储键不提供运行时兼容或回退。

升级前停止相关服务并备份工作区、连接配置及云端设备注册表。由发布步骤一次性迁移目录、配置中的云端地址和注册表路径；应用只读写新格式。新名称的 iOS 应用需要重新登录。旧备份仅供操作员恢复，不参与新版本运行。

GitHub 仓库为 `hanzeal-ai/CarryOn`。本地 checkout 目录维持当前路径，以免打断正在进行的开发任务；历史验证记录和设计概念稿保留当时名称。
