---
name: bnu-library
description: 使用 bnul CLI 查询与预约北京师范大学图书馆自习座位，按自习计划推荐覆盖完整时段的座位，选择日期和起止时间，查看当前预约、签到提示与变更记录，取消未签到预约或结束使用。
---

直接运行 PATH 中的 `bnul`。只有 shell 报告找不到 bnul 时，才按 [安装说明](references/installation.md) 处理。

## 常用任务（每项一条命令）

| 用户意图 | 命令 |
| --- | --- |
| 按时段找座位、推荐、问有没有座 | `bnul recommend --date tomorrow --start 19:00 --end 21:00` |
| 约推荐结果中的某个 | `bnul book --room 房间ID --seat 座位ID --date … --start … --end … -e`，ID 取自推荐结果，不再查询 |
| 约指定房间的指定编号 | `bnul book --room r4 --seat 008 --date … --start … --end … -e` |
| 看当前预约、签到状态 | `bnul current` |
| 取消或结束当前预约 | 说取消用 `bnul cancel -e`，说结束用 `bnul stop -e`；状态不符时 CLI 自动改用正确的操作，不先查 current |
| 结束当前并重约 | `bnul stop -e`，确认成功后再运行 `bnul book … -e`；book 失败时告知原预约已释放，无法恢复 |
| 用户要看指定房间的座位列表 | `bnul seats --room r4 --date … --start … --end …` |
| 按设施找房间 | `bnul rooms --date … --start … --end … --power --windows` |
| 某座位的可选时段（仅在用户问起时） | `bnul times --seat 座位ID --date … --start …` |
| 历史、违约、变更记录 | `bnul history`、`bnul breach`（可加 `--page N`）；当前预约的变更记录用 `bnul life`，其他预约加 ID |

## 通用规则

- 直接执行业务命令：不先跑 `--help`，不先登录，也不先用 `current` 探测。会话失效时 CLI 会自动恢复登录。
- 读默认文本输出即可。只有确需完整字段做计算时，才加 `--json`。
- 已有结果能回答就不再查询；同一流程复用刚返回的 ID、状态和时段。未获监控授权时不轮询。
- 写操作即带 `-e` 的 book/cancel/stop，需要用户明确的意图，如"约""取消""结束"。授权明确、参数齐全时直接 `-e`，不先预览，CLI 执行前会自行重新校验。只问空位、查看信息或开发调试都不构成授权。
- 写操作结果不明（超时、断连）时，只查一次 `current` 或 `recent` 核实。不重复提交；结果不明时也不继续重约。
- 不在聊天中收集、回显或拼接密码、token、Cookie。

## 时间与位置

- 日期用 today、tomorrow 或 YYYY-MM-DD（上海时区）。时间用 HH:MM，通常是整点或半点，必须在服务器的可选列表里，不能跨天。
- "现在开始"用 `--start now`，仅限今天；服务器不提供 now 时不能立即预约，不擅自改成未来时段。
- 不擅自缩短、拆分或舍入用户的时段；不可行时给出建议，让用户选择。
- 默认楼馆是主馆。`seats` 和 `book` 未给房间时默认 `r4`；其他楼馆必须给 `--room`。`recommend` 未给房间时，在所选楼馆内跨房间搜索。
- 楼馆 `--building`：`b1` 主馆、`b2` 主馆南区、`b3` 教育学分馆、`b4` 沙河。
- 楼层 `--floor fN` 即 N 层，仅用于 rooms 和 recommend。可选范围：主馆 f1–f8，南区 f3，教育学分馆 f1，沙河 f1–f2。
- 房间 `--room rN`，须属于所选楼馆：
  - 主馆：r1 1F 师樾厅、r2 2F 自习区、r3 3F 多媒体中心、r4 3F 自习区、r5 4F 借阅区、r6 5F 借阅区、r7 6F 阅览区、r8 7F 阅览区、r9 8F 借阅区
  - 主馆南区：r1 工具报刊外文阅览区
  - 教育学分馆：r1 108、r2 149
  - 沙河：r1 昌平校园 G 区分馆一层、r2 二层
- 有区域偏好时用 `bnul recommend … --room-order r4,r3,r2`，严格按顺序搜索，与 `--room` 互斥。
- 只有别名无法识别或位置未列出时，才用 `bnul buildings` 或 `bnul room-list --building bN` 查 ID。

## 推荐与预约

- 从用户的话里提取日期和起止时间；缺少或有歧义时才问，不要求用户给座位 ID。未指定位置时使用默认范围，并在答复中说明。
- recommend 默认返回 5 个通过完整时段校验的候选，最多检查 50 个，可用 `--limit` 和 `--max-checks` 调整。
- 用简短中文列出位置、座位编号和时段。可以按用户偏好推荐其中一个，但不编造靠窗、插座、安静等属性。
- 推荐后由用户选座，再预约。只有用户事先说过"找到合适的就直接约"，才在其条件内选一个，直接 `book -e`。
- 没有候选时：`searchExhausted=false` 只能说"已检查的候选中未找到"，可增大 `--max-checks` 继续；`searchExhausted=true` 也只代表该范围已查完。接口错误不能说成没有座位。
- 座位显示空闲或 afterFree，不代表整个时段可约，以 recommend 或 book 的校验为准。
- 预约成功后，告知位置、座位、日期、时段，以及服务端提示中的签到要求。状态含义：RESERVE 待签到，CHECK_IN 使用中，AWAY 暂离，STOP 已结束。
- 需要验证码时，让用户去官网完成。遇到"已有有效预约"时说明情况，不自动结束原预约。

## 取消与结束

- `stop` 和 `cancel` 都按实时状态执行：RESERVE 取消，CHECK_IN/AWAY 结束使用。命令与状态不符时，CLI 自动改用正确的操作，并在结果中注明 switched。向用户说明实际执行的是哪一项，不要再跑另一个命令。
- 取消每天最多 3 次。用户只是询问会执行什么、没有要求执行时，才不加 `-e` 预览。
- 已知预约 ID 时，可加 `--expect-id ID` 防止误操作新的预约。ID 不符报错时，不改用新 ID 重试。

## 错误处理

| 错误码 | 下一步 |
| --- | --- |
| AUTH_SETUP_REQUIRED | 让用户在自己的终端运行 `bnul auth setup`（隐藏输入密码）；服务器上也可注入环境变量，见登录说明 |
| AUTH_INTERACTION_REQUIRED | 需要验证码或二次认证：让用户运行 `bnul auth login`，在可见窗口完成 |
| AUTH_REJECTED | 学校拒绝账号密码：转述学校的提示；密码已改时让用户在自己的终端运行 `bnul auth setup`。不重试 |
| WEBVPN_LOGIN_REQUIRED | 按 [WebVPN 说明](references/webvpn.md) 发送二维码 |
| SEAT_NOT_FOUND | 编号不在该房间：核对房间，必要时用 `bnul seats --room …` 查看 |
| TIME_UNAVAILABLE | 该时间不可选：说明情况并给出替代建议 |
| NO_CURRENT_RESERVATION | 告知用户没有当前预约 |
| 网络错误 | 只读命令：环境有代理时，可加 `--no-proxy` 重试一次。写操作：按结果不明处理，不重试 |
| 其他错误 | 如实说明并停止；不反复重跑，不换 `--json` 重试，不自行改写请求或调试官网 |

登录相关的其他命令见 [登录说明](references/auth.md)。用户要求预约临期监控（watch）或服务器部署时，读 [监控说明](references/watch.md)。
