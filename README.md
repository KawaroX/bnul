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
bnul current
```

`auth setup` 只需配置一次学校账号密码；日常命令会在会话失效后后台自动登录。浏览器使用独立资料，不读取个人浏览器数据。

也可使用 [pipx](https://pipx.pypa.io/stable/installation/)：

```sh
pipx install git+https://github.com/KawaroX/bnul.git
pipx ensurepath
```

重开终端后运行同样的 `bnul` 命令。以上命令适用于 Windows PowerShell、macOS 和 Linux。无需填写 Python 或 CLI 绝对路径。若需要固定版本，将安装 URL 改为 `git+https://github.com/KawaroX/bnul.git@v0.5.4`。

Linux 缺少浏览器系统库时执行 `bnul auth install-browser --with-deps`，系统依赖安装可能要求管理员权限。默认使用上述命令安装的 Chromium；也可通过 `BNUL_BROWSER=chrome` 或 `msedge` 使用已安装的 Chrome/Edge。

## 预约临期监控（0.5.2）

`bnul watch` 默认只观察，每天北京时间 08:00–23:00 查询，夜间休眠且不触发登录恢复或告警。白天无预约每 30 分钟、使用中每 20 分钟、暂离剩余超过 10 分钟时每 7 分钟、暂离剩余不超过 10 分钟及未签到时每 2 分钟检查；`--execute --notify slack` 开启临期自动处理和通知。未签到或暂离距离截止不足 5 分钟时，取消/结束后尝试重约原座位至原结束时间，已签到使用中的预约不处理。暂离起点按学校实际返回的当天秒数解析，并与分钟及显示字段校验；预约自然结束早于暂离截止时只观察。告警区分期限解析、登录、查询和心跳故障。登录失效自动恢复，失败持久化并通知；通知可重试，写操作结果不明不重复提交。

```sh
bnul watch --once
bnul watch --execute --interval 120 --notify slack
bnul --json watch --status
```

长期运行请按 [监控部署与验收说明](deploy/linux/WATCH.md) 配置 systemd、现有凭据和独立心跳告警。学校取消次数限制、验证码或座位竞争可能使重约失败，此时会通知；达到当日重约上限时只释放，不重约。

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

从 0.4.1 起，支持学校将签名密钥改为通过登录响应的 `userInfoRes.hmacKey` 下发。CLI 会将密钥与对应 token 一起保存，仍按原有 AES 算法解密并为每次请求生成签名；不会跳过签名校验。旧会话缺少密钥时，普通查询自动重新登录一次。仅导入 token 或显式设置 `BNUL_TOKEN` 而没有配对密钥时会返回 `SESSION_SIGNING_KEY_MISSING`，请使用正常浏览器登录保存完整会话。

## 常在线 VPS 和校外网络

Linux 无桌面服务器可使用学校官方 SSL VPN 账号密码登录并由 systemd 自动重连，且只将选座与 CAS 两个学校域名通过该连接。服务需要学校单独开通和系统管理员部署，安装 CLI 不会自动改变网络。配置、服务模板和验证步骤见 [Linux 部署](deploy/linux/README.md)。

另支持学校官方 WebVPN 微信认证，登录会话与浏览器保存在运行 bnul 的当前电脑或 VPS：

```sh
bnul --json auth webvpn            # 返回二维码路径及 MEDIA 行，后台等待本人确认
bnul --json auth webvpn --status   # 确认 authenticated / already_authenticated
bnul --json auth webvpn --refresh  # 旧二维码过期时换新图
bnul --transport webvpn current
```

默认 `direct` 保持原有行为。`--transport auto` / `BNUL_TRANSPORT=auto` 在业务请求前无凭据检测直连，不通时使用本机 WebVPN；不会在结果未知的写请求之后切换连接并重放。`bnul-vpn-login` 是扫码助手的兼容入口，输出原始状态 JSON。WebVPN 本身的微信登录不冒充为密码自动登录；有权限的 SSL VPN 连接及选座 CAS 会话使用账号密码自动恢复。

