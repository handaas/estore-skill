# 报告输出 — 网店大数据报告

本文件规定 `estore-report` skill 产出的报告结构、质量底线与渲染工作流。所有产物遵循 `AGENTS.md` 的统一 JSON 骨架与本 skill 的领域裁剪。

## 默认展示模式

- HTML：可分享 / 可交付的可视化报告；独立本地文件，内嵌 CSS，无调试 / 内部段落。
- Markdown：知识库 / wiki / PRD / 后续手工编辑。
- JSON：系统集成或二次处理。

`compose_report.py` 通过 `--report-output <path>` 同时产出 HTML + Markdown；`--output <path>` 产出 JSON。`render_report.py` 可基于已有 JSON 重渲染。

## 报告结构（7 章）

1. **报告摘要**：分析对象、数据覆盖范围、核心发现、关键指标卡。
2. **查询对象与口径**：企业全称、匹配方式、数据范围、产品、局限。
3. **数据总览**：网店画像实际返回时展示网店总数、覆盖平台、国内/海外网店数和产品数；只有店铺明细返回时仅展示当前响应关联网店记录数，不外推全部店铺或平台覆盖。
4. **核心分析**（网店专属子章节，由 `core_analysis.sections` 驱动渲染）：
   - 网店概况（KV：网店数 / 平台覆盖 / 国内海外分布 / 主营类目 / 累计销售）。
   - 电商产品画像（表或 KV：产品数 / 热销产品 / 价格带 / 销量 / 主营类目）。
   - 电商关联网店信息（表：店铺名称 / 所属企业 / 关联性质 / 开店时间 / 状态等）。“关联”不等于查询主体自营；所属企业未知时不得统称企业店铺。
5. **代表性记录**：关键店铺 / 产品记录 Top N。
6. **特征与洞察**：结构化解读（网店规模 / 平台覆盖 / 产品画像 / 店铺布局），每条含 `feature` / `evidence` / `interpretation`。
7. **数据口径与来源**：MCP server、数据产品、生成时间、是否 dry-run。

## 质量底线

- 报告脱离 Skill 上下文也可独立阅读；正文只见网店事实与结构化数据。
- 绝不出现工具名、入参（如 `matchKeyword=...`）、product_id、内部字段名、空表、调试信息。
- HTML 采用研究报告视觉风格：A4 风、灰色顶部条纹、蓝色报告横幅、左侧目录 / 范围侧栏、深蓝章节标题、深蓝表头、浅蓝斑马行、打印友好分页。
- 数据为空时明确说明数据范围 / 口径，不渲染空表、不臆造事实。
- 绝不打印 `secret_id` / `secret_key` / 签名 / token / 原始签名请求。
- 自动补全企业全称时，在报告口径中说明“由关键词模糊查询补全”。

### 数据格式约束（铁律）

以下约束适用于 compose_report.py 组装数据与 render_report.py 渲染输出的全过程：

1. **嵌套 JSON 字符串必须解析**：MCP 返回的某些字段（如 `regCapital`、`addressValue`、`subscriptionDetail`）可能是 JSON 字符串（例：`{"coinType":"人民币","value":430000000.0}`）。compose 层必须调用 `_unwrap_json_str()` / `_parse_reg_capital()` / `_flatten_addr()` 解析为可读文本（如"4.30 亿 人民币"、"浙江省杭州市滨江区..."）。绝不在报告正文、表格单元格或指标值中输出原始 JSON 字符串。

2. **section 标题必须用中文**：`core_analysis.sections` 数组中每个 section 的 `title` 字段必须使用中文（如"企业基本信息"、"对外投资"、"股东信息"）。`key` 字段用英文 snake_case 供程序索引，但 `title` 绝不可显示英文 key。即使缺少 sections 数组，渲染器回退逻辑也内置了 `_TITLE_MAP` 映射。

3. **指标值可读化**：所有 `metrics` 的 `value` 字段必须格式化为人类可读形式：
   - 金额：`10995210218.0` → `109.95 亿 人民币`（≥1 亿用亿，≥1 万用万）
   - 地址：嵌套 dict → 省+市+区拼接 或取 `value` 字段
   - 比率：`0.8858` → `88.58%`
   - 日期：保持 `yyyy-MM-dd` 格式
   - "-" 表示字段缺失（MCP 未返回）；`0` 表示真实为零

4. **企业画像指标提取**：有 fuzzy_search 的 skill 必须从返回的 record 中提取 `regCapitalValue` / `foundTime` / `operStatus` / `enterpriseType` / `legalRepresentative`，通过 `_enrich_metrics_with_profile()` 追加为指标卡。

5. **分布派生指标**：`_derive_core_metrics()` 从 core_analysis 各 section 计算分布指标（CR3 集中度、覆盖城市/平台/类目数、价格区间、正面占比等），确保指标总数 M ≥ 6。

## 工作流

```bash
# 1. 干跑（不调真实 API，用样例数据组装报告骨架）
python scripts/compose_report.py \
  --enterprise "示例科技有限公司" \
  --dry-run \
  --output output/estore.json \
  --report-output output/estore.html

# 2. 真实查询 + 渲染（需 MCP 连接就绪）
python scripts/compose_report.py \
  --enterprise "示例科技有限公司" \
  --output output/estore.json \
  --report-output output/estore.html

# 3. 重渲染已有 JSON
python scripts/render_report.py --input output/estore.json --output output/estore.html
python scripts/render_report.py --input output/estore.json --output output/estore.md
```

返回：JSON 路径、HTML 路径、Markdown 路径，以及企业全称映射与数据口径摘要。

## 内容审校（离线）

对已有 `report.json` 复核而不调用 MCP：`python scripts/estore_content_review.py --input <report.json> --out-dir <dir>`；纯函数 `estore_content_review.apply_content_review(report)`。审校顺序：

1. 平台/渠道：`直播店` 等为渠道类型，不计入平台数；平台清单只表示上游出现过，不算店铺份额或 CR2。平台覆盖只认网店概况平台清单：仅有海外平台清单时保留其上游计数（不置 0），不把产品画像 `ecSources` 或链接域名推断提升为平台覆盖。
2. 链接核验：平台与店铺链接域名交叉核对，`taobao.com` 标成天猫时保留原值并标“待核实”。
3. 口径隔离：网店总数、产品画像店铺数、关联网店样本、网店概况商品数、产品画像在售商品数分别标注，不互相相除。`domesticEshopProductCount` 标为网店概况商品数，仅与国内网店数同产品口径计算店均；`product.ecShopItemCount` 标为产品画像在售商品数，不与网店概况店铺数相除；来源无法核对时保留原值、不猜来源、不相除。未返回网店总数时，国内网店数不得在正文或洞察中改称网店总数。
4. 数值：好评率按原精度转百分比，评分标“满分制未说明”，销售额标“原值、单位未声明”，`0` 不等于缺失；在营/停业只统计当前样本。
5. 措辞：删除“评分高=复购高”“CR2 偏高”等无数据支撑结论；类目中的价格片段（如 `150200元`）剔除展示并保留口径说明。

交付前按最终 `sections` 与实际 body 刷新 `data_source.quality_report`（`0` 计为已填充；`coverage_pct` 仅为章节填充率）；保留原 `generated_at`。好评率显式百分比原样输出；平台域名用 `urlsplit().hostname` 做精确/后缀匹配，不接受 credentials、query 或外来域名中的片段。

CLI 会拒绝 `--out-dir` 的 `report.json` 解析为 `--input` 的调用；输出目标应位于本 skill 的 `output/content-quality-review/`，不得覆盖 `examples/` 或 `test-records/`。
