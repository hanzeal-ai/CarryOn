# 第二轮真机交互对照

参考：iPhone 16 Pro Max 上 ChatGPT 的 Codex 区域，2026-10-21。原始截图仅本机保留于 `.runtime/phone-parity-round2-2026-10-21/`，索引 `gallery.html`，尺寸和摘要 `screenshots.json`。本轮不使用重置卡，不清空数据、不提交真实任务。

| 项目 | 实际操作和观察 | 原始截图 | 当前差异及处理 |
| --- | --- | --- | --- |
| 项目折叠 | 点击 CarryOn 标题原位展开，再点收起；文件夹图标联动，没有新页面 | official-project-expanded / collapsed | CarryOn 目前标题无动作；改为原位折叠，保留独立新建按钮和查看全部 |
| 工具组 | 点击“调用了 8 个工具”显示子项，子项失败时明确标示失败 | official-tools-collapsed / expanded | 核对组内展示与展开状态，不能把失败显示成成功 |
| 单个工具 | 点击子项，原位出现纯文本输出卡片、换行按钮，下方原始调用输出入口 | official-tool-detail | 当前打开详情 sheet；将已有工具输出改为原位展开，复用现有数据渲染 |
| 文字选中 | 原生菜单有添加到聊天、拷贝、侧边聊天等；添加后生成可移除批注，未发送 | official-selection-menu / added / removed | 现有 ReviewComment 只接受真实 diff 行，不能伪造 source/path 实现正文引用；需独立草稿引用契约，尚未同步 |
| 附件 | + 打开带圆形图标的宽浮层；照片后退出回到附件菜单 | official-attachment-menu-expanded / photo-cancel-menu | 当前为系统 Menu；照片选择没有执行上传，私人网格没有保存 |
| 重命名 | 更多→重命名任务，居中原生 alert，有输入框和取消/保存；已取消 | official-rename-alert | 当前表单包含待处理请求核对和恢复；不能直接删除恢复路径换成无状态 alert |
| 搜索无结果 | 前轮已采到查询词和检查拼写提示 | 第一轮 official-search-no-results-ime | 当前只写没有搜索结果；补齐查询和提示 |

原位展开默认保持 CarryOn 现有的展开状态；官方初始状态是否跨启动持久化尚无证据，不据此引入持久化协议。现有目录树、工作区 Git 比较范围仍缺等价后端能力，见第一轮记录。真实软键盘、语音、停止/归档写操作未作为本轮已验证项。

本轮修改基于 main 的 556e79b；仓库其他会话的 Web/服务端改动不在本次范围内。当前为 R1 展示层调整，不改远端操作、权限或存储格式。验证及安装结果在完成后追加。

## 已同步与验证

- 首页项目标题原位展开/收起，图标随状态变化，不导航到另一个列表。折叠状态下右侧新建仍带入正确项目；取消新建、搜索和清除搜索后折叠状态保留。证据 `sim-project-expanded.png`、`sim-project-collapsed.png`、`sim-collapsed-project-create.png`、`home-ui-checks.json`。
- 搜索空结果显示查询词和检查拼写提示，保持加载、错误、重试分支。证据 `sim-search-empty.png`。采集时真机出现一次 HTTP 502，重试恢复；`carryon-search-502-before.png` 是服务失败记录，不作为无结果样式基线。
- 工具组显示调用数量，全部子项原位展开，不再在第 5 项后转入完整过程 sheet。单个工具原位展开输出、保留失败标记、支持换行切换及原始调用输出。收起再展开组时保留子项展开状态。证据 `sim-tools-expanded.png`、`sim-tool-wrapped-final.png`、`sim-tool-horizontal.png`、`sim-raw-output-wrapped-final.png`、`tool-ui-checks.json`。
- 发现并修复展开文件夹符号不存在和高亮 JSON 换行行距重叠；失败截图分别保留为 `sim-home-expanded-missing-icon.png`、`sim-raw-output-overlap-before.png`。换行模式使用统一等宽排版，横向模式保留语法高亮。
- 最终首页 smoke 通过；会话回归 33 项通过。测试在初始动画中取到 239.11 宽度，曾导致与收起后的 238 比较失败；现以有上限的稳定帧等待取样，保留全部原断言。最终实测 238 → 342 → 238。选择页撤权检查等待实际原生关闭完成，仍断言选择视图不在窗口内。失败结果和最终结果均保留，没有清空测试数据。
- 模拟器初次处于 Shutdown，后来启动请求停滞；仅对同一模拟器进行保留数据重启，之后完成验证。没有抹除、卸载或使用重置卡。

## 未完成项

正文引用批注、附件浮层外观与取消后返回行为、重命名正常态 alert 尚未同步。本轮没有修改草稿存储格式、待处理请求恢复或上传契约。目录树和工作区 Git 比较范围仍缺等价能力。不能把本轮的三组界面同步描述为整个 GPT App 已经一比一完成。

## 真机交付

14:44 覆盖安装成功，bundle `com.hanzeal.carryon`，签名严格校验通过。14:46 打开应用确认原登录与项目列表可用，项目标题收起仍留在首页。真机截图为 `phone-updated-home-expanded.png`、`phone-updated-home-collapsed.png`；没有提交真实会话任务。设备返回的安装凭证在 `install-result.json`，源码、安装包各文件摘要和验证状态在 `build-manifest.json`。本地可视对照页为 `synced-gallery.html`。

代码保留在 main 工作区，未创建提交、推送或合并；未动并发的 Web/服务端变更。