可在 `~/.config/bnul/settings.json` 配置 `transport`、`browser_executable`、`webvpn_profile`、`qr_directory`；对应环境变量分别是 `BNUL_TRANSPORT`、`BNUL_BROWSER_EXECUTABLE`、`BNUL_WEBVPN_PROFILE`、`BNUL_QR_DIR`，环境变量优先。`BNUL_SETTINGS` 可指定设置文件。已有独立 Chrome 可以直接复用可执行文件，不读取个人浏览器资料。

## 楼馆、楼层与房间别名

每个已登记位置提供一个固定别名，对应一个官方 ID。日常使用别名即可；楼层和房间的别名按所选楼馆解析。旧版参数写法继续兼容，新示例统一使用别名。

| 别名 | 楼馆 |
| --- | --- |
| `b1` | 主馆 |
| `b2` | 主馆南区 |
| `b3` | 教育学分馆 |
| `b4` | 沙河 |

| 别名 | 楼层 |
| --- | --- |
| `f1` | 1 层 |
| `f2` | 2 层 |
| `f3` | 3 层 |
| `f4` | 4 层 |
| `f5` | 5 层 |
| `f6` | 6 层 |
| `f7` | 7 层 |
| `f8` | 8 层 |

楼层别名用于 `rooms` / `recommend`，省略 `--floor` 表示全部楼层。2026-10-18 核对的范围：主馆 `f1`–`f8`；主馆南区 `f3`；教育学分馆 `f1`；沙河 `f1`–`f2`。别名固定对应实际层数，不按接口返回顺序编号。

主馆房间：

| 别名 | 房间 |
| --- | --- |
| `r1` | 1F 师樾厅 |
| `r2` | 2F 自习区 |
| `r3` | 3F 多媒体中心 |
| `r4` | 3F 自习区 |
| `r5` | 4F 借阅区 |
| `r6` | 5F 借阅区 |
| `r7` | 6F 阅览区 |
| `r8` | 7F 阅览区 |
| `r9` | 8F 借阅区 |

