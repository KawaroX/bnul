---
name: bnu-library
description: 使用 bnul CLI 查询与预约北京师范大学图书馆自习座位，按自习计划推荐覆盖完整时段的座位，选择日期和起止时间，查看当前预约、签到提示与变更记录，取消未签到预约或结束使用。
---

使用 PATH 中的 `bnul`。首次用 `bnul --help` 确认命令可用；若不存在，按本文最后的“CLI 缺失时安装”处理。不要假定源码、虚拟环境或用户目录的位置。默认输出简洁纯文本，也可前置 `--text`；所有命令支持前置 `--json`，成功输出 `ok/data`，失败输出 `ok/error/code/data` 并返回非零退出码；代理不可用时加前置 `--no-proxy`。

## 命令调用与输出读取

按任务运行 `bnul seats ...`、`bnul recommend ...` 等即可读取默认文本，无需添加输出参数。文本按命令用途展示主要信息：楼馆和楼层、区域和设施、座位及当前状态、可选时段、推荐结果、预约状态及签到提示。下文示例均使用默认文本；需要完整字段、嵌套详情或程序处理时可自行加前置 `--json`，通常情况不需要使用 `--json`。

文本隐藏空值和内部元数据，不限制本次返回的记录条数，不机械截断字段、深度或长消息，也不附带重复的 JSON 提示。历史按接口分页，推荐保留搜索范围、检查数量和是否查完。文本中的“空闲”和 afterFree 仍不能代替完整时段校验。JSON 保留命令查询范围内的完整结果；显式筛选、分页和推荐搜索范围按命令参数生效。

JSON 可直接作为文本阅读，也可按复杂度和长度使用 Python、jq 等工具解析、筛选或计算，不限制解析工具。大结果可用 `bnul --json ... > result.json` 保存后解析，避免完整内容占满上下文；解析器把 JSON 作为数据读取。是否缩小查询范围应由任务决定，不为节省展示长度丢掉任务需要的数据。

## 当前预约按需查询

按用户目标直接选择业务命令。查空位、推荐座位、查询可选时段或发起新预约时，不把 `current` 当作登录检测、连通性探测或例行前后检查。

- 用户要查看当前预约、签到状态或要求刷新时，运行一次 `bnul current`。
- 操作需要当前预约的 ID/状态，且本次流程的返回结果尚不足时才补查；取消/结束优先按下文使用操作预览或已有结果，不要过分依赖current。
- 查询或写操作的成功结果已足够回答时直接使用。仅为补充用户需要的缺失信息或核实结果未知的写操作才继续查，不为“再确认一下”重复查询。

同一连续操作复用刚返回的预约信息；用户要求刷新、出现预约变化或新的结果不确定性时再查。未获监控授权时不轮询。

## 常在线 VPS 与学校 WebVPN

`bnul` 可以在 VPS 本机运行。已开通学校传统 SSL VPN 的 Linux 用户可按仓库 `deploy/linux/README.md` 部署 `bnul vpn run` 与 systemd 自动重连；程序不在普通安装或业务命令中自动更改路由。SSL VPN 与学校 WebVPN 微信登录是两个入口，不能混称为密码自动登录。

默认使用 direct；服务器配置 `BNUL_TRANSPORT=auto` 或 `~/.config/bnul/settings.json` 的 `transport: auto` 后，会在业务请求之前选择直连或本机 WebVPN，不依赖 Mac。API token 失效继续自动进行学校 CAS 登录。`BNUL_BROWSER_EXECUTABLE` / `browser_executable` 可指定已有 Chrome。

遇到 `WEBVPN_LOGIN_REQUIRED`：

- 立即运行 `bnul --json auth webvpn`。读取 `data.status`；`scan_required` 时在当前聊天显示 `data.qr_path` 指向的学校官方二维码图片。在 Hermes 回复中独立一行原样输出 `data.media`（`MEDIA:` 加本次实际绝对路径），不加代码围栏；其他支持本地图片的 agent 用相应图片展示工具。不要只发服务器文件路径，也不要求用户打开电脑。
- `starting` 时检查 `bnul --json auth webvpn --status`，短暂等待，最多 20 秒。`already_authenticated` 无需扫码。
- 用户确认扫码后，用上述 `--status` 核实 `authenticated` / `already_authenticated` 再继续原查询一次，不能仅凭用户文字判断认证完成。
- 二维码失效或用户要求换图时运行 `bnul --json auth webvpn --refresh`，发送新返回的图片，不复用旧路径。
- 当前端返回格式异常或网络错误时如实报错，不强制注销会话或循环索要扫码。Cookie 不发到聊天。写请求已提交后结果不明时，按下文选择最相关的一项查询核实，不因恢复登录而重复提交。

