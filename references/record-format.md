# 本轮记录格式

start 创建 context.json、observations.json 模板及 evidence/。填入本轮真实采集结果后 finish。证据仅保存在本轮目录，不存 cookies、令牌或无关个人信息。

顶层字段：

- run_id：复制 context.json 值。
- coverage：complete 或 partial，指声明的酒店资料范围，不是全网。
- coverage_note：实际读了哪些工作表/区域和落地页、哪些没读。只读首页不能写全表完成。
- sources：每项含 id,url,kind,status,fetched_at,source_updated_at,evidence,note。kind 为 document、merchant 或 search；status 为 ok 或 blocked。ok 必须有本轮带时区 ISO 采集时间及非空 evidence 相对路径数组；blocked 写具体原因，不可用作有效证据。
- offers：本轮观察到的项目，空数组合法；未查到的旧项目不要复制。

单项字段示例（未知金额为 null，不是 0）：

```json
{
  "id": "来源及活动稳定标识",
  "title": "酒店或活动",
  "source_id": "本轮规则来源id",
  "url": "实际活动链接",
  "location": "城市或范围",
  "booking_start": null,
  "booking_end": null,
  "booking_open_ended": false,
  "booking_year_verified": false,
  "booking_raw": "预订期原文",
  "stay_raw": "入住期原文",
  "redemption_raw": "核销期原文",
  "availability": "unknown",
  "itinerary_match": false,
  "eligibility": "unknown",
  "terms_checked": false,
  "conflict": false,
  "merchant_source_id": null,
  "price": {"cash": null, "currency": "CNY", "basis": "每晚/每券/整单", "confirmed_cashback": null, "points": null, "point_value_per_10000": null},
  "conditions": ["房型、人数、早餐、税费、退改、最低数量、资格和叠加等"],
  "missing": ["未核实项"]
}
```

标准日期允许 YYYY-MM-DD 或带时区 ISO 时间戳。纯日期表示明确包含当日；“之前”等边界歧义保留原文，列 missing，不造精确边界。年份未核实则 booking_year_verified=false，标准日期留空。仅在规则明确持续开放时用 booking_open_ended=true，缺少截止日不等于长期开放。

availability 为 available/unavailable/unknown；eligibility 为 matched/excluded/unknown。itinerary_match 表示实际匹配指定日期房型人数或明确要买的房券规格，不是活动存在。merchant_source_id 必须指向本轮真实销售页，文档与搜索摘要不算 merchant。terms_checked 要求该项目的资格、税费、退改、早餐、数量及叠加核验完成；conflict=true 阻止确认。

confirmed_bookable 还要求非空 missing 为零及可核验现金价。价格、规则和条件参与变化比较；证据路径与采集时间变化不触发优惠变化提醒。缺失旧项目标 not_rechecked，不判失效。

脚本保留额外字段，可加房型、人数、晚数、报价有效期等。工具只做完整性和保守分类，不保证录入事实正确。report.md 为基础摘要，交付仍需说明费用与条件。
