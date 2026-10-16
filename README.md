# 酒店优惠动态核验

让 Agent 每次运行时重新读取最新酒店优惠、核对预订期限和使用条件，找出仍可参与的酒店预订或房券项目，并与上次结果比较变化。

这是供 Agent 执行的 Skill。联网发现、网页读取和事实核验由 Agent 完成；Python 脚本负责本地证据检查、保守分类和状态记录，不是独立酒店爬虫或订房系统。

## 能做什么

- 从小菜鸡腾讯文档及其当前活动入口开始，每次重新枚举工作表，发现新增或修改的公告。
- 核对预订、入住及核销日期，避免把入住截止日当作购买截止日。
- 区分实际付款、返现、积分估值、酒店消费额度和抽奖。
- 输出“已核验可预订”“规则期内候选”“待核实”及已结束等状态。
- 保留本轮证据，比较价格、规则和条件；本轮没能读取的旧项目记为“未复核”，不误判为下架。

没有足够证据时可以返回零条已核验项目。链接能打开、表名写着“每日更新”或宣传价很低，都不代表当前可订。

## 安装与使用

需要支持本地 Skill 的 Agent、Python 3.9 或更新版本，以及已安装并可用的 Ego 浏览器和 `ego-browser` 技能。Python 脚本只用标准库，其中 `fcntl` 要求 macOS 或 Linux 环境。

在目标目录不存在时，可安装到 Codex 默认技能目录：

```bash
git clone https://github.com/huntingrin/hotel-offer-tracker.git ~/.codex/skills/hotel-offer-tracker
```

如果设置了 `CODEX_HOME`，将目标目录调整为该目录下的 `skills/hotel-offer-tracker`。已有安装时先检查本地改动，不直接覆盖。其他兼容 Agent 可使用自己的技能目录；入口是 [SKILL.md](SKILL.md)。

向 Agent 发出请求：

```text
$hotel-offer-tracker 更新最新酒店优惠，找出现在还能预订或购买的项目。
```

或提供更具体的行程：

```text
$hotel-offer-tracker 查杭州下周五入住、周日退房，2位成人，万豪金卡，每晚预算600元以内的优惠。
```

未提供日期和会员等级时先查活动候选；具体行程、房型、资格、规则和销售页面都匹配后，才能列为“已核验可预订”。查询结果带检查时间，后续价格和库存可能变化。

## 来源与浏览器

默认入口在 [references/sources.json](references/sources.json)，其中旧工作表 ID 仅供定位，不代表活动仍有效。Agent 会按本次页面发现新入口；必要时用相关官方公告、公开搜索或已连接的小红书工具补充。小红书不是必需依赖。

默认来源包含第三方维护的腾讯文档，权限和内容可能变化；本仓库不代表该作者、酒店集团或预订平台，也不包含其完整资料副本。没有微信数据源时不会宣称读取了微信群最新消息。

交互浏览在 Ego 独立 TaskSpace 后台完成，不抢焦点。登录、验证码或用户接管时交回用户操作；不会绕过权限或自动改用其他可见浏览器。具体采集方法见 [references/collection.md](references/collection.md)。

## 本地记录

在项目已有 `酒店优惠研究` 目录时，默认写入其 `追踪记录` 子目录；否则写入当前项目的 `酒店优惠追踪`。也可以指定其他目录。

```text
追踪记录/
├── latest.json
└── runs/<run-id>/
    ├── context.json
    ├── observations.json
    ├── evidence/
    ├── result.json
    └── report.md
```

Agent 使用下列本地命令创建一轮记录，并在实际联网采集后提交观察结果：

```bash
python3 scripts/track.py start --state-dir /absolute/path/to/hotel-state
python3 scripts/track.py finish --run-dir /absolute/path/to/hotel-state/runs/RUN_ID --input /absolute/path/to/hotel-state/runs/RUN_ID/observations.json
```

数据字段和分类条件见 [references/record-format.md](references/record-format.md)。脚本拒绝本轮开始前的采集时间、未来时间、非当日证据以及指向本轮证据目录之外的文件，但不能证明人工填写的事实真实；Agent 仍须核对原文。

## 验证与范围

运行离线行为测试：

```bash
python3 scripts/test_track.py
```

测试覆盖截止日期、跨年、未知年份、销售页证据、搜索摘要降级、旧缓存拒绝、变化比较、部分采集及并发状态保护。

该 Skill 只读查询，不下单、不支付、不提交抽奖信息、不发私信。它不会自行创建定时任务或推送；每次调用刷新，和后台持续监控是两回事。