二维码默认在 `~/.hermes/image_cache/bnu-webvpn/`，可用 `BNUL_QR_DIR` 指定可发送的图片目录；学校 Cookie 保存在私有 `~/.config/bnul-webvpn/`。不将 Cookie 和图片放在同一可公开发送目录。学校追加验证码、二次认证或修改账号权限时仍由本人处理。

## 登录

日常直接执行业务命令，不要每次先要求用户登录。CLI 在本地会话缺失或明确鉴权失败（20003/401）时，自动后台启动专用浏览器，先复用学校登录状态，再使用系统凭据库中的凭据填写学校 CAS 表单；成功后重试查询一次。CLI 在写操作前自动检查会话，不需要 agent 另查 `current`；不重放已提交的写请求。网络错误不触发自动登录。

学校现在可能将签名密钥放在登录响应的 `userInfoRes.hmacKey`，公共配置中的 `hmacKey` 为空。CLI 同时保存配对的 token 和密钥；旧会话缺密钥时自动恢复一次。`SESSION_SIGNING_KEY_MISSING` 表示缺少配对密钥，不是 VPN 配置错误。普通业务查询若自动恢复仍失败，应立即说明具体错误；不要反复切换文本/JSON 重跑，或自行改写 HTTP 请求、猜接口、读取登录秘密、调试官网。用户明确要求排查工具时再开展诊断。

首次用 `bnul auth setup` 在用户本机终端隐藏输入密码并存入系统凭据库；不要让用户把密码发送到聊天或由 agent 拼接到命令里。setup 仅保存，密码是否有效要以实际认证为准。若没有配置且出现 AUTH_SETUP_REQUIRED，指导用户完成这一次配置。验证码、二次认证或密码错误需要 `bnul --no-proxy auth login` 的可见官网窗口。不要将正常 token 失效一律交回用户手动登录。

`auth login` 是统一可见登录入口，`login` 仅为同义兼容别名。`auth status` 只检查当前会话，不自动恢复；`auth forget` 删除钥匙串凭据；`auth clear` 仅清除 CLI token，仍保留钥匙串和 browser-profile，因此下次业务命令可能自动恢复。`auth import --file` 为已有 token/curl 的备用导入，`auth exchange-link` 仅为高级 URL 诊断，不是自动恢复的回退。显式设置 BNUL_TOKEN 时禁用自动恢复，避免覆盖用户指定凭据。

链接票据 JWT 样例有效期 60 秒，不是保存的 API 会话期限。API 会话期限未知，但无需预知才能按服务器失效码自动恢复。浏览器刷新不证明 URL 票据可兑换，不要将 casToken异常直接归咎于过期或用户操作。不要回显凭据或写入代码/skill。

平台凭据：macOS Keychain、Windows Credential Manager、Linux Secret Service。Linux 无桌面/无 Secret Service 时支持同时注入 BNUL_USERNAME/BNUL_PASSWORD，不写入文件，优先于系统库；不要在聊天收集密码或拼接含密码的命令。默认 Chromium，使用 `bnul auth install-browser` 安装；Linux 可加 `--with-deps`。BNUL_BROWSER 可选 chrome/msedge/chromium。无桌面自动登录遇到验证码仍需可见环境处理。

## 按自习计划推荐

用户说“今天 19 点到 21 点自习，帮我找座位”或“现在到 22 点想去图书馆”，属于推荐请求，先运行：

- `bnul recommend --date today --start 19:00 --end 21:00`
- `bnul recommend --date today --start now --end 22:00`

从自然语言提取日期、起止时间；“现在”保留 now，不能替换为固定分钟。只有缺少必要时段或表达歧义时才问；不要先要求用户给出座位 ID。未指定位置时使用默认主馆并在答复中说明。用户指定位置时，按下表使用固定别名填写 `--building`、`--floor`、`--room`；别名无法识别时，按下文查询 ID。不要因默认房间偏好擅自覆盖明确位置要求。

