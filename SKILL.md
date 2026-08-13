---
name: estore-report
description: Use for generating a professional e-store big-data report (网店大数据报告) from the HandaaS estore MCP — covering 国内外网店概况、电商产品画像、电商店铺信息. Trigger when users ask for “网店大数据报告”, “网店分析报告”, “电商分析报告”, “查一家公司的网店”, “网店概况”, “电商产品画像”, “电商店铺信息”, or “企业网店画像”. Infer the canonical enterprise name (auto-fuzzy-completing a keyword), pick the right MCP tools, and produce HTML + Markdown + JSON reports automatically.
---

# 网店大数据报告

## 用户契约

把“网店大数据报告”作为面向用户的调用短语。`estore-report` 仅为内部包名。

当本 skill 处于激活状态：

1. 不要向用户索要 product_id、MCP 工具名、API 字段、内部参数或凭证信息；只接受企业名称、统一社会信用代码、注册号或企业 ID。
2. 接受自然目标，例如“查一下某某公司的网店”“分析这家企业的电商布局”“给我一份某某公司的网店概况报告”“看看这家公司有哪些电商店铺”。
3. 当用户只给关键词时，自动调用关键词模糊查询补全企业全称，再查网店维度。
4. 优先使用 MCP 连接（`ESTORE_MCP_URL` Remote MCP 或本地 `handaas-mcp-server/estore-mcp-server`）；不要让用户处理签名或凭证。
5. 同时产出 HTML（可分享交付）、Markdown（知识库 / wiki）、JSON（系统集成）三类产物。
6. 报告正文必须是专业研究报告风格：只见网店事实与结构化数据，绝不出现工具名、入参、product_id、内部字段或空表。
7. 绝不打印 `secret_id`、`secret_key`、签名、token 或原始签名请求。
8. 默认 dry-run；真实付费 / 凭证调用需用户明确要求且 MCP 连接配置完整。
9. 数据为空时明确说明数据范围 / 口径，不渲染空表、不臆造事实。


- MCP 返回的嵌套 JSON 字符串（如金额 `{"coinType":"人民币","value":430000000.0}`、地址 `{"city":"杭州市",...}`）必须解析为可读文本（如"4.30 亿 人民币"、"浙江省杭州市"），绝不在报告正文、表格或指标中输出原始 JSON 字符串。
- 报告所有章节标题、指标卡标签必须用中文；`core_analysis.sections` 的 `title` 字段必须中文，不可显示英文 key（如 `holders`、`investments`）。
- 指标值必须可读化：金额格式为"X 亿/万 + 币种"，地址拼接省市区，比率显示百分号。详见 `references/report-output.md` 的「数据格式约束」。

## MCP 服务入口

- 上游 MCP 项目：`handaas-mcp-server/estore-mcp-server`（位于 `HANDAAS_MCP_SERVER_ROOT` 或本仓库同级目录）。
- Remote MCP：设置环境变量 `ESTORE_MCP_URL`（streamable-http），可选 `ESTORE_MCP_TOKEN`。
- 本地 MCP：设置 `HANDAAS_MCP_SERVER_ROOT` 指向 `handaas-mcp-server` 仓库根目录；该 server 自己的 `.env` 提供 `INTEGRATOR_ID` / `SECRET_ID` / `SECRET_KEY`。
- 首次真实查询前，运行 `scripts/mcp_client.py ping` 与 `scripts/mcp_client.py list-tools` 验证连通。

## 按需加载 references

- 不清楚该 MCP 有哪些工具、参数、返回字段、何时调用：`references/mcp-tools-reference.md`。
- 报告结构、章节、质量底线、渲染工作流：`references/report-output.md`。

## 意图路由

| 用户意图 | 内部工作流 |
| --- | --- |
| 查一家公司的全维度网店报告 | 调网店概况 + 产品画像 + 店铺信息组装全量报告；`compose_report.py --enterprise ...` |
| 只要网店概况 / 平台覆盖 | 仅调 `estore_bigdata_global_online_store_profile` |
| 看电商产品 / 热销单品 / 价格带 | 调 `estore_bigdata_ecommerce_product_profile` |
| 看电商店铺明细 / 开店时间 | 调 `estore_bigdata_ecommerce_store_info` |
| 只给关键词（不是全称） | 先 `estore_bigdata_fuzzy_search` 补全全称，再查网店维度 |
| 只要 JSON / 只要 HTML / 只要 Markdown | 用 `--output`（JSON）或 `--report-output`（HTML+MD），或 `render_report.py` 重渲染 |
| 连接 / 工具不存在 / 传参错误 | `mcp_client.py ping` / `list-tools` 排查；报脱敏后的缺失项 |

## Golden path for 网店大数据报告

1. **解析企业全称**：若输入含“公司/集团/有限/院/厂/中心/事务所/合作社/合伙”等后缀视为全称；否则调 `estore_bigdata_fuzzy_search` 取首个命中。
2. **调用网店工具**（入参均为 `matchKeyword`（企业全称）+ `keywordType`）：`estore_bigdata_global_online_store_profile`（网店概况）、`estore_bigdata_ecommerce_product_profile`（产品画像）、`estore_bigdata_ecommerce_store_info`（店铺信息）。
3. **组装统一报告**：核心分析含网店概况（KV）、电商产品画像（表或 KV）、电商店铺信息（表或 KV）。
4. **渲染三件套**：`compose_report.py --enterprise ... --output ... --report-output ...` 直接产出 JSON + HTML + Markdown；或 `render_report.py --input ... --output ...` 重渲染。
5. **返回路径**：返回 JSON、HTML、Markdown 文件路径，以及企业全称映射与数据口径。

## 脚本速查

```bash
# 校验连接配置（脱敏）
python scripts/validate_config.py --allow-placeholders

# 连通性自测
python scripts/mcp_client.py ping
python scripts/mcp_client.py list-tools

# 干跑（不调真实 API，用样例数据组装报告骨架）
python scripts/compose_report.py \
  --enterprise "示例科技有限公司" \
  --dry-run \
  --output output/estore.json \
  --report-output output/estore.html

# 真实查询 + 渲染（需 MCP 连接就绪）
python scripts/compose_report.py \
  --enterprise "示例科技有限公司" \
  --output output/estore.json \
  --report-output output/estore.html

# 手动调单个工具
python scripts/mcp_client.py call-tool \
  --tool estore_bigdata_global_online_store_profile \
  --arguments-json '{"matchKeyword": "示例科技有限公司", "keywordType": "name"}'

# 重渲染已有 JSON
python scripts/render_report.py --input output/estore.json --output output/estore.html
python scripts/render_report.py --input output/estore.json --output output/estore.md
```

## 输出字段

- `subject`：企业全称、匹配关键词、主体类型、是否自动补全。
- `abstract` / `summary`：封面摘要与详细摘要。
- `metrics`：网店总数、覆盖平台、国内网店数、海外网店数、产品总数、累计销售额、店铺数等指标卡。
- `caliber`：匹配对象、匹配方式、数据范围、产品、局限。
- `core_analysis`：网店概况（KV）、电商产品画像（表或 KV）、电商店铺信息（表或 KV）。
- `representative_records`：代表性店铺 / 产品记录。
- `insights`：结构化解读（网店规模 / 平台覆盖 / 产品画像 / 店铺布局）。
- `data_source`：MCP server、数据产品、生成时间、是否 dry-run。

若 API 调用失败，明确报出缺失的配置 / 缺失的工具 / MCP 错误 / 参数校验错误 / 上游网络错误，给出 dry-run 命令或配置步骤，绝不暴露密钥。