其他楼馆的房间同样有固定别名：主馆南区 `r1` 为工具报刊外文阅览区；教育学分馆 `r1`、`r2` 分别为 108、149；沙河 `r1`、`r2` 分别为 G 区分馆一层、二层。完整分馆表见 [skill](skills/bnu-library/SKILL.md#房间别名)。房间别名由代码固定，不随清单排序、安装时间或本机配置变化；新位置不会自动分配别名。

```sh
bnul seats --room r4 --date tomorrow --start 19:00 --end 21:00
bnul recommend --building b1 --floor f3 --date tomorrow --start 19:00 --end 21:00
bnul rooms --building b2 --floor f3
bnul seats --building b3 --room r1 --date tomorrow --start 19:00 --end 21:00
```

优先使用别名，无需先列清单。别名无法识别或位置未列出时，用 `bnul buildings` 获取楼馆、楼层 ID；用 `bnul room-list --building 别名或ID` 获取房间 ID，再将返回的 ID 传给对应参数。清单文本显示名称、别名和 ID；JSON 保留完整字段，包括旧版兼容字段。名称仅用于辨认位置，表格不代表实时有空位。

CLI 解析楼馆与楼层别名时共用一次实时目录查询，完整 ID 不新增目录请求。未知、歧义或禁用位置不会改选其他位置。主馆 `seats` / `book` 默认使用 `r4`；其他楼馆必须指定 `--room`。`recommend` 未指定房间时在所选楼馆跨房间搜索。

`book` 不需要 `--floor`：CLI 按房间确认目标座位，再校验该座位的时段；最终预约接口只需要座位和时段。楼层参数用于查找房间、推荐座位时缩小范围。

## 按自习计划推荐座位

安装 skill 后，可以直接对 AI 说：

> 今天晚上 7 点到 9 点想在图书馆自习，帮我推荐几个座位。
>
> 我从现在开始到 22 点自习，看看三楼有哪些位置合适。

也可以直接运行：

```sh
bnul recommend --date today --start 19:00 --end 21:00
bnul recommend --date today --start now --end 22:00
bnul recommend --date tomorrow --start 19:00 --end 21:00 --room r4
```

默认查主馆，推荐 5 个候选，跨房间逐座检查，最多校验 50 座；可指定 --building/--floor/--room，以及 --limit/--max-checks（最多 200）。默认不预设个人区域偏好，跨区域轮流检查。若偏好某些区域，可以指定顺序：

```sh
bnul recommend --date today --start now --end 22:00 --room-order 'r4,r3,r2'
```

指定顺序时严格先查首选区域，该区域候选查完才到下一项，找到足够结果或达到检查上限即停，只查列出的区域。与 --room 互斥；重复、未知或与楼层范围冲突的区域会报错。每个候选均校验服务器返回的开始、结束时间，覆盖完整计划时段。输出位置、座位号、理由与校验时间，不使用当前空闲状态代替完整时段校验，也不编造靠窗/插座等属性。

若达到检查上限，searchExhausted=false，不能把暂未找到理解为全馆无座。候选仅反映查询时的可选时段，不保证账号资格或稍后仍可预约。推荐命令不创建预约；决定后再运行 book --execute。

## 输出格式

所有命令提供两种输出，按阅读或程序处理需要自由选择：

- 默认：纯文本，无需添加参数。按命令用途展示主要信息，隐藏空值和内部元数据，保留本次查询返回的全部记录和完整消息。`--text` 只是显式选择同一默认格式。
- 前置 `--json`：完整命令结果，保留所有字段。成功为 `{"ok": true, "data": ...}`，失败保留错误信息、错误码及详情。可直接阅读，也可用 Python、jq 等解析；大结果可重定向到文件。

| 命令 | 文本主要信息 |
| --- | --- |
| buildings | 可预约日期、楼馆开放时间、楼层和 ID |
| room-list / rooms | 房间名称和 ID；时段查询另显示座位、空闲及设施数量 |
| seats | 全部匹配座位的编号、位置、当前状态、afterFree 和 ID |
| times | 空闲时段、全部可选开始和结束时间 |
| recommend | 匹配座位、位置和 ID、校验时间、搜索范围和进度 |
| current / recent / history | 日期时段、位置、座位、状态、ID、实际使用和服务端提示 |
| life | 变更时间、事件、来源和说明 |

文本没有条数、字段数、深度或字符数截断，也不反复提示切换 JSON。历史记录仍按接口分页，推荐仍受用户指定的搜索上限控制；未查完时保留相应说明。空字符串、null 和空容器不输出字段，0 和 false 正常展示。

```sh
bnul seats --room r4 --label 008 --start now --end 15:00
bnul --json seats --room r4 --start now --end 15:00 > seats.json
```

JSON 的“完整”指该命令查询范围内的结果，不是所有底层 HTTP 响应的原样抓包。筛选、分页和推荐搜索上限仍生效；展示层不会为了缩短输出删除 JSON 字段或截断记录。不带 `--json` 的旧版缩进 JSON 已改为文本摘要，依赖结构化输出的脚本请显式加 `--json`。两种格式执行相同业务逻辑，切换格式不会增加查询或重复提交。

## 查询与预约

```sh
bnul buildings
bnul rooms --date tomorrow --start 19:00 --end 21:00
bnul seats --date tomorrow --start 19:00 --end 21:00 --label 008
bnul times --seat 1888111985066872919 --date tomorrow --start 19:00
bnul current
bnul recent
bnul life 预约ID
```

默认楼馆为主馆；`seats` / `book` 默认房间为 `r4`，`rooms` / `recommend` 默认跨房间查询。楼层筛选仅用于 `rooms` / `recommend`，完整选择规则见前文“楼馆、楼层与房间别名”。日期支持 today/tomorrow/YYYY-MM-DD，使用上海时区。固定时间为 HH:MM，通常只能选择整点或半点，必须出现在服务器可选列表中，不支持跨天。“现在”使用 `--start now`（也支持 `--start 现在` 或 `--start=-1`），仅限今天。查询结束时间时使用当前上海时间的分钟数，提交预约时严格发送 -1。记录中出现 14:04 代表实际落定的开始时间，不证明可以直接提交任意分钟。以实时可选时段为准；当前 IN_USE 不代表未来不可约，afterFree 也不保证整个目标时段可约。

```sh
# 从现在开始（默认仅预览）
bnul book --seat 1888111985066872919 --date today --start now --end 19:30
# 默认仅校验并预览
bnul book --seat 1888111985066872919 --date tomorrow --start 19:00 --end 20:30
# 实际提交
bnul book --seat 1888111985066872919 --date tomorrow --start 19:00 --end 20:30 --execute
# 结束使用：先预览，再按实际预约 ID 提交
bnul history --page 1 --page-size 10
bnul breach --page 1 --page-size 10

# 未签到（RESERVE）：取消预约
bnul cancel
bnul cancel --execute --expect-id 预约ID

# 已签到（CHECK_IN / AWAY）：结束使用
bnul stop
bnul stop --execute --expect-id 预约ID

# 省略 --expect-id：直接操作本次读取到的当前预约；-e / --exe 等同 --execute
bnul stop -e
```

从 0.3.2 起支持 `cancel`、`history` 和 `breach`。取消和结束均默认预览；`book`、`cancel`、`stop`、`watch` 的 `--execute` 均可简写为 `-e` 或 `--exe`。指定 `--expect-id` 时必须与当前预约一致，省略时使用同一命令内刚读取的当前预约 ID。cancel 与 stop 按实时状态执行：未签到（RESERVE）一律取消，已签到（CHECK_IN/AWAY）一律结束使用；命令与状态不符时自动改用正确操作，预览和结果会注明，JSON 带 `switched`、`requestedAction`、`action` 字段，执行结果原值放在 `result`。其他状态（如 STOP）报错，不执行。`history`/`breach` 保留服务端 `list`/`count`，每次只查询指定的一页；违约是否已过期不由 CLI 推断。

取消成功返回的数字保留原值；已核实官网前端将它显示为当天剩余取消次数。取消时间限制由服务端判定，不凭 `cancelMinute` 字段名推导。取消后 `current` 可能返回空字符串，表示没有当前预约。需要重新预约时重新校验可选时段，不保证座位仍可用或一定允许重约。

成功预约不等于签到，按服务端 message 完成签到。RESERVE 是待签到，CHECK_IN 是使用中，AWAY 是暂离，STOP 是结束。普通命令不自动取消原预约；显式启用 watch --execute 后按[监控规则](deploy/linux/WATCH.md)处理临期预约，不绕过验证码。写操作先检查会话；结果不明时，选择 current/recent 中最相关的一项查询核实，不自动重放。服务端 stop 无 ID 参数，本地 ID 检查无法完全消除并发更换预约的竞态。

`--json` 输出结构为 `ok/data` 或 `ok/error/code/data`，失败退出码非零。全局参数放在子命令前；系统代理不可用时加 `--no-proxy`，例如 `bnul --no-proxy current`。TLS 校验始终开启。

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

三平台 CI 覆盖安装和自动化测试；监控运行支持 Linux/macOS。登录与通知的实机验收、连续检查和真实预约操作须分别记录，单纯启动进程不代表验收通过。暂不包含定时抢座或地图 UI。

协议依据用户提供的抓包与 2026-09-09 官网公开前端。请求签名通过系统配置解密获得，每次请求生成新的 UUID、毫秒时间戳和 HMAC-SHA256，不重放抓包签名。

## License

MIT

查看已安装版本：`bnul -v` 或 `bnul --version`。该命令不登录、不访问网络，输出工具名称和已安装的版本号。
