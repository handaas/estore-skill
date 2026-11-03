# estore-skill：已验收示例

本目录只展示 **4 个完全通过的真实正向场景**（最低要求4例）。

每例均为真实、非空、非缓存调用；技术检查、独立业务检查和离线浏览器检查全部通过。不把空数据、报错处理或仅生成页面计作通过。历史验收记录保留在本地 test-records/；本目录的 HTML/Markdown 由原 JSON 重渲染，不代表重新查询或重新验收。

| 场景 | 真实使用需求 | 报告 |
|---|---|---|
| [休闲食品线上店铺画像](01-snack-brand/README.md) | 请分析三只松鼠股份有限公司的全网店铺平台、商品和运营概况。 | [HTML](01-snack-brand/report.html) / [MD](01-snack-brand/report.md) / [JSON](01-snack-brand/report.json) |
| [消费电子电商画像](04-consumer-electronics/README.md) | 请查看小米科技有限责任公司的线上店铺布局。 | [HTML](04-consumer-electronics/report.html) / [MD](04-consumer-electronics/report.md) / [JSON](04-consumer-electronics/report.json) |
| [平台零售主体画像](06-retailer-platform/README.md) | 请查看北京京东世纪贸易有限公司的线上店铺数据覆盖情况。 | [HTML](06-retailer-platform/report.html) / [MD](06-retailer-platform/report.md) / [JSON](06-retailer-platform/report.json) |
| [良品铺子关联网店生命周期核验](09-liangpin-store-lifecycle-check/README.md) | 请核验良品铺子股份有限公司实际返回的关联网店记录，列出店铺名称、关联企业、开店时间和状态，用于确认历史店铺是否仍在营；不要扩展为平台覆盖分析。 | [HTML](09-liangpin-store-lifecycle-check/report.html) / [MD](09-liangpin-store-lifecycle-check/report.md) / [JSON](09-liangpin-store-lifecycle-check/report.json) |

- [逐例验收结果](results.json) · [业务复核](review.json) · [证据摘要](evidence-index.json)
- 完整测试记录仅存于本地 test-records/live-replaced-20261027/（仅本地审计用，不随本目录发布），不属于可展示示例。
- 当前数据与结论限于原查询时点及公开样本；覆盖率不代表准确率或低风险。
