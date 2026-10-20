# 文件与文件夹附件契约

此功能把用户选择的文件上传到本机服务的私有附件目录，供 Codex 在新建或已有会话中读取。不会解压归档、执行文件或写入项目目录。风险级别为 R2：新增持久文件写入和账号权限边界，交付需通过安全测试和独立审查；不涉及生产部署或历史数据迁移。

## 客户端

iOS 与 Web 在聊天、新建会话的「＋」菜单提供「上传文件」「上传文件夹」。附件显示名称、进度或失败状态，失败可重试，也可以移除；上传完成前不能发送。每条消息最多引用 20 个上传附件，可仅发送附件，运行中的会话也支持排队。

iOS 使用系统文件选择器和受限资源访问，将选择内容暂存为稳定快照后上传；草稿和提交回执支持恢复。Web 完成回执按账号、工作区、会话或新建项目隔离，保存在当前标签页的 sessionStorage；仅保留 ID、目标、名称和类型，不保存文件内容或服务器路径。刷新后可用原 ID 重试结果未确认的发送；未完成的上传刷新后需重新选择。支持 `showDirectoryPicker` 的浏览器保留空目录；其他浏览器使用目录文件选择器，只能保留文件及其父目录，会明确提示不包含空目录。iOS 可保留空目录。选择器取消不会开始上传。

## 接口与限制

`GET /api/status` 与实时状态使用同一 `Bridge.status()`，提供：

```json
{
  "supportsUploads": true,
  "uploadLimits": {
    "chunkBytes": 49152,
    "maxEntries": 100,
    "maxFileBytes": 20971520,
    "maxTotalBytes": 52428800
  }
}
```

所有上传请求必须通过既有认证、启用服务门禁；云端还需本机 `remoteControl` 授权和当前连接账号的 `send`、`files` 权限（工作区权限模型要求同时持有 `view`）。每一步及最终投递均重新验证权限，不使用开始上传时的权限快照。恢复查询 `GET /api/uploads/<id>` 采用相同门禁。创建携带附件时需 `create + send + files`，高级设置继续需要 `edit`。已有会话发送、steer、queue-add 需 `send + files`。

`POST /api/uploads` 以 `action` 区分：

```json
{
  "action": "begin",
  "requestId": "stable-client-request-id",
  "target": {"type": "thread", "threadId": "11111111-1111-4111-8111-111111111111"},
  "name": "notes",
  "kind": "directory",
  "entries": [
    {"path": "notes", "kind": "directory"},
    {"path": "notes/empty", "kind": "directory"},
    {"path": "notes/readme.txt", "kind": "file", "size": 5,
     "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}
  ]
}
```

新建目标为 `{"type":"creation","projectId":"<项目 ID>"}`；独立工作区允许省略 projectId，回执规范为 `null`。服务端记录既有 `resolve_project` 解析的项目 ID、工作目录、分组身份，并在后续操作再次核对。附件不可改绑到其他会话或新建项目。

文件附件的 name 是单个文件名，kind 为 `file`，entries 只有一个相同路径的 file。目录附件必须显式列出顶层目录、所有父目录、文件及空目录。每个附件最多 100 项，单文件最多 20 MiB，总文件字节最多 50 MiB。服务目录累计保留及预留空间上限 1 GiB，包含未完成上传，并计入清单和批次固定开销；不自动清理已完成附件。

begin 返回 `{"id":"<32位小写十六进制>","name":"notes","kind":"directory","state":"uploading","target":{...}}`。相同所有者、相同 requestId、相同清单/目标得到同一 ID；不同内容返回 409。客户端必须保留 requestId 以恢复未知结果。

```json
{"action":"chunk","uploadId":"<id>","path":"notes/readme.txt","offset":0,"data":"aGVsbG8="}
```

data 为严格 base64，每块原始数据最多 49,152 字节，非空；offset 为非负整数。首次和完全相同的重复块均返回 `{"offset":5}`，即**该块的末尾**，不是服务器当前累计进度。允许从 offset 0 逐块重传；若系统中断留下相同前缀，补写剩余字节。不同内容、跳跃偏移、越界块被拒绝；已封存附件只接受相同字节的重放。上传接口 JSON 限制在 100,000 字节内，复用现有 HTTP、WebSocket、云端隧道限额，无新增大请求通道。

```json
{"action":"complete","uploadId":"<id>"}
```

服务端逐项校验精确结构、文件大小及 SHA256，全部通过后设为只读并原子落盘 complete 状态。零字节文件和只有空目录的批次可以直接完成。回执为：

```json
{"id":"<id>","name":"notes","kind":"directory","state":"complete",
 "path":"<服务状态目录>/attachments/<id>/content/notes","target":{...}}
```

complete 可重复调用。path 仅用于显示/诊断；客户端发送 `uploads:["<id>"]`，不能自行提供服务器路径。`GET /api/uploads/<id>` 返回同一回执及 entries，其中每个 file 有累计已写 `offset`；complete 状态仍重新验证实际磁盘内容。

历史消息的 `artifacts` 与上传回执分开：实际目录使用 `kind:"directory", previewAvailable:false`；超过现有 8 MiB 读取上限的普通文件使用原 kind，并增加 `previewAvailable:false`。目录识别使用 `lstat`，不跟随符号链接。当前 Web/iOS 对这些项目只显示附件名称，不提供预览或下载；附件仍可通过完整路径供 Codex 读取。本次不提供目录压缩下载，也不扩大预览接口的 8 MiB 限制。小文件字段与行为保留，`previewAvailable` 缺省沿用原预览行为。这是新增可选字段；忽略该字段的旧客户端仍可能显示无法完成的下载入口，需同步升级两端才能隐藏，服务端继续拒绝目录、特殊文件及过大文件读取。