recommend 只读取数据：默认返回 5 个通过实时 starts/ends 校验的候选，最多检查 50 个座位；未指定偏好时按服务器房间顺序跨房间轮流检查；可用 --limit/--max-checks 调整。不根据当前 FREE/IN_USE 或 afterFree 单独判断匹配。指定 --room-order 时，按房间优先级逐个区域检查，达到结果/检查上限即停；只有该区域候选查完才进入下一项。顺序中未列出的区域不参与搜索，不静默回退。默认排序是查找顺序，不是最佳舒适度评分。

按用户希望的数量用简短中文给出返回的候选：位置、座位编号、覆盖时段，以及“该完整时段已通过可选时间校验”。可根据用户偏好在这些候选中推荐一个，但只使用已知事实，不能编造靠窗、插座、安静等座位属性。无额外偏好时说明候选都匹配时段，没有证据证明某个更舒适。保留返回的 roomId/seatId/date/beginMinute/endMinute 供后续执行。

recommendations 为空且 searchExhausted=false 时，只能说“已检查的候选中未找到”，可在合理范围增加 max-checks；不能说全馆无座。searchExhausted=true 也仅代表返回的 scope 和候选列表已检查完。接口错误不能解释成无座。不可静默缩短、拆分或取整用户时段；需要调整时给出建议让用户选择。推荐不保证用户账号当前具备预约资格，也不锁定座位。

用户只要求推荐时不执行 book --execute。用户选定并要求预约后重新用 book 校验/提交，沿用 now 标记，不照搬查询时的当前分钟。如果用户本来明确要求“找一个符合条件的并预约”，则在其授权条件内选择后执行，无需重复索取相同授权。

## 楼馆、楼层与房间别名

每个已登记位置只提供一个固定别名，CLI 将别名解析为官方 ID。楼馆使用 `bN`；楼层和房间在所选楼馆内分别使用 `fN`、`rN`。下表只列别名和位置说明，不列 ID，也不把说明文字作为另一套传参方式。未指定楼层时搜索全部楼层。

优先直接使用别名，无需预先查询目录。别名无法识别或位置未列出时，楼馆、楼层用 `bnul buildings` 获取 ID；房间用 `bnul room-list --building 别名或ID` 获取 ID，再以返回的 ID 传参。按名称和所属楼馆核对结果，不自行编造别名。登录失败、网络错误或没有可约座位不表示别名失效。

以下位置于 2026-10-18 核对；表格不代表实时有座。用户要求刷新或展示最新清单时再查询目录。

### 楼馆别名

| 别名 | 楼馆 |
| --- | --- |
| `b1` | 主馆 |
| `b2` | 主馆南区 |
| `b3` | 教育学分馆 |
| `b4` | 沙河 |

### 楼层别名

`--floor` 用于 `rooms` / `recommend`。别名表示所选楼馆的实际楼层，不是清单行号。

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

可选范围：主馆 `f1`–`f8`；主馆南区 `f3`；教育学分馆 `f1`；沙河 `f1`–`f2`。例如主馆三层：`bnul recommend --building b1 --floor f3 --date tomorrow --start 19:00 --end 21:00`。

### 房间别名

`--room` 用于 `seats` / `book` / `recommend`，配合所属楼馆的 `--building` 使用。

主馆（`--building b1`，可省略）：

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

主馆南区（`--building b2`）：

| 别名 | 房间 |
| --- | --- |
| `r1` | 工具报刊外文阅览区 |

教育学分馆（`--building b3`）：

| 别名 | 房间 |
| --- | --- |
| `r1` | 教育学分馆 108 |
| `r2` | 教育学分馆 149 |

沙河（`--building b4`）：

| 别名 | 房间 |
| --- | --- |
| `r1` | 昌平校园 G 区分馆一层 |
| `r2` | 昌平校园 G 区分馆二层 |

用户给了区域偏好时，将别名填入有序搜索，例如 `--room-order 'r4,r3,r2'`。顺序中的房间必须属于所选楼馆，并符合楼层范围；`--room` 和 `--room-order` 互斥。

已有用户偏好时优先使用，不必重新询问同样偏好；没有偏好时使用默认跨区域模式并说明范围。结果因 max-checks 截断时可能尚未检查后续区域，要根据 searchExhausted/stopReason 如实说明；需要继续可以针对余下区域查询，不把首选区域未查完误报为首选无座。不要擅自缩短时段来迎合区域偏好。

## 查询和选座

