# 学校 WebVPN 与常在线服务器

`bnul` 可以在 VPS 本机运行。默认直连；配置 `BNUL_TRANSPORT=auto`，或在 `~/.config/bnul/settings.json` 中设置 `transport: auto` 后，CLI 会在业务请求前自动选择直连或学校 WebVPN。API token 失效时，CLI 仍会经 WebVPN 用 HTTP 自动登录学校 CAS，不需要浏览器；只有 WebVPN 自身失效时才需要扫码。`BNUL_BROWSER_EXECUTABLE`（或 settings 的 `browser_executable`）可以指定已有的 Chrome。

学校传统 SSL VPN 与 WebVPN 微信扫码是两个不同的入口，不要混称为"密码自动登录"。已开通 SSL VPN 的 Linux 用户，按仓库 `deploy/linux/README.md` 部署 `bnul vpn run` 和 systemd 自动重连；普通安装和业务命令不会改动路由。

## 遇到 WEBVPN_LOGIN_REQUIRED

1. 运行 `bnul --json auth webvpn`，命令会等到二维码就绪才返回，无需另外轮询。读取 `data.status`：
   - `scan_required`：在当前聊天中显示 `data.qr_path` 指向的学校官方二维码图片。
     - Hermes：回复中单独一行原样输出 `data.media`（`MEDIA:` 加实际绝对路径），不加代码围栏。
     - 其他 agent：使用各自的图片展示工具。
     - 不要只发服务器上的文件路径，也不要让用户去打开电脑。
   - `already_authenticated`：无需扫码，直接重跑原命令。
   - 仍为 `starting`（极少见）：直接再运行一次同一命令，它会继续等待同一次尝试，不需要自己计时或等待。
   - `failed` 或返回格式异常：如实报错，不循环索要扫码。
2. 用户说已扫码后，直接重跑原命令，由原命令本身验证登录是否成功。不能只凭用户的话判断登录已完成。
3. 重跑后仍然返回 WEBVPN_LOGIN_REQUIRED 时，运行一次 `bnul --json auth webvpn --status`：
   - `qr_expired`，或用户要求换图：运行 `bnul --json auth webvpn --refresh`，发送新返回的图片，不复用旧路径。
   - `scan_required`：说明尚未完成扫码。

写请求已提交、但结果不明时，按 SKILL 中的核实规则处理，不因恢复登录而重复提交。不要把 Cookie 发到聊天里。

二维码默认保存在 `~/.hermes/image_cache/bnu-webvpn/`，可用 `BNUL_QR_DIR` 指定可发送图片的目录。学校 Cookie 保存在私有目录 `~/.config/bnul-webvpn/`，不要和图片放在同一个可公开发送的目录。学校追加验证码、二次认证或修改账号权限时，仍由用户本人处理。
