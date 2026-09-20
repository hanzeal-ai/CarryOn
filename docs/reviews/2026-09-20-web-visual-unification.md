# Web 视觉统一（2026-09-20）

## 范围

同步已确认的 iOS 黑白灰视觉语言，仅修改呈现：系统字体、语义色、卡片/控件圆角、间距、消息和表单、浅色/深色外观。

- 移动端保留页面与弹层结构，单行输入保持紧凑，超过一行展开为文字与工具两层，删除后收起；图片和模型按钮中心间距 32 CSS px。
- 桌面端保留侧栏、完整工具栏、鼠标悬停/键盘焦点反馈、快捷键说明，限制宽屏阅读宽度。
- `mobile-ui.js` 的变化仅测量输入框和调整布局类/高度，未改变请求、操作回调、状态判定或权限。
- `web/src/index.css` 是桌面样式源，`shadcn.css` 是构建产物。现有 HTML 的选择器不属于 React 源，因此页面样式移出会被 Tailwind 清除的 components layer，确保产物包含页面规则。
- 无新增依赖，无功能升级，无提交、推送或部署。已有 iOS/后端改动保留。

## 验证

- `cd web && npm run build` 通过，生成 CSS 已复制到根目录 `shadcn.css`。
- `node --check mobile-ui.js` 与 `git diff --check` 通过。
- `node --test tests/test_client.js tests/test_console_client.js tests/test_request_refresh.js`：31 项通过。
- `node tests/check_web_style.cjs`：320/390/768/1440 px × 浅色/深色共 8 组通过，覆盖列表、会话、登录、设置、模型/工具弹层或新建弹窗。检查横向溢出、输入展开/收起、32 px 间距、页面异常及模拟传输记录。
- `node tests/check_mobile_ui.cjs`：21 项布局检查，以及导航、创建/编辑入口、复制、队列操作、草稿、已读、权限禁用、短视口、桌面恢复、本机提示检查通过。
- 原移动 UI 测试中的旧静态设计坐标比较已替换为当前响应式边界和输入布局契约。原测试还引用了当前页面已不存在的本机服务管理面板，改为验证当前 Web 的本机连接提示；未恢复已撤销功能。

浏览器测试使用现有 Playwright 和模拟 API，不连接真实账号或发送真实任务。先在仓库根目录启动 `python3 -m http.server 8892 --bind 127.0.0.1`，再运行测试。可用 `CARRYON_UI_URL` 指定页面地址、`PLAYWRIGHT_MODULE` 指定已有 Playwright 模块路径。

截图和日志在 `.runtime/web-style/`；现有移动回归截图在 `.runtime/mobile-*.png`。已人工查看代表性桌面/移动、浅色/深色截图。尚未进行 Safari、真机触摸和真实服务端端到端验收。
