# 云端控制台

云端保存用户账号、工作区授权、短期绑定申请和账号会话。用户通过 iOS 注册、密码登录或账号登录码登录，登录后只能读取自己获授权的工作区。

云端 public URL 应与 `carryon/product.json` 一致，自托管时显式配置对应地址。现有部署使用 `python3 -m carryon.console configure --config 配置路径 --public-url HTTPS地址`；管理员配置与普通用户自助注册分别管理。

## 用户接口

- `POST /console/register`：创建用户账号并登录。
- `POST /console/login`、`POST /console/logout`：密码登录／注销当前会话及其订阅和推送关联。
- `POST /console/password`：验证当前密码后修改本账号密码，撤销该账号旧会话。
- `GET /console/session`：返回当前账号及其授权工作区，不返回设备 Token。
- `GET /console/binding/pending`、`POST /console/binding/respond`：目标账号查看、确认或拒绝电脑申请。
- `POST /console/binding/inspect`、`POST /console/binding/accept`：已登录账号核对及接受工作区绑定码。

## 电脑接口

`POST /console/binding/start` 创建短期申请，带 `targetAccount` 时定向到该账号，否则返回扫码绑定地址。`poll` 只能用电脑独有的领取秘密读取已确认结果；二维码秘密与领取秘密不同。`manage` 通过对应设备凭证管理当前工作区成员，不能签发用户登录态。

账号登录二维码使用 `/console/qr/*`，需目标账号密码验证及电脑批准。设备 Token 或其他工作区成员身份不构成登录授权。

HTTP、实时流、文件、图片、任务和推送均继续执行工作区权限校验。断网保留绑定；明确凭证失效后由电脑进入恢复流程，见 [ONBOARDING.md](ONBOARDING.md)。

反向代理、TLS、服务管理和运行检查见 [deployment/README.md](../deployment/README.md)。Apple webcredentials 文件生成及正式签名验收条件见初始化文档。源代码本地构建不代表正式域名及生产服务已部署。
