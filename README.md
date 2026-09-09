# bnul

北京师范大学图书馆自习座位预约命令行工具，附带可安装的 AI skill。支持 macOS、Windows、Linux；查询座位、选择日期与起止时间、预约、查看使用记录和结束使用。非学校官方项目。

## 安装

推荐使用 [uv](https://docs.astral.sh/uv/getting-started/installation/)，无需克隆仓库，也无需创建虚拟环境：

```sh
uv tool install git+https://github.com/KawaroX/bnul.git
uv tool update-shell
```

重开终端后直接使用：

```sh
bnul --help
bnul auth install-browser
bnul auth setup
bnul --json current
```

`auth setup` 只需配置一次学校账号密码；日常命令会在会话失效后后台自动登录。浏览器使用独立资料，不读取个人浏览器数据。

也可使用 [pipx](https://pipx.pypa.io/stable/installation/)：

```sh
pipx install git+https://github.com/KawaroX/bnul.git
pipx ensurepath
```

重开终端后运行同样的 `bnul` 命令。以上命令适用于 Windows PowerShell、macOS 和 Linux。无需填写 Python 或 CLI 绝对路径。若需要固定版本，将安装 URL 改为 `git+https://github.com/KawaroX/bnul.git@v0.1.0`。

Linux 缺少浏览器系统库时执行 `bnul auth install-browser --with-deps`，系统依赖安装可能要求管理员权限。默认使用上述命令安装的 Chromium；也可通过 `BNUL_BROWSER=chrome` 或 `msedge` 使用已安装的 Chrome/Edge。

## 安装 skill

安装 CLI 后执行：

```sh
bnul skill install
```

默认安装到 `$CODEX_HOME/skills/bnu-library`，未设置 CODEX_HOME 时为用户目录的 `.codex/skills/bnu-library`。在新任务中使用 `$bnu-library`，或直接用自然语言要求查询/预约北师大座位。安装到其他 agent 时，用 `bnul skill install --dest "目标技能文件夹"` 指定该 agent 接受的 skill 路径。

skill 随安装包发布，不依赖源码目录；只调用 PATH 中的 `bnul`。也可直接从本仓库复制整个 [skills/bnu-library](skills/bnu-library) 文件夹。skill 末尾包含 CLI 缺失时的安装指引。

## 自动登录

| 命令 | 用途 |
|---|---|
| `bnul auth setup` | 一次配置学校账号密码到系统凭据库 |
| `bnul auth login` | 可见浏览器登录，处理验证码、二次认证 |
| `bnul login` | `auth login` 的兼容别名 |
| `bnul auth status` | 只检查当前会话，不自动恢复 |
| `bnul auth forget` | 删除已保存的账号密码 |
| `bnul auth clear` | 删除 CLI 会话，保留密码与浏览器状态 |
| `bnul auth import` | 备用：隐藏输入已有 token/curl |
| `bnul auth exchange-link` | 高级诊断：兑换登录 URL 票据 |

普通业务命令自动处理明确的会话失效，后台恢复后重试查询一次。无需每分钟登录，也无需事先知道会话期限。样例 URL JWT 的 60 秒期限与 API 会话期限不同。学校要求验证码/二次认证或密码错误时才需要人工处理；每条命令最多恢复一次、提交密码一次，避免循环登录。setup 表示已保存，实际有效性以学校认证为准。

macOS 使用 Keychain，Windows 使用 Credential Manager，Linux 使用 Secret Service（需要已启动且解锁的服务与会话 D-Bus）。无桌面服务器可通过秘密管理器注入 `BNUL_USERNAME` 和 `BNUL_PASSWORD`，无需系统凭据库；程序不将其写入文件。两者须同时设置，优先于系统库。后台模式不需要显示器，但遇到人工验证仍需要可见桌面。

会话文件默认为 `~/.config/bnul/session.json`，用 `BNUL_CONFIG` 可改变位置。设置 `BNUL_TOKEN` 时优先使用该 token，禁用自动恢复以免覆盖指定身份。密码不写入 JSON 或日志。auth clear 不注销学校会话，下次业务命令可能再次自动登录。

## 按自习计划推荐座位

安装 skill 后，可以直接对 AI 说：

> 今天晚上 7 点到 9 点想在图书馆自习，帮我推荐几个座位。
>
> 我从现在开始到 22 点自习，看看三楼有哪些位置合适。

也可以直接运行：

```sh
bnul --json recommend --date today --start 19:00 --end 21:00
bnul --json recommend --date today --start now --end 22:00
bnul --json recommend --date tomorrow --start 19:00 --end 21:00 --room 1888096971220160512
```

默认查主馆，推荐 3 个候选，跨房间逐座检查，最多校验 30 座；可指定 --building/--floor/--room，以及 --limit/--max-checks（最多 200）。每个候选均校验服务器返回的开始、结束时间，覆盖完整计划时段。输出位置、座位号、理由与校验时间，不使用当前空闲状态代替完整时段校验，也不编造靠窗/插座等属性。

若达到检查上限，searchExhausted=false，不能把暂未找到理解为全馆无座。候选仅反映查询时的可选时段，不保证账号资格或稍后仍可预约。推荐命令不创建预约；决定后再运行 book --execute。

## 查询与预约

```sh
bnul --json buildings
bnul --json rooms --date tomorrow --start 19:00 --end 21:00
bnul --json seats --date tomorrow --start 19:00 --end 21:00 --label 008
bnul --json times --seat 1888111985066872919 --date tomorrow --start 19:00
bnul --json current
bnul --json recent
bnul --json life 预约ID
```

默认主馆、3F 自习区（低声区、朗读区），可指定 `--building`、`--floor`、`--room`。日期支持 today/tomorrow/YYYY-MM-DD，使用上海时区。固定时间为 HH:MM，通常只能选择整点或半点，必须出现在服务器可选列表中，不支持跨天。“现在”使用 `--start now`（也支持 `--start 现在` 或 `--start=-1`），仅限今天。查询结束时间时使用当前上海时间的分钟数，提交预约时严格发送 -1。记录中出现 14:04 代表实际落定的开始时间，不证明可以直接提交任意分钟。以实时可选时段为准；当前 IN_USE 不代表未来不可约，afterFree 也不保证整个目标时段可约。

```sh
# 从现在开始（默认仅预览）
bnul --json book --seat 1888111985066872919 --date today --start now --end 19:30
# 默认仅校验并预览
bnul --json book --seat 1888111985066872919 --date tomorrow --start 19:00 --end 20:30
# 实际提交
bnul --json book --seat 1888111985066872919 --date tomorrow --start 19:00 --end 20:30 --execute
# 结束使用：先预览，再按实际预约 ID 提交
bnul --json stop
bnul --json stop --execute --expect-id 预约ID
```

成功预约不等于签到，按服务端 message 完成签到。RESERVE 是待签到，CHECK_IN 是使用中，AWAY 是暂离，STOP 是结束。工具不自动取消原预约、不绕过验证码。写操作先检查会话；请求提交后若失败不自动重放，应查 current/recent 确认结果。服务端 stop 无 ID 参数，本地 ID 检查无法完全消除并发更换预约的竞态。

`--json` 输出结构为 `ok/data` 或 `ok/error/code/data`，失败退出码非零。全局参数放在子命令前；系统代理不可用时加 `--no-proxy`，例如 `bnul --no-proxy --json current`。TLS 校验始终开启。

## 更新与卸载

```sh
uv tool upgrade bnul
bnul auth install-browser
bnul skill install
# 卸载
uv tool uninstall bnul
```

pipx 用户使用 `pipx upgrade bnul` / `pipx uninstall bnul`。浏览器库升级后可能需重新安装 Chromium。卸载 CLI 不删除凭据、浏览器资料或 skill；如需清除密码，先运行 `bnul auth forget`。

## 开发与验证

```sh
git clone https://github.com/KawaroX/bnul.git
cd bnul
uv venv
uv pip install -e .
uv run python -m unittest discover -s tests -v
```

真实查询、签名与时段预览已验证；密码提交、恢复与平台分支有模拟测试。三平台 CI 覆盖安装和自动化测试；校园账号的 Windows/Linux 登录尚未实机验证；开发期间未真实预约或结束使用。暂不包含定时抢座、自动续约或地图 UI。

协议依据用户提供的抓包与 2026-09-09 官网公开前端。请求签名通过系统配置解密获得，每次请求生成新的 UUID、毫秒时间戳和 HMAC-SHA256，不重放抓包签名。

## License

MIT