- `bnul room-list` 返回房间别名、名称与 ID；`bnul rooms` 不带时段时显示同一清单。
- `bnul buildings` 返回楼馆、楼层和可预约日期。
- `bnul rooms --date tomorrow --start 19:00 --end 21:00` 查询主馆房间；可指定 `--building b1 --floor f3 --power --windows`。
- `bnul seats --room r4 --date tomorrow --start 19:00 --end 21:00` 返回座位；可用 `--label 008` 精确匹配编号。
- `bnul times --seat ID --date tomorrow --start 19:00` 返回时间线、可选开始时间和该开始时间对应的结束时间。

默认楼馆是主馆（`b1`）。主馆的 `seats` / `book` 未指定房间时默认使用 3F 自习区（`r4`）；选择其他楼馆时必须同时指定对应的 `--room`，否则返回 `ROOM_REQUIRED`，不使用主馆默认房间。`recommend` 未指定房间时在所选楼馆跨房间搜索，未指定楼馆则使用主馆。日期按 Asia/Shanghai；支持 today、tomorrow、YYYY-MM-DD。座位 ID 与带前导零的编号保持字符串。

`status` 是当前状态；`afterFree` 不能单独证明完整目标时段可约。即使 IN_USE/AWAY 也可能在未来有可约时段，以实时 starts/ends 校验为准。预约记录中的 14:04 不代表允许任意分钟提交。固定开始/结束时间通常为整点或半点，必须使用实时 starts/ends 中的选项，不自行凑数或静默舍入。用户要求“现在开始”时用 `--date today --start now`（也支持 `--start=-1` 或“现在”），而不是把本机当前分钟填成固定时间。可选列表的 now 对应提交 -1；查询结束时间用当前分钟数，CLI 已分别处理。若服务器没有返回 now，就不能立即预约，不擅自改成未来时段。不要用旧附件判断当前空闲情况。

## 预约、取消与结束

需要预览时运行 `bnul book --room r4 --seat ID --date DATE --start HH:MM --end HH:MM`；用户已明确授权且座位、日期、时段确定时，可直接加 `--execute` 提交，无需先单独预览。执行本身会重新校验座位及实时可选开始/结束时间。`book` 不需要 `--floor`：CLI 先确认目标座位属于指定房间，再按座位校验时段并提交；最终预约接口使用座位和时段，楼层只用于查找房间、推荐座位时筛选范围。仅询问空位、提供接口样例或开发工具不构成实际预约授权。缺少必要日期、时间或座位选择时先查询可选项。

预约成功后呈现位置、座位、日期、时段、状态以及服务端 message 中的签到要求。RESERVE 是待签到，CHECK_IN 是使用中，AWAY 是暂离，STOP 是已结束。不要根据 showCheckBtn、isSign 或 oneself 单独推断已签到。需要验证码时交由用户在官网完成；不尝试绕过。可通过环境变量 BNUL_CAP_TOKEN 传入正常验证所得 token。

`bnul current` 查看当前预约；`recent` 查看最近详情；`history --page 1 --page-size 10` 分页查看预约历史，`breach --page 1 --page-size 10` 分页查看违约记录（返回 list/count，不自行判断违约是否过期）；`life MAKE_ID` 查看变更记录。遇到“已有有效预约”时保留错误中的 ctId；只有需要了解或处理原预约且现有信息不足时才查 `current`，不要自动结束原预约。

取消/结束按状态选择：RESERVE 未签到用 `cancel`，CHECK_IN/AWAY 已签到用 `stop`。

- 需要预览或缺少目标预约 ID 时，直接运行对应的 `bnul cancel` / `bnul stop` 预览；成功结果已含当前预约 ID 和状态（JSON 的 `data.current.id` / `data.current.status`），无需先查 `current`。只有无法依据用户请求及已有信息确定应预览 `cancel` 还是 `stop` 时，才查一次 `current`。
- 本次流程已有目标预约 ID、状态且用户已授权时，可直接 `bnul cancel --execute --expect-id MAKE_ID` 或 `bnul stop --execute --expect-id MAKE_ID`。CLI 执行前会重新读取并校验当前预约，无需再加预览或 `current`。
- 用户已授权释放“当前预约”、但本次流程没有 ID 时，可省略 `--expect-id`（如 `bnul stop -e`；`-e`/`--exe` 等同 `--execute`），CLI 使用同一命令内读取的当前预约 ID。

