# 0.5.2 预约临期监控

监控是独立常驻进程；普通查询命令和安装本身不会启用它。Linux/macOS 支持 `watch`，服务器推荐 systemd。一个账号使用一个状态文件，只运行一份监控。手机应用以后可以控制这个服务；本版不包含手机后台或多租户托管。

## 行为

- 每天北京时间（Asia/Shanghai）08:00（含）至 23:00（不含）运行。夜间不查询、不启动登录恢复、不生成告警，也不投递队列中已有的通知；08:00 恢复查询。`--once` 与 `--notify-test` 同样遵守休眠时段。23:00 后不开始新的查询轮次、API 请求或登录恢复；此前已启动的网络操作可能在边界后结束。
- 根据上次实际查询结果安排下一次查询：无预约 30 分钟，CHECK_IN 使用中 20 分钟；AWAY 剩余超过 10 分钟时 7 分钟，不超过 10 分钟时 2 分钟；RESERVE 未签到、状态未知或异常每 2 分钟。等待期间状态变化会在下一次查询时发现。`--interval` 仅调整上述 2 分钟间隔，其余间隔固定。临近 23:00 时截短等待以进入休眠。
- 严格在 `0 < 剩余秒数 < 300` 时处理：RESERVE 取消，AWAY 结束，然后尝试原座位、现在开始、原结束时间的预约。
- CHECK_IN 不处理。不改变座位、延长结束时间或自动签到。暂离按官网须知中的 30 分钟与用餐豁免规则计算；规则或字段无法确认就通知并暂停写操作。截止时间已过只通知，不冒险操作。
- 暂离字段已用真实历史和变更记录交叉核实：`awayTime=81578` 表示当天 22:39:38，`awayTimeM=1359` 表示分钟数，`awayRange="22:39"` 是显示值。支持当天秒数及原有明确时间格式；附带字段冲突时保留诊断并停止写操作。预约自然结束不晚于暂离截止时继续观察，不提前结束或重约。
- 写操作前重新核对预约 ID、状态、座位、日期、结束时间和截止时间；先确认登录和验证码策略，再释放座位。学校 stop 接口不接受 ID，仍不能完全消除与人工同时操作的竞态。
- 默认每天最多尝试重约 3 次。取消返回的剩余次数为 0、格式未知或达到重约上限时，只释放并通知，不留下一个无法再自动取消的新预约。按日计数，失败的重约也占一次尝试。学校不保证原位重新可用。
- 写请求前同步落盘；结果不确定或进程中断后只读核对，不重放取消/结束/预约。`actions` 保存结果，需要处理的异常发通知。

## 配置与验证

