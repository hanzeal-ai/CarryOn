# 远程待机（macOS）

在本机 example 的「云端接入与本地服务」里打开「远程待机」。默认关闭；选择会保存在用户状态目录的 `standby.json`，服务下次启动时恢复。无需 sudo，不修改系统的永久睡眠设置。

- 接通电源且保护进程正常时显示「已生效」。屏幕可以熄灭或锁定，ConnectNow 与 Codex 必须保持运行。
- 使用电池时显示「等待接电」，不会为远程待机阻止睡眠；重新接电后，系统恢复该保护的适用条件。
- 合盖、手动睡眠、关机、系统重启、掉电仍可能中断连接。它不是“让已睡眠的电脑执行任务”的能力，也不能保持 Wi-Fi 或 Codex 本身永不掉线。
- 关闭开关或退出 ConnectNow 服务会释放保护；退出服务不会忘记已保存的偏好。
- 若系统电源状态读取失败，或保护进程退出，页面会显示未知或异常，不声称保护已生效。

实现使用系统 `/usr/bin/caffeinate -s -w <服务PID>`；`-s` 仅在交流电供电时有效，`-w` 将保护生命周期绑定到服务 PID。没有使用阻止显示器休眠的 `-d`，也没有使用会在电池供电时阻止闲置睡眠的 `-i`。

接口仅限已配对的本机客户端：`GET /api/service/standby` 读取状态，`POST /api/service/standby` 使用 `{"enabled":true}` 或 `{"enabled":false}` 修改。云端即使有远程控制权限，也不能访问该本机生命周期设置。

验证：`python3 -m unittest discover -s tests -p test_standby.py -v`。实际 Mac 可通过 `pmset -g assertions` 检查属于本服务 caffeinate 子进程的 `PreventSystemSleep` 断言；关闭后该断言应消失。其他应用仍可能持有自己的防睡眠断言。
