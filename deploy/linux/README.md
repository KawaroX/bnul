# 常在线 Linux 服务器

学校 WebVPN 微信登录与传统 SSL VPN 账号密码登录是两个不同入口。SSL VPN 必须先在北师大微信门户 → 信息网络中心 → SSL VPN 申请中开通；不尝试绕过学校权限。学校官方介绍：https://vpn.bnu.edu.cn/in.php。

先安装正式版本 bnul 和浏览器，以及系统 `openconnect`、`iproute2`。不要在命令行或仓库填写密码。

```sh
uv tool install git+https://github.com/KawaroX/bnul.git@v0.4.0
bnul auth install-browser --with-deps
sudo apt-get install --no-install-recommends openconnect iproute2
```

按实际安装位置修改 [bnul-sslvpn.service](bnul-sslvpn.service) 的 `ExecStart`。用环境或现有秘密管理器注入 `BNUL_USERNAME`、`BNUL_PASSWORD`；已有私有 dotenv 文件时，可在服务中设置 `Environment=BNUL_CREDENTIAL_ENV=/绝对路径/现有.env`，程序只读取这两个键。不要提交该文件。启用服务需要管理员权限：

```sh
sudo install -m 644 bnul-sslvpn.service /etc/systemd/system/bnul-sslvpn.service
sudo systemctl daemon-reload
sudo systemctl enable --now bnul-sslvpn
```

服务每次重新建立连接时重新使用账号密码。认证被拒绝时退出 78，停止重复尝试，防止错误密码循环；修正凭据后 `systemctl restart bnul-sslvpn`。其他连接退出由 systemd 重新启动。路由钩子仅设置当前 `libseat.bnu.edu.cn`、`cas.bnu.edu.cn` 的 IPv4 `/32` 路由，不更改默认路由、系统 DNS、其他代理或服务。学校会话过期、网络中断后的重新认证仍受学校服务及账号权限约束。

可在运行 bnul 的用户目录 `~/.config/bnul/settings.json` 设置：

```json
{"transport": "auto"}
```

auto 在发送选座 token 或业务请求之前，先无凭据检查直连是否可用；可用则走原生请求，否则选择保存在该用户服务器上的 WebVPN。未配置时默认 direct，兼容已有桌面使用。WebVPN 需要认证时运行 `bnul --json auth webvpn`，将 `data.media` 的图片发给本人手机；`--status` 检查结果，`--refresh` 换新图。不要求其他电脑保持在线。

已有 Chrome 可设置 `BNUL_BROWSER_EXECUTABLE`，或在 settings.json 配置 `browser_executable`。二维码位于 `~/.hermes/image_cache/bnu-webvpn/`，以便 Hermes 在不放宽媒体安全策略的情况下发送；其他 agent 可设置 `BNUL_QR_DIR` / `qr_directory`。Cookie 仍只保存在私有 `~/.config/bnul-webvpn/`，不发送给聊天。
