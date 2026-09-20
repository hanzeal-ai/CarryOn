# 云端连接与运行边界

本地服务通过出站 WebSocket 连接云端，每个绑定独立保存设备凭证。账号成员权限由云端检查，电脑侧控制许可提供额外限制。远程请求不能管理本机配置或获取 Codex 账号认证材料。

使用 `carryon init` 或桌面初始化向导完成账号确认绑定。新工作区使用独立 app-server 与独立会话目录，流程见 [ONBOARDING.md](ONBOARDING.md)。多云绑定及恢复语义见 [MULTI_CLOUD.md](MULTI_CLOUD.md)。

服务配置、TLS、反向代理与专用运行用户见 [deployment/README.md](../deployment/README.md)。原始网关 `/v1/` API 供已配置的服务端集成使用；用户日常接入以账号确认的绑定流程为准。
