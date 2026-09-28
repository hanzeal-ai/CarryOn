# 共享目录项目分类与 Codex 侧边栏对齐

## 范围与风险

用户要求修复 DoTasks 出现两个项目分组。R2：分类 ID 会影响项目列表、详情、通知投影和创建会话目标；仅修改只读分类推断，不修改 Codex 会话、项目绑定或运行服务，不提交、推送、部署。

## 原因与权威证据

本机 DoTasks 与 DMC产品矩阵共享 `/Users/sanmws/Documents/DoTasks` 根目录。两条会话有旧项目绑定，两条没有显式绑定。空值不证明 Codex 无法展示归属：侧边栏会依据目录推断。此前“未同步项目 ID”的判断不准确。

只读检查当前安装的 `/Applications/ChatGPT.app/Contents/Resources/app.asar`：
- `webview/assets/app-initial-d817715f10a0.js` 的 `Q9t` 为每个根目录选择一个展示项目，`ren` 调用共享排序规则；`Een` 优先使用显式绑定，之后才按目录展示归组。
- `webview/assets/app-shared-36eae88777f2.js` 的 `dmt` 依次偏好：单根目录项目、当前根是项目首根、较早 createdAt、较大项目 ID。
- Codex `list_threads` 返回的展示归属，与未绑定的两条 DoTasks 会话采用该规则的结果一致。

原始 bundle 的相关文件已只读提取到忽略目录 `.runtime/` 供独立审查。产品运行不依赖这些提取文件。

## 最终行为与影响

相同根目录匹配多个项目时，CarryOn 使用上述展示排序规则，生成选中项目的既有分类 ID。显式数据库项目 ID、旧绑定、显式无项目标记的原有优先级不变；不同根目录仅因 Git common-dir 相同的歧义仍不推断。子目录仍沿用已有最近根匹配。

这是对 2026-09-25 多根目录分类中“所有共享根都保留路径分组”规则的修正。新建目标继续由现有 `creation.resolve_project` 校验；不写回猜测的绑定、不合并两个明确绑定的项目、不新增 ID 重定向。

## 验证与恢复

- Catalog、Workspace、项目创建：61 项通过。
- 真实本机 Catalog 只读分类：4 条 DoTasks 会话归入唯一分组 `49606a35aaef0ce0d20b19b09e9e3fd4aa1770580b2208cd2052a57f72270d60`。
- 独立审查确认实现与 Codex 排序证据一致，要求修正 `docs/WORKSPACE.md` 中旧的共享目录规则；文档已同步。文档复核通过，独立审查接受本次变更。
- 路径匹配沿用现有 Python Path 规则；本次未扩展 Codex 的大小写/Windows 路径别名归一化，验证覆盖本机规范路径。
- 完整后端测试：516 项，OK，1 项跳过；原始日志 `.runtime/project-grouping-tests.log`。
- 尚未更新运行服务或在手机验收。发布后需刷新项目列表；旧目录分类详情可能需要返回列表重新选择。
- 恢复时回退本次分类代码并刷新列表即可，无数据迁移；不清理会话、Journal 或重新发送请求。