CLI 按实时状态决定实际操作：命令与状态不符时自动改用 cancel 或 stop，结果注明 `switched`/`requestedAction`/`action`，向用户说明实际执行的是哪一项，不要因此重跑另一个命令。指定 `--expect-id` 时须匹配当前预约 ID。状态/ID 不匹配错误不一定带回完整预约，不能凭空提取 ID，也不要自动改成新 ID 重试。沿用用户已有取消/结束授权，不重复索取；仅提供抓包或要求开发功能不构成操作真实预约的授权。

取消成功的数字 data 原样保留；须知说明每日最多取消 3 次。取消时间限制以服务端结果为准。`current` 返回空字符串表示没有当前预约。如果用户要求“结束当前并重约”，按实时状态选择 cancel/stop，成功后重新查询座位和时段再 book；不保证无冷却或一定能重约。写请求可能已提交，但因超时、断连等无法判定结果时，选择 `current` 或 `recent` 中最相关的一项核实；确有缺失证据时再用 `history` 或 `life MAKE_ID`，不要按清单全部查询。仅 `current` 为空不能证明某次写操作成功。核实仍失败或证据不足时如实说明结果未知并停止，不循环查询、不重复提交，也不在取消/结束结果不明时继续重约。

服务端 stop 无预约 ID 参数，CLI 的 ID 校验只能缩小竞态窗口；操作期间不要并行更换预约。`bnul stop` 不带 `--execute` 只预览；`bnul stop --execute` 会主动结束使用，不能当成取消预览。

## 预约临期监控（0.5.2）

用户授权监控和自动处理后可用 `bnul watch --execute --interval 120 --notify slack`。每天北京时间 08:00–23:00 运行；夜间不查询、不触发登录恢复、不生成或投递告警。白天无预约 30 分钟、CHECK_IN 20 分钟、AWAY 剩余超过 10 分钟时 7 分钟、不超过 10 分钟时 2 分钟；RESERVE 和异常每 2 分钟。默认 `bnul watch` 只观察，`--once` 单次，`--status` 只读本地健康、下次检查时间和动作记录；夜间 `--once` 返回休眠。主馆 RESERVE/AWAY 严格在距离截止不足 300 秒时释放并尝试原位重约；CHECK_IN 不处理，结束时间不延长。暂离规则以实时官网须知为准；awayTime 为当天零点起的秒数，awayTimeM 为分钟数，awayRange 为 HH:MM 显示值，存在的字段需相互一致。自然结束早于暂离截止时只观察。无法确认就分类告警而不操作，lastObservation 保留最小诊断字段；期限解析告警不能解释为登录失败。

保持普通业务命令同一份正式安装，不使用另一份过时代码。Linux 长期运行用随安装包发布的 deploy/linux/WATCH.md 与 systemd 模板；启用服务是实际自动操作，沿用用户已有授权。可用 BNUL_CREDENTIAL_ENV 指向服务器现有私有 dotenv，不因 SSH 进程没加载变量就断言服务器没有凭据；只检查配置与必要键是否可用，不输出秘密。

登录恢复失败会保留退避状态并继续检查；异常、恢复和动作结果通知到明确配置的 Slack 会话，失败队列跨重启重试。独立 timer 检查监控心跳，不能用“进程 active”代替成功查询和实际通知回执。真实取消重约须有授权并记录前后预约 ID，不能通过结束 CHECK_IN 来验收。达到当日重约上限、取消配额为 0/未知时只释放并通知；不重试结果未知的写操作。

## CLI 缺失时安装

项目主页及最新安装说明：[KawaroX/bnul](https://github.com/KawaroX/bnul)。若 bnul 不存在，按该仓库 README 安装；链接失效时可搜索 GitHub 的 KawaroX/bnul，确认仓库身份后再使用，不安装未经确认的 PyPI 同名包。

推荐 `uv tool install git+https://github.com/KawaroX/bnul.git`，然后 `uv tool update-shell`。也可用 `pipx install git+https://github.com/KawaroX/bnul.git` 和 `pipx ensurepath`。重开终端/任务使 PATH 生效，验证 `bnul --help`，再运行 `bnul auth install-browser`。安装 skill 用 `bnul skill install`。这些是全局可调用的隔离工具安装，不要求用户提供虚拟环境绝对路径。

需要更详细的安装、PATH 和平台说明时，读取 [安装说明](references/installation.md) 或仓库 README。账号密码只在用户终端通过 `bnul auth setup` 配置，不在聊天中收集。
