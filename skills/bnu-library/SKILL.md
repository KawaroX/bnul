---
name: bnu-library
description: 使用 bnul CLI 查询与预约北京师范大学图书馆自习座位，选择日期和起止时间，查看当前预约、签到提示与变更记录，或结束使用。
---

使用 PATH 中的 `bnul`。首次用 `bnul --help` 确认命令可用；若不存在，按本文最后的“CLI 缺失时安装”处理。不要假定源码、虚拟环境或用户目录的位置。所有命令支持前置 `--json`，成功输出 `ok/data`，失败输出 `ok/error/code/data` 并返回非零退出码；代理不可用时加前置 `--no-proxy`。

## 登录

日常直接执行业务命令，不要每次先要求用户登录。CLI 在本地会话缺失或明确鉴权失败（20003/401）时，自动后台启动专用浏览器，先复用学校登录状态，再使用系统凭据库中的凭据填写学校 CAS 表单；成功后重试查询一次。写操作前检查会话，不重放已提交的写请求。网络错误不触发自动登录。

首次用 `bnul auth setup` 在用户本机终端隐藏输入密码并存入系统凭据库；不要让用户把密码发送到聊天或由 agent 拼接到命令里。setup 仅保存，密码是否有效要以实际认证为准。若没有配置且出现 AUTH_SETUP_REQUIRED，指导用户完成这一次配置。验证码、二次认证或密码错误需要 `bnul --no-proxy auth login` 的可见官网窗口。不要将正常 token 失效一律交回用户手动登录。

`auth login` 是统一可见登录入口，`login` 仅为同义兼容别名。`auth status` 只检查当前会话，不自动恢复；`auth forget` 删除钥匙串凭据；`auth clear` 仅清除 CLI token，仍保留钥匙串和 browser-profile，因此下次业务命令可能自动恢复。`auth import --file` 为已有 token/curl 的备用导入，`auth exchange-link` 仅为高级 URL 诊断，不是自动恢复的回退。显式设置 BNUL_TOKEN 时禁用自动恢复，避免覆盖用户指定凭据。

链接票据 JWT 样例有效期 60 秒，不是保存的 API 会话期限。API 会话期限未知，但无需预知才能按服务器失效码自动恢复。浏览器刷新不证明 URL 票据可兑换，不要将 casToken异常直接归咎于过期或用户操作。不要回显凭据或写入代码/skill。

平台凭据：macOS Keychain、Windows Credential Manager、Linux Secret Service。Linux 无桌面/无 Secret Service 时支持同时注入 BNUL_USERNAME/BNUL_PASSWORD，不写入文件，优先于系统库；不要在聊天收集密码或拼接含密码的命令。默认 Chromium，使用 `bnul auth install-browser` 安装；Linux 可加 `--with-deps`。BNUL_BROWSER 可选 chrome/msedge/chromium。无桌面自动登录遇到验证码仍需可见环境处理。

## 查询和选座

- `bnul --json buildings` 返回楼馆、楼层和可预约日期。
- `bnul --json rooms --date tomorrow --start 19:00 --end 21:00` 查询主馆房间；可指定 `--building ID --floor ID --power --windows`。
- `bnul --json seats --room ID --date tomorrow --start 19:00 --end 21:00` 返回座位；可用 `--label 008` 精确匹配编号。
- `bnul --json times --seat ID --date tomorrow --start 19:00` 返回时间线、可选开始时间和该开始时间对应的结束时间。

默认楼馆是主馆 `1887388460760797184`，默认房间是 3F 自习区（低声区、朗读区）`1888096971220160512`。用户曾使用的 008 号座位 ID 为 `1888111985066872919`；这是参考位置，不代表以后预约时默认选择它。日期按 Asia/Shanghai；支持 today、tomorrow、YYYY-MM-DD。座位 ID 与带前导零的编号保持字符串。

`status` 是当前状态；`afterFree` 不能单独证明完整目标时段可约。即使 IN_USE/AWAY 也可能在未来有可约时段，以实时 starts/ends 校验为准。预约记录中的 14:04 不代表允许任意分钟提交。固定开始/结束时间通常为整点或半点，必须使用实时 starts/ends 中的选项，不自行凑数或静默舍入。用户要求“现在开始”时用 `--date today --start now`（也支持 `--start=-1` 或“现在”），而不是把本机当前分钟填成固定时间。可选列表的 now 对应提交 -1；查询结束时间用当前分钟数，CLI 已分别处理。若服务器没有返回 now，就不能立即预约，不擅自改成未来时段。不要用旧附件判断当前空闲情况。

## 预约与结束

先用 `bnul --json book --room ID --seat ID --date DATE --start HH:MM --end HH:MM` 生成实时校验的预览。实际提交加 `--execute`。用户明确要求预约且已确定座位和时间即可执行；仅询问空位、提供接口样例或开发工具不构成实际预约授权。缺少必要日期、时间或座位选择时先查询可选项。

预约成功后呈现位置、座位、日期、时段、状态以及服务端 message 中的签到要求。RESERVE 是待签到，CHECK_IN 是使用中，AWAY 是暂离，STOP 是已结束。不要根据 showCheckBtn、isSign 或 oneself 单独推断已签到。需要验证码时交由用户在官网完成；不尝试绕过。可通过环境变量 BNUL_CAP_TOKEN 传入正常验证所得 token。

`bnul --json current` 查看当前预约；`recent` 查看最近详情；`life MAKE_ID` 查看变更记录。遇到“已有有效预约”时保留错误中的 ctId，查询 current；不要自动结束原预约。网络失败时写操作结果可能未知，先查询 current/recent，不盲目重试。

结束使用先执行 `bnul --json stop` 得到当前预约。用户授权结束后执行 `bnul --json stop --execute --expect-id MAKE_ID`。服务端 stop 无预约 ID 参数，CLI 的 ID 校验只能缩小竞态窗口；操作期间不要并行更换预约。stop 会主动结束使用，不能当成无副作用的取消预览。

## CLI 缺失时安装

项目主页及最新安装说明：[KawaroX/bnul](https://github.com/KawaroX/bnul)。若 bnul 不存在，按该仓库 README 安装；链接失效时可搜索 GitHub 的 KawaroX/bnul，确认仓库身份后再使用，不安装未经确认的 PyPI 同名包。

推荐 `uv tool install git+https://github.com/KawaroX/bnul.git`，然后 `uv tool update-shell`。也可用 `pipx install git+https://github.com/KawaroX/bnul.git` 和 `pipx ensurepath`。重开终端/任务使 PATH 生效，验证 `bnul --help`，再运行 `bnul auth install-browser`。安装 skill 用 `bnul skill install`。这些是全局可调用的隔离工具安装，不要求用户提供虚拟环境绝对路径。

需要更详细的安装、PATH 和平台说明时，读取 [安装说明](references/installation.md) 或仓库 README。账号密码只在用户终端通过 `bnul auth setup` 配置，不在聊天中收集。