安装 [v0.6.0 Release](https://github.com/KawaroX/bnul/releases/tag/v0.6.0) 的 wheel 或固定 tag。不要把新监控装到另一份旧代码目录中。自动登录不需要浏览器，旧版本安装的 Chromium 可以不再维护。

```sh
uv tool install --force git+https://github.com/KawaroX/bnul.git@v0.6.0
bnul --version
```

可复用已有私有 dotenv：将 `BNUL_CREDENTIAL_ENV` 指向绝对路径，只读取 `BNUL_USERNAME`、`BNUL_PASSWORD` 和通知所需键，不复制文件。环境中的同名键优先；文件内容不做 `${...}` 展开。`BNUL_WATCH_ENV` 可为监控单独指定文件。文件应只允许运行用户读取。已有浏览器可通过 settings.json 的 `browser_executable` 指定；transport 设置沿用正式 CLI。

Slack 使用 `SLACK_BOT_TOKEN` 和 `SLACK_HOME_CHANNEL`，可选 `SLACK_HOME_CHANNEL_THREAD_ID`。`BNUL_SLACK_CHANNEL` / `BNUL_SLACK_THREAD` 可覆盖目标。Bot 需有 `chat:write` 且能访问目标会话。通知使用 [Slack chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/)，检查 `ok` 和消息时间戳后才记为送达。

```sh
export BNUL_CREDENTIAL_ENV=/绝对路径/已有私有.env
bnul --json watch --once
bnul --json watch --notify slack --notify-test
bnul watch --execute --interval 120 --notify slack
```

告警区分截止时间/规则无法确认、登录恢复失败、查询失败、错过处理窗口与心跳异常；只在登录相关故障中说明登录重试。期限解析失败不等于鉴权失败。首次故障立即通知，同类连续故障最多每小时提醒一次；恢复及自动操作结果单独通知。通知失败保留磁盘队列并以 120 秒至 1 小时退避重试，尊重 Slack 限流；服务重启后继续投递。网络超时而 Slack 实际已收件时可能重复一条，通知按至少一次交付设计。通知不包含学校密码或 token。

普通会话失效时用现有凭据经 HTTP 自动登录（直连或 WebVPN 均可）。同一账号只有一个有效会话，其他设备登录会顶掉监控的会话，监控会自动重新登录。白天恢复失败后仍每 120 秒读状态，登录尝试从 30 分钟退避到最多 6 小时，状态跨重启保留；外部修复的会话会在下一轮读检查中被识别。学校要求验证码或 WebVPN 手机确认时，通知后需正常完成认证。修正凭据后可先 `bnul current` 完成恢复，监控下一轮会自动恢复工作。

## systemd

按实际用户名、主目录、正式 CLI 路径、现有环境文件修改三个模板。`bnul-watch.service` 带 `--execute`，启用会执行已授权的临期处理。

```sh
sudo install -m 644 deploy/linux/bnul-watch.service /etc/systemd/system/
sudo install -m 644 deploy/linux/bnul-watch-health.service /etc/systemd/system/
sudo install -m 644 deploy/linux/bnul-watch-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bnul-watch.service bnul-watch-health.timer
```

服务总是重启，单轮超过 300 秒未报告心跳时由 systemd 重启。等待期间每 60 秒仅更新本地心跳并报告给 systemd，不查询学校。独立 timer 每 120 秒读取监控状态文件，白天心跳超过 360 秒时告警；夜间直接返回休眠，不检查故障或投递通知，不需要获取监控持有的锁；它不修改预约。整个 VPS 或外网不可用时，本机无法即时向 Slack 投递，恢复后重试。

```sh
bnul --json watch --status
systemctl is-enabled bnul-watch.service bnul-watch-health.timer
systemctl status bnul-watch.service bnul-watch-health.timer
journalctl -u bnul-watch.service --since '15 minutes ago'
```

验收需核对真实查询按当前状态间隔运行，长间隔下本地心跳持续更新；用独立状态文件和可控时钟覆盖 23:00 休眠、夜间零查询/登录/通知、08:00 恢复以及各状态间隔。登录恢复和 Slack 回执验证应沿用隔离环境。测试注入失败/卡死应使用独立状态文件与明确“测试”通知，不能改生产预约状态或伪造成功。真实取消重约会占取消额度，应使用用户授权的测试预约或自然出现的临期预约；不能拿已签到的座位强行验收。

状态默认在 `~/.config/bnul/watch-state.json`（随 `BNUL_CONFIG` 的父目录）；里面包含最后实际查询 `lastCheck`、独立进程心跳 `heartbeatAt`、休眠状态与下一次检查 `schedule`、健康状态、最近读取的最小预约字段 `lastObservation`（含暂离原始值、无账号或凭据）、登录退避、动作日志与通知回执，权限 0600。旧版 version=1 日志可继续读取。不要通过删除动作日志来强制重试不确定的写入。独立心跳的状态使用 `.health` 后缀。

休眠只表示当前不查询；不会把上次未解决的故障标为健康。`sleeping`、`fresh`、`healthy` 分别表示计划休眠、进程心跳新鲜和最近业务检查健康。夜间升级后保留旧故障，次日真实查询成功才产生恢复记录。

监控属于轮询：状态变化最迟在下一次成功查询时发现。空闲 30 分钟轮询不能保证保护通过其他入口新建、只有 30 分钟签到窗口的每一笔预约；需要更强保障时应缩短空闲间隔或让预约创建事件主动唤醒监控。网络、登录、验证码、取消额度和原位可用性也会影响执行结果。
