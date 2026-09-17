# iOS 与 Mac App 更新

两端提供手动检查更新。iOS 从“我的 → CarryOn 版本”进入；Mac 从应用菜单或左侧“检查更新…”进入。当前版本来自应用 Bundle，不依赖工作区服务版本。

检查使用独立、无登录凭证的 HTTPS 请求，不停止后台服务、不重放任务。无正式发布、未配置当前渠道或当前架构时显示“尚未发布可用版本”；网络失败单独报错，不误报“已是最新版本”。

- iOS：开发 Debug 与 TestFlight 沙盒收据使用 `testflight` 渠道；App Store 正式收据使用 `app-store`。发现更新后打开 TestFlight 邀请页或 App Store 页面，由 Apple 完成安装。同版本更高 build 也会被识别。
- Mac：只选择当前运行架构对应的官方 DMG。点击后由浏览器下载；打开 DMG，将 CarryOn 拖入“应用程序”替换旧版。应用不执行下载脚本或自动覆盖自身。CLI 更新仍走原有 `carryon update`，此入口不会更新 CLI。
- 高于当前系统要求的版本会显示最低 iOS/macOS 版本，不提供不可安装的更新按钮。

## 发布清单

两个客户端使用同一份公开清单：

`https://github.com/hanzeal-ai/CarryOn/releases/latest/download/app-updates.json`

清单由正式 GitHub Release 附件承载。仓库目前没有正式 Release，iOS 也没有 Apple 分发链接，因此本次交付只接好更新流程，不创建或发布版本。

Swift 解析、版本比较、可信地址校验和网络读取的唯一源文件是 `iOS/CarryOn/Core/AppUpdate.swift`。iOS 通过 CarryOnCore 使用；Mac 构建和桌面验证脚本直接编译同一文件。

## 准备发布

1. 递增对应平台的真实版本：Mac 使用 `carryon.__version__`（同时保持 Python 项目版本一致）；iOS 使用 Xcode 的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`。
2. iOS 在 TestFlight 可安装或 App Store 已发布后，更新 `release/ios-updates.json`。每个渠道最多一条记录；尚未发布的渠道不填。当前文件为 `[]`，不包含虚构下载地址。
3. 在目标架构运行 `scripts/build_release.py`。它在生成 DMG 后自动生成 `dist/app-updates.json`，并将清单加入 `SHA256SUMS`。它不上传或发布。
4. 若同一发布包含两种 Mac 架构，用生成脚本合并两个实际存在的 DMG。不要用缺失架构的文件名冒充产物。
5. 完成签名、公证及目标设备验收后，经发布授权，将清单、相应 DMG、CLI 包和 SHA256SUMS 一起上传到正式、非 prerelease 的 `v版本` Release。GitHub Release 的 latest 下载入口必须指向这次发布。

```sh
python3 scripts/build_app_updates.py \
  --mac-dmg dist/CarryOn-0.3.0-macos-arm64.dmg \
  --mac-dmg dist/CarryOn-0.3.0-macos-x86_64.dmg \
  --notes-file /实际路径/更新说明.txt \
  --output dist/app-updates.json
```

上述文件名仅演示下一版本。合并清单或修改说明后，需要重新生成最终附件的 SHA256SUMS，随后再发布。只有 iOS 更新时可省略 `--mac-dmg`，但应保留当前仍可下载的 Mac 记录：传入最近已发布的实际 DMG 生成完整清单，避免 latest 发布丢失其他平台的更新信息。

`release/ios-updates.json` 中每条记录包含：

| 字段 | 内容 |
| --- | --- |
| `platform` | `ios` |
| `channel` | `testflight` 或 `app-store` |
| `bundleIdentifier` | `com.hanzeal.carryon` |
| `version` / `build` | 与已上传的 iOS 包一致，均为字符串 |
| `minimumSystemVersion` | 例如 `17.0`，须与该包最低系统要求一致 |
| `url` | 真实的 `https://testflight.apple.com/join/…` 或 `https://apps.apple.com/…/id…` 地址 |
| `notes` | 纯文本更新说明 |

客户端拒绝非 HTTPS、其他仓库的 Mac 安装包、非 Apple 的 iOS 更新地址、错误 Bundle ID、重复渠道和超限清单。清单不保存任何签名凭证或登录密钥。

## 验证与恢复

```sh
swift test --package-path iOS --filter update
python3 -m unittest discover -s tests -p test_app_updates.py -v
```

恢复发布清单可重新上传已验证的上一份清单；已安装版本不会因清单回退而被降级。Mac 用户保留旧 DMG可手动恢复旧应用，工作区数据不由本流程清理。iOS 的版本恢复遵循 Apple 分发渠道限制。

真实商店跳转后的安装、Mac 的公开签名/公证与真机升级保留数据，需要在正式发布时验证。构建和隔离测试不能替代这些验收。
