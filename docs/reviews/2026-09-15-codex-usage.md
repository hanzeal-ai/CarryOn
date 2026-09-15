# 当前工作区 Codex 额度

目标：“我的”页展示当前工作区本机 Codex 登录账号的额度消耗，包括各额度池已用比例、周期、重置时间、读取时间及手动刷新。

范围/风险：R2，新只读公共接口及本机子进程读取。账号额度共享，不推算工作区独立花费或 token；不添加登录、购买、重置入口，不新增安装依赖。复用已安装 Codex 桌面附带程序或已有 PATH codex，以及现有 Bridge/远程绑定授权。界面只有 iOS“我的”页新增卡片，其他客户端无主动调用，不改变会话与写入契约。

权威：本机 Codex app-server 的 account/read 与 account/rateLimits/read，CODEX_HOME 固定为 bridge.catalog.home。官方网页读取返回 Forbidden，因此协议依据本机 Codex 导出 JSON Schema及安装包中已存在的方法，且进行了真实只读请求验证。没有读取/传出 auth.json 或账号身份。

隔离：iOS 按 model.scope 重建卡片、清空旧数据，读取响应需匹配 scope/requestVersion；通过既有设备路由读取。失败显示未知/错误，不显示缓存为最新或默认成0。响应白名单投影；子进程上限2、读取15秒超时，清理有界并处理 pipe/terminate 竞态。

验证：真实本机只读读取成功，返回多个额度池与窗口；7项后端测试覆盖字段投影、未知/legacy、权限与工作区路径、stdio协议/进程退出、并发容量、清理异常。iOS完整模拟器构建 BUILD SUCCEEDED；Swift回归69+4通过；git diff --check通过。独立审查要求的子进程清理/容量边界已修复并覆盖测试；GPT-5.6 Sol最终审查结论 Accept。没有真实额度消耗或重置操作。

恢复：撤回本次 usage.py、新路由与iOS用量卡片，不回退其他已有改动；无迁移，无提交/推送/部署。手机页面验收仍由用户完成。