## 投递与安全边界

支持 POST `/api/threads`、`/api/threads/<id>/messages`、`compose`、以及 `operations` 的 `steer`/`queue-add`。客户端把 uploads 列表纳入待重试请求的内容身份。服务端在统一路由验证所有者、目标和封存内容，再通过现有文件引用 envelope 投影成普通 prompt，继续使用原创建、发送、队列和幂等日志，不新增调度器。上传 ID 对应唯一受控路径，因此既有 prompt 指纹也包含对应附件身份。与项目文件同时引用时合并为一个 envelope，保留原正文。

上传所有者是本机或“连接绑定 ID + 云端验证账号 ID”。其他账号、绑定、本机请求不能凭 ID 读取或发送该附件，返回 404。账号身份来自已认证传输上下文，不能从 body 设置。最终发送再次核对现行权限。

路径是 NFC 规范相对路径，UTF-8 最多 512 字节，每段最多 255 字节。拒绝绝对路径、`..`/`.`、空段、反斜杠、控制字符、冒号、前后空白、尾点和大小写/规范化重名；只接受目录和普通文件。文件通过目录 FD + `O_NOFOLLOW` 打开，并验证单一硬链接；目录也禁止符号链接。完成和投递时拒绝额外内容、文件变更、符号链接、硬链接和特殊文件。用户不能指定存储目录，文件不会覆盖项目路径。

私有根目录为配置的 `bridge.workspace_directory/attachments`，独立随机批次隔离。全局文件锁保护预留配额、并发 begin 和写入；新记录在 `.pending-<id>` 目录内写入并同步后，原子发布为正式 ID。公布后的 `preparing` 状态可以通过相同 begin 重试初始化。完成文件权限为 0400，目录为 0500。与服务同一操作系统用户运行的 Codex 可读取这些路径；沙箱若另有读取限制，仍遵循原生权限机制。服务不会为此扩大原生沙箱权限。当前自动化验证覆盖普通文件读取和实际协议文本投递，不声称已在每种真实 Codex 沙箱配置执行读取。

## R2 影响分析、验证与恢复

影响范围：统一 API 路由、远程请求来源、工作区权限投影、权威状态、既有文件 envelope、公共静态资源清单。既有项目目录、SQLite 日志模式、原生创建/队列调度不迁移。测试使用临时目录、模拟 native IPC、本机随机端口和临时出站隧道，没有写入真实会话。

验证入口：

```sh
python3 -m unittest discover -s tests -p 'test_uploads*.py' -v
PYTHONPATH=tests python3 -m unittest test_file_references test_http test_cloud test_creation_capabilities test_console test_project_creation
node --test tests/test_file_uploads.js tests/test_client.js
swift test --package-path iOS
```

启动本地静态服务 `python3 -m http.server 8923 --bind 127.0.0.1` 后，使用已安装的 Playwright 运行 `node tests/check_upload_ui.cjs`（需要时通过 `PLAYWRIGHT_MODULE` 指定模块路径）。覆盖桌面和移动 Web 的真实选择入口、分块失败重试、草稿隔离、纯附件发送、排队、新建、权限撤销及未知发送结果跨刷新恢复；传输使用隔离 fixture。截图输出到 `.runtime/uploads/`。

iOS 设备目标编译使用 `iOS/scripts/compile-device.sh`；对已启动的隔离模拟器运行 `python3 tests/run_ios_navigation_regression.py <simulator-id> uploads`，检查两处附件菜单、文件/文件夹选择器打开与关闭及草稿门禁。结果和截图位于 `.runtime/uploads-regression/`。此验证不覆盖真机或真实 iCloud、第三方文件提供器。

覆盖多块从头重放、部分系统写入恢复、并发 begin、配额、目录/空目录、大小及 hash、穿越/符号链接/硬链接/特殊文件、所有者和目标隔离、权限撤销、record 写入失败、封存后回执失败、HTTP 限额及云端只读拒绝。2026-10-20 独立审查结论为接受：审查者基于原始差异、独立运行结果和界面证据复核，提出的问题均已修复并复验。审查使用继承模型，因为规范优先的 `gpt-5.6-luna` 当前不可用；未执行部署。

恢复路径：

1. 网络超时或回执丢失：使用原 requestId + 原清单重试 begin；可查询 GET，再从头按原 offset/字节重放 chunk，重复 complete。不要更换 requestId 盲目制造新副本。状态为 preparing 时先重试 begin。
2. 进程在初始化或封存中退出：重启现有服务后执行同样恢复流程。已发布记录可恢复，全部校验成功但 complete 回执落盘失败的只读内容仍支持重复块确认与再次 complete。
3. 存储满、磁盘错误或损坏：接口失败关闭，不覆盖、不自动删除、不向项目写入。由本机管理员先停服务、备份整个 attachments 目录，再核对 record 清单与实际内容。`.pending-*` 是未发布初始化残留，确认无活跃进程且备份后才可按用户授权清理。损坏正式批次应隔离并让用户重新选择上传，不手改 hash 绕过校验。
4. 功能回滚：恢复上一版代码及客户端入口即可停止新上传，**保留 attachments 数据**。已有聊天中的路径引用仍需要对应文件；不得因回滚删除目录。未来迁移或清理需独立授权，并明确路径失效影响。

恢复验收：旧 ID 相同块可重放、无重复创建/发送、坏批次不会影响未关联项目文件；权限撤销仍拒绝继续写入/引用；所有内容恢复应先通过 SHA256 校验。
