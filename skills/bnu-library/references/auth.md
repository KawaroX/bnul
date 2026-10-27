# 登录与凭据

日常直接执行业务命令。本地会话缺失或服务器判定登录失效（20003/401）时，CLI 会在后台用账号密码登录学校 CAS，成功后自动重试一次查询。直连和 WebVPN 都直接发 HTTP 请求，不需要浏览器；经 WebVPN 较慢，约 20–30 秒。写操作提交前 CLI 会自动检查会话，已提交的写请求不会重放。网络错误不会触发自动登录。

自动登录按顺序读取账号密码，配置任一种即可，不需要运行登录命令：
1. 环境变量 `BNUL_USERNAME` 和 `BNUL_PASSWORD`，两者须同时设置；或用 `BNUL_CREDENTIAL_ENV` 指向已有的 dotenv 文件，只读取这两个键。适合没有桌面或 Secret Service 的服务器。
2. `bnul auth setup` 保存的凭据：优先存入系统凭据库（macOS 用 Keychain，Windows 用 Credential Manager，Linux 用 Secret Service）；凭据库不可用时，经用户在终端确认后改存 `~/.config/bnul/credentials.env`（明文，仅当前用户可读）。

命令：
- `bnul auth setup`：首次配置。用户在本机终端隐藏输入密码。这一步只保存，密码是否有效以实际认证为准。不要让用户把密码发到聊天里，也不要由 agent 拼接进命令或环境变量。
- `bnul auth login`：可见浏览器登录，用于验证码、二次认证等情况。需要浏览器支持；返回 BROWSER_SUPPORT_MISSING 时，按报错中的命令让用户自己安装。
- `bnul auth status`：检查当前会话（不自动恢复），显示账号（打码）、会话保存时间、连接方式、自动登录凭据来源、自动登录方式和预约额度，不显示密码；未登录时给出原因和下一步。
- `bnul auth logout`：删除本机的会话、已保存的账号密码（凭据库和凭据文件）、登录浏览器资料和 WebVPN 会话。环境变量中的账号密码无法由 CLI 删除，结果会提示仍存在。
- `bnul auth install-browser`：安装浏览器支持后，为可见登录安装 Chromium，Linux 可加 `--with-deps`。
- 换用已安装的 Chrome 或 Edge：`bnul auth login --browser chrome`（或 `msedge`），选择会保存。

同一账号同一时间只有一个有效会话，任何一处新登录都会顶掉此前的会话。用户反映"经常掉线"时，多半是手机、网页或另一台设备也在登录，CLI 会自动重新登录，不需要排查。

设置了 `BNUL_TOKEN` 时自动恢复会被禁用，以免覆盖用户指定的凭据。`--json`、`--no-proxy`、`--transport` 放在子命令前后都可以。

`SESSION_SIGNING_KEY_MISSING` 表示会话缺少与 token 配对的签名密钥，CLI 会自动重新登录一次，这不是 VPN 配置错误。自动恢复仍失败时，说明具体错误并停止，不要自行猜接口、读取登录秘密或调试官网。用户明确要求排查工具时再诊断。

无桌面环境下自动登录遇到验证码时，仍需在可见环境中处理。官网验证码验证所得的 token 可以通过 `BNUL_CAP_TOKEN` 传给 book。
