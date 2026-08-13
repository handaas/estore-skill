# MCP 工具参考 — estore-mcp-server

本 skill 连接的 MCP server：`handaas-mcp-server/estore-mcp-server`（“网店大数据”）。

> **重要**：网店维度类工具入参为 `matchKeyword`（**企业全称** / 注册号 / 统一社会信用代码 / 企业 id）+ `keywordType`；当用户只给企业关键词时，必须先调关键词模糊查询补全全称。

## 通用约定

- `keywordType` 枚举：`name`（企业名称）/ `nameId`（企业 id）/ `regNumber`（注册号）/ `socialCreditCode`（统一社会信用代码）。
- 分页：`pageIndex` 从 1 开始；`pageSize` 单页最多 50。

---

## 工具清单

### 1. `estore_bigdata_global_online_store_profile` — 国内外网店概况

用途：按企业主体返回国内外网店整体概况（网店数、平台覆盖、类目、累计销售等）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业名称 / 注册号 / 统一社会信用代码 / 企业 id |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |

返回：`storeCount`（网店总数）、`platformList`（覆盖平台）、`domesticStoreCount`（国内网店数）、`overseasStoreCount`（海外网店数）、`mainCategory`（主营类目）、`totalSalesAmount`（累计销售额）、`totalSalesVolume`（累计销量）、`updateTime`（数据更新时间）等。

product_id：`66d5b7df537c3f61d646c327`。

---

### 2. `estore_bigdata_ecommerce_product_profile` — 电商产品画像

用途：按企业主体返回电商产品销售画像（产品数、热销产品、价格带、销量等）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体 |
| `keywordType` | string | 否 | 主体类型 |

返回：`productCount`（产品总数）、`topProduct`（热销产品）、`avgPrice`（平均价格）、`mainCategory`（主营类目）、`priceRange`（价格区间）、`totalMonthlySales`（总月销量）等；或返回产品明细 list（`productName`、`category`、`price`、`monthlySales`、`platform`、`shopName`）。

product_id：`66c33eff3c0917a9a02feba8`。

---

### 3. `estore_bigdata_fuzzy_search` — 关键词模糊查询企业

用途：根据企业名称 / 人名 / 品牌 / 产品 / 岗位等关键词模糊查询企业列表，用于补全企业全称。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 匹配关键词 |
| `pageIndex` | int | 否 | 分页开始位置（默认 1） |
| `pageSize` | int | 否 | 单页最多 50 |

返回：`total` + 企业列表（`name`、`nameId`、`regCapitalValue`、`foundTime`、`operStatus`、`address`、`legalRepresentative`、`enterpriseType`、`catchReason` 命中原因等）。

product_id：`675cea1f0e009a9ea37edaa1`。

---

### 4. `estore_bigdata_ecommerce_store_info` — 电商店铺信息

用途：按企业主体返回电商店铺明细信息。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体 |
| `keywordType` | string | 否 | 主体类型 |

返回（list + `total`）：`shopName`（店铺名称）、`platform`（所属平台）、`shopType`（店铺类型）、`mainCategory`（主营类目）、`openDate`（开店时间）、`shopUrl`（店铺链接）等；或返回店铺汇总 KV（`dsrScore`、`followerCount`、`totalSalesAmount` 等）。

product_id：`66a34ccedbee527b7a831c98`。

---

## 推荐调用顺序（报告编排）

1. （若仅有关键词）`estore_bigdata_fuzzy_search` → 取 `name` 作为全称。
2. `estore_bigdata_global_online_store_profile` → 网店整体概况。
3. `estore_bigdata_ecommerce_product_profile` → 电商产品画像。
4. `estore_bigdata_ecommerce_store_info` → 店铺明细信息。

> 单次报告通常调用 3 个数据工具；所有维度入参均为企业主体 `matchKeyword` + `keywordType`。
