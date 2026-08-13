#!/usr/bin/env python3
"""Compose an e-store big-data report by orchestrating the estore MCP.

Calls the upstream estore-mcp-server tools and assembles a structured JSON
payload rendered into a professional HTML / Markdown report. Supports
``--dry-run`` which returns a well-formed skeleton from the bundled sample data
WITHOUT contacting the MCP.

Workflow (real run):
  1. Resolve the canonical enterprise name (fuzzy search if only a keyword).
  2. Query 国内外网店概况 / 电商产品画像 / 电商店铺信息.
  3. Build unified report JSON with domain sections.
  4. Optionally render HTML + Markdown.

This file never prints secrets; MCP credentials live in the server's own .env.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from common import REPORT_BANNER, REPORT_TYPE, json_dumps, load_json_file, print_json
import mcp_client
from render_report import render_html, render_markdown, html_to_pdf

SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "assets" / "report.example.json"

# E-store MCP tools.
T_FUZZY = "estore_bigdata_fuzzy_search"
T_PROFILE = "estore_bigdata_global_online_store_profile"
T_PRODUCT = "estore_bigdata_ecommerce_product_profile"
T_STORE = "estore_bigdata_ecommerce_store_info"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _is_api_error(value: Any) -> bool:
    """Detect MCP API error responses (not empty data, but actual failures like 405)."""
    if value is None:
        return False
    if isinstance(value, str):
        return any(s in value for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5"))
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and any(s in v for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5")):
                return True
    return False

def _first_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if _is_api_error(value):
            return []
        # Treat upstream empty responses ({"text": "查询数据为空"}) and internal
        # skip markers ({"_error": "未指定..."}) as empty so tables don't render
        # a phantom all-"-" row.
        if set(value.keys()) <= {"text", "error", "code", "_error"} and not any(
            isinstance(value.get(k), list) for k in ("resultList", "list", "items", "data")
        ):
            return []
        for key in ("resultList", "list", "items", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    if value in (None, "", {}):
        return []
    return [value]


def _first_record(value: Any) -> Dict[str, Any]:
    for record in _first_list(value):
        if isinstance(record, dict):
            return record
    if isinstance(value, dict):
        return value
    return {}


def _text(value: Any, limit: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        t = json.dumps(value, ensure_ascii=False)
    else:
        t = str(value)
    t = " ".join(t.split())
    if limit and len(t) > limit:
        return t[: limit - 1].rstrip() + "…"
    return t


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_call(tool: str, arguments: Dict[str, Any]) -> Any:
    try:
        result = mcp_client.call_tool(tool, arguments)
        if _is_api_error(result):
            return {"_error": "API错误"}
        return result
    except Exception as exc:
        return {"_error": str(exc)}


def _safe_total(payload: Any) -> Any:
    if isinstance(payload, dict):
        if _is_api_error(payload):
            return None
        return payload.get("total")
    return None


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def resolve_enterprise_name(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {"keyword": "", "enterprise": "", "resolved": False, "reason": "关键词为空"}
    if any(suffix in raw for suffix in ("公司", "集团", "有限", "院", "厂", "中心", "事务所", "合作社", "合伙")):
        return {"keyword": raw, "enterprise": raw, "resolved": True, "reason": "视为企业全称"}
    fuzzy = _safe_call(T_FUZZY, {"matchKeyword": raw, "pageSize": 1})
    record = _first_record(fuzzy)
    name = str(record.get("name") or "").strip()
    if name:
        return {"keyword": raw, "enterprise": name, "resolved": True, "reason": "由关键词模糊查询补全", "fuzzy_total": _int(_safe_total(fuzzy)), "record": record}
    return {"keyword": raw, "enterprise": raw, "resolved": False, "reason": "模糊查询未命中企业全称，按关键词直查"}


# --------------------------------------------------------------------------- #
# Enterprise profile helpers (from fuzzy_search record)
# --------------------------------------------------------------------------- #

def _extract_profile(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract enterprise profile fields from a fuzzy_search record."""
    return {
        "name": _text(record.get("name")),
        "reg_capital": record.get("regCapitalValue"),
        "reg_capital_coin": _text(record.get("regCapitalCoinType")),
        "annual_turnover": _text(record.get("annualTurnover")),
        "oper_status": _text(record.get("operStatus")),
        "enterprise_type": _text(record.get("enterpriseType")),
        "found_time": _text(record.get("foundTime")),
        "legal_rep": _text(record.get("legalRepresentative")),
        "address": _text(record.get("address")),
        "homepage": _text(record.get("homepage")),
    }


def _format_capital(val: Any, coin: str = "") -> str:
    """Format capital value: 10995210218.0 -> '109.95 亿'."""
    try:
        v = float(val)
        if v >= 1e8:
            s = f"{v / 1e8:.2f} 亿"
        elif v >= 1e4:
            s = f"{v / 1e4:.2f} 万"
        else:
            s = f"{v:.0f}"
        if coin:
            s += f" {coin}"
        return s
    except (TypeError, ValueError):
        return _text(val) if val else "-"


def _enrich_metrics_with_profile(metrics: List[Dict[str, Any]], record: Any) -> List[Dict[str, Any]]:
    """Append enterprise profile metrics from a fuzzy_search record."""
    if not isinstance(record, dict):
        return metrics
    _prof = _extract_profile(record)
    if _prof.get("reg_capital") and _prof["reg_capital"] not in ("-", "", None):
        metrics.append({"label": "注册资本", "value": _format_capital(_prof["reg_capital"], _prof.get("reg_capital_coin", "")), "hint": "工商登记注册资本"})
    if _prof.get("found_time") and _prof["found_time"] != "-":
        metrics.append({"label": "成立时间", "value": _prof["found_time"], "hint": "工商登记成立日期"})
    if _prof.get("oper_status") and _prof["oper_status"] != "-":
        metrics.append({"label": "经营状态", "value": _prof["oper_status"], "hint": "工商登记经营状态"})
    if _prof.get("enterprise_type") and _prof["enterprise_type"] != "-":
        metrics.append({"label": "企业类型", "value": _prof["enterprise_type"], "hint": "工商登记企业类型"})
    if _prof.get("legal_rep") and _prof["legal_rep"] != "-":
        metrics.append({"label": "法定代表人", "value": _prof["legal_rep"], "hint": "工商登记法定代表人"})
    return metrics


def _derive_core_metrics(metrics: List[Dict[str, Any]], core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Derive additional metrics from core analysis sections."""
    platform_dist = core.get("platform_dist", []) if isinstance(core, dict) else []
    stores = core.get("store_table", []) if isinstance(core, dict) else []
    profile = core.get("profile_overview", {}) if isinstance(core, dict) else {}
    if isinstance(platform_dist, list) and platform_dist:
        metrics.append({"label": "电商平台数", "value": str(len(platform_dist)), "hint": "覆盖的电商平台数量"})
    if isinstance(stores, list) and stores:
        try:
            total_sales = sum(float(str(r.get("销量", "0")).replace(",", "")) for r in stores if str(r.get("销量", "0")).replace(",", "").replace(".", "").isdigit())
            if total_sales > 0:
                metrics.append({"label": "店铺总销量", "value": f"{total_sales:.0f}", "hint": "电商店铺销量合计"})
        except Exception:
            pass
    if isinstance(profile, dict) and profile:
        cats = profile.get("商品类目数")
        if cats and str(cats) not in ("-", "", "0", "None"):
            metrics.append({"label": "商品类目数", "value": str(cats), "hint": "覆盖的商品类目总数"})
    return metrics


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #

def build_subject(raw: str, resolved: Mapping[str, Any], keyword_type: str) -> Dict[str, Any]:
    return {
        "enterprise": resolved.get("enterprise") or raw,
        "matchKeyword": resolved.get("enterprise") or raw,
        "keywordType": keyword_type,
        "match_raw": raw,
        "resolved": bool(resolved.get("resolved")),
        "resolve_reason": resolved.get("reason", ""),
    }


def build_caliber(subject: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "match_target": subject.get("enterprise") or subject.get("match_raw"),
        "match_type": f"网店维度按企业主体匹配（keywordType={subject.get('keywordType', 'name')}）；支持企业名称/注册号/统一社会信用代码/企业 id",
        "data_scope": "国内外网店概况、电商产品画像、电商店铺信息",
        "products": ["国内外网店概况", "电商产品画像", "电商店铺信息"],
        "limit": "数据来自电商平台公开信息；少量字段可能存在更新延迟。",
    }


def _kv_from(payload: Any, mapping: List[tuple]) -> Dict[str, Any]:
    p = payload if isinstance(payload, dict) else {}
    out: Dict[str, Any] = {}
    for key, label in mapping:
        val = p.get(key)
        if val not in (None, "", [], {}):
            out[label] = _text(val)
    return out


def _table_from(payload: Any, fields: List[tuple]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in _first_list(payload):
        if not isinstance(item, dict):
            continue
        row: Dict[str, Any] = {}
        for key, label in fields:
            row[label] = _text(item.get(key)) or "-"
        rows.append(row)
    return rows


def _platform_rows(store_rows: List[Mapping[str, Any]], product_rows: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate store/product rows by 所属平台 into a {平台,数量} distribution."""
    counts: Dict[str, int] = {}
    pool = list(store_rows) + list(product_rows)
    for r in pool:
        p = (r.get("所属平台") or "-").strip()
        if not p or p == "-":
            continue
        counts[p] = counts.get(p, 0) + 1
    out = [{"平台": k, "店铺/商品数": str(v)} for k, v in counts.items()]
    out.sort(key=lambda x: int(x["店铺/商品数"]), reverse=True)
    return out


def _concentration(rows: List[Mapping[str, Any]], name_key: str, value_key: str, top_n: int = 3) -> Dict[str, Any]:
    """Compute top-N concentration (CRn) and dominant category from {name,count} rows."""
    items = []
    for r in rows:
        try:
            items.append((r.get(name_key, "-"), float(str(r.get(value_key, 0)).replace(",", ""))))
        except (TypeError, ValueError):
            items.append((r.get(name_key, "-"), 0.0))
    total = sum(v for _, v in items)
    if not total:
        return {}
    items.sort(key=lambda x: x[1], reverse=True)
    cr = sum(v for _, v in items[:top_n]) / total * 100
    return {"top": items[0][0], "top_share": items[0][1] / total * 100, "cr": cr, "total": total, "n": len(items)}


def _platform_rows_from_list(platform_list: Sequence[str]) -> List[Dict[str, Any]]:
    """Build a {平台, 数量} distribution from a flat platform-name list.

    The estore profile returns the platforms the enterprise sells on; each
    platform counts as 1 source (we cannot derive per-platform store counts
    from the list, so we present coverage breadth).
    """
    counts: Dict[str, int] = {}
    for p in platform_list:
        name = str(p or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    out = [{"平台": k, "店铺/商品数": str(v)} for k, v in counts.items()]
    out.sort(key=lambda x: int(x["店铺/商品数"]), reverse=True)
    return out


def build_core_analysis(profile: Any, product: Any, store: Any) -> Dict[str, Any]:
    p = profile if isinstance(profile, dict) else {}
    prod = product if isinstance(product, dict) else {}
    st = store if isinstance(store, dict) else {}

    # 网店概况 KV — 真实字段：domesticEshopCount / domesticEshopProductCount /
    # domesticEshopPlatformList / domesticEshopBrandList / domesticEshopProductList。
    profile_kv: Dict[str, Any] = {}
    if p.get("domesticEshopCount") is not None:
        profile_kv["国内网店数"] = _text(p.get("domesticEshopCount"))
    if p.get("domesticEshopProductCount") is not None:
        profile_kv["国内网店商品数"] = _text(p.get("domesticEshopProductCount"))
    plat_list = p.get("domesticEshopPlatformList")
    if isinstance(plat_list, list) and plat_list:
        profile_kv["覆盖平台"] = "、".join(str(x) for x in plat_list if x)
        profile_kv["覆盖平台数"] = str(len(plat_list))
    brand_list = p.get("domesticEshopBrandList")
    if isinstance(brand_list, list) and brand_list:
        profile_kv["运营品牌"] = "、".join(str(x) for x in brand_list if x)
    prod_cat_list = p.get("domesticEshopProductList")
    if isinstance(prod_cat_list, list) and prod_cat_list:
        profile_kv["商品类目数"] = str(len(prod_cat_list))
        profile_kv["主要商品类目"] = "、".join(str(x) for x in prod_cat_list[:15] if x) + ("…" if len(prod_cat_list) > 15 else "")

    # 电商产品画像 KV — 真实字段：ecShopAvgRates / ecShopItemCount / ecShopNumber /
    # ecShopEarliestFoundTime / ecShopBrands / ecShopItemCategories / ecSources。
    product_kv: Dict[str, Any] = {}
    if prod.get("ecShopNumber") is not None:
        product_kv["电商店铺数"] = _text(prod.get("ecShopNumber"))
    if prod.get("ecShopItemCount") is not None:
        product_kv["在售商品数"] = _text(prod.get("ecShopItemCount"))
    if prod.get("ecShopAvgRates") is not None:
        product_kv["店铺平均评分"] = _text(prod.get("ecShopAvgRates"))
    if prod.get("ecShopEarliestFoundTime"):
        product_kv["最早开店时间"] = _text(prod.get("ecShopEarliestFoundTime"))
    brands = prod.get("ecShopBrands")
    if isinstance(brands, list) and brands:
        product_kv["商品品牌"] = "、".join(str(x) for x in brands if x)
    cats = prod.get("ecShopItemCategories")
    if isinstance(cats, list) and cats:
        product_kv["商品类目"] = "、".join(str(x) for x in cats if x)
        product_kv["商品类目数"] = str(len(cats))
    sources = prod.get("ecSources")
    if isinstance(sources, list) and sources:
        product_kv["电商来源平台"] = "、".join(str(x) for x in sources if x)

    # 电商店铺信息表 — 真实字段：eshopList[{eshopName, eshopUrl, eshopFoundTime,
    # isExpired, businessStatistics:{totalSaleAmount, totalSaleQty, fans,
    # favorableRate, eshopComprehensiveScore, eshopProductCount}}]。
    store_rows: List[Dict[str, Any]] = []
    eshop_list = st.get("eshopList") if isinstance(st, dict) else None
    if not isinstance(eshop_list, list):
        eshop_list = _first_list(st)
    for item in eshop_list:
        if not isinstance(item, dict):
            continue
        bs = item.get("businessStatistics") or {}
        store_rows.append({
            "店铺名称": _text(item.get("eshopName")) or "-",
            "链接": _text(item.get("eshopUrl")) or "-",
            "开店时间": _text(item.get("eshopFoundTime")) or "-",
            "状态": ("已下线" if item.get("isExpired") else "在营") if item.get("isExpired") is not None else "-",
            "销售额": _text(bs.get("totalSaleAmount")) or "-",
            "销量": _text(bs.get("totalSaleQty")) or "-",
            "粉丝数": _text(bs.get("fans")) or "-",
            "好评率": _text(bs.get("favorableRate")) or "-",
            "综合评分": _text(bs.get("eshopComprehensiveScore")) or "-",
            "在售商品数": _text(bs.get("eshopProductCount")) or "-",
        })

    # 派生：平台分布（优先 profile.domesticEshopPlatformList，回退 product.ecSources）。
    platform_rows: List[Dict[str, Any]] = []
    src_list = plat_list if isinstance(plat_list, list) and plat_list else sources
    if isinstance(src_list, list) and src_list:
        platform_rows = _platform_rows_from_list([str(x) for x in src_list if x])

    sections: List[Dict[str, Any]] = [
        {"key": "profile_overview", "title": "网店概况", "kind": "kv", "note": "国内外网店整体概况"},
        {"key": "product_overview", "title": "电商产品画像", "kind": "kv", "note": "电商在售商品规模、评分与品牌类目分布"},
        {"key": "platform_dist", "title": "电商平台分布", "kind": "bar", "note": "企业覆盖的电商平台",
         "chart": {"name": "平台", "value": "店铺/商品数", "orient": "v"},
         "columns": [("平台", "平台"), ("店铺/商品数", "店铺/商品数")]},
        {"key": "store_table", "title": "电商店铺信息", "kind": "table", "note": f"共 {len(store_rows)} 家店铺，展示前 N 家",
         "columns": [("店铺名称", "店铺名称"), ("链接", "链接"), ("开店时间", "开店时间"), ("状态", "状态"), ("销售额", "销售额"), ("粉丝数", "粉丝数"), ("好评率", "好评率"), ("综合评分", "综合评分")]},
    ]
    return {
        "sections": sections,
        "profile_overview": profile_kv,
        "product_overview": product_kv,
        "platform_dist": platform_rows,
        "store_table": store_rows,
    }


def build_records(core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in core.get("store_table") or []:
        rows.append({
            "店铺名称": item.get("店铺名称") or "-",
            "开店时间": item.get("开店时间") or "-",
            "状态": item.get("状态") or "-",
            "销售额": item.get("销售额") or "-",
            "粉丝数": item.get("粉丝数") or "-",
        })
    return rows[:20]


def build_insights(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    metric_map = {m["label"]: str(m["value"]) for m in metrics}
    store_count = metric_map.get("网店总数") or metric_map.get("国内网店数")
    platforms = metric_map.get("覆盖平台")
    product_total = metric_map.get("电商产品数") or metric_map.get("在售商品数")
    profile_kv = core.get("profile_overview") or {}
    product_kv = core.get("product_overview") or {}

    if store_count:
        # 是否有海外数据
        ovs = metric_map.get("海外网店数")
        dom = metric_map.get("国内网店数")
        if dom and ovs:
            try:
                d = float(dom); o = float(ovs); tot = d + o
                if tot > 0:
                    insights.append({
                        "feature": "网店规模与区域结构",
                        "evidence": f"网店总数 {int(tot)}（国内 {dom}、海外 {ovs}），国内占比 {d / tot * 100:.0f}%。",
                        "interpretation": "国内/海外网店结构反映企业电商的全球化程度：海外占比越高代表出海布局越深，国内占比越高则聚焦本土流量。",
                    })
            except (TypeError, ValueError):
                pass
        else:
            insights.append({
                "feature": "网店规模",
                "evidence": f"网店总数 {store_count}。",
                "interpretation": "网店数量反映企业电商业务覆盖广度；结合平台分布可评估线上渠道布局的多元化程度。",
            })
    platform_rows = core.get("platform_dist") or []
    if platform_rows:
        conc = _concentration(platform_rows, "平台", "店铺/商品数", 2)
        if conc:
            insights.append({
                "feature": "平台覆盖",
                "evidence": f"覆盖 {conc['n']} 个电商平台，主流平台为“{conc['top']}”。",
                "interpretation": "平台覆盖面反映渠道触达能力；CR2 偏高意味着流量集中于少数平台、议价与政策风险较高；平台数多则代表多渠道分散布局。",
            })
    elif platforms:
        insights.append({
            "feature": "平台覆盖",
            "evidence": f"覆盖平台：{platforms}。",
            "interpretation": "多平台布局有助于分散单一平台流量与政策风险，但也对运营资源提出更高要求。",
        })
    # 商品密度：在售商品数 / 网店数
    if product_total and store_count:
        try:
            pt = float(str(product_total).replace(" 个", ""))
            stores = float(str(store_count).replace(" 个", ""))
            if stores > 0:
                insights.append({
                    "feature": "商品密度",
                    "evidence": f"在售商品 {int(pt)} 件、网店 {int(stores)} 家，店均商品约 {pt / stores:.1f} 件。",
                    "interpretation": "店均商品数反映单店的 SKU 广度：比值高通常意味着大店/综合店运营，比值低则代表精品店/品牌专卖店模式。",
                })
        except (TypeError, ValueError):
            pass
    # 店铺评分/粉丝画像
    store_rows = core.get("store_table") or []
    if store_rows:
        insights.append({
            "feature": "店铺布局",
            "evidence": f"电商店铺明细 {len(store_rows)} 家。",
            "interpretation": "店铺明细反映企业电商渠道的具体形态与开店年限；结合销售额与粉丝数可评估单店运营成熟度。",
        })
    # 平均评分 insight
    avg_rate = product_kv.get("店铺平均评分")
    if avg_rate:
        insights.append({
            "feature": "店铺口碑",
            "evidence": f"店铺平均评分 {avg_rate}。",
            "interpretation": "店铺评分反映消费者口碑与商品质量稳定性；评分越高通常对应复购率与转化率越高。",
        })
    if not insights:
        insights.append({
            "feature": "数据完整性",
            "evidence": "部分维度未返回有效数据。",
            "interpretation": "建议核对匹配关键词是否为企业全称，或检查 MCP 连接与上游数据产品覆盖范围。",
        })
    return insights


def build_metrics(profile: Any, product: Any, store: Any) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    p = profile if isinstance(profile, dict) and "_error" not in profile else {}
    prod = product if isinstance(product, dict) and "_error" not in product else {}
    st = store if isinstance(store, dict) and "_error" not in store else {}

    # 真实字段：domesticEshopCount / domesticEshopProductCount / domesticEshopPlatformList / overseasEshop*。
    dom_n = _int(p.get("domesticEshopCount"))
    ovs_n = _int(p.get("overseasEshopCount"))
    store_n = (dom_n or 0) + (ovs_n or 0)
    # 回退到店铺信息接口的 eshopListCount / overview.enterpriseEshopCount。
    if not store_n and isinstance(st, dict):
        store_n = _int(st.get("eshopListCount")) or _int((st.get("overview") or {}).get("enterpriseEshopCount"))
    if store_n:
        metrics.append({"label": "网店总数", "value": str(store_n), "hint": "国内外网店总量"})
    if dom_n is not None:
        if dom_n and ovs_n:
            metrics.append({"label": "国内网店数", "value": str(dom_n), "hint": "国内网店数量", "delta": f"国内占比 {dom_n / (dom_n + ovs_n) * 100:.0f}%"})
        else:
            metrics.append({"label": "国内网店数", "value": str(dom_n) if dom_n is not None else "-", "hint": "国内网店数量"})
    if ovs_n is not None:
        metrics.append({"label": "海外网店数", "value": str(ovs_n), "hint": "海外网店数量"})
    # 平台覆盖
    platforms = p.get("domesticEshopPlatformList") or p.get("overseasEshopPlatformList")
    if isinstance(platforms, list) and platforms:
        metrics.append({"label": "覆盖平台", "value": str(len(platforms)) + " 个", "hint": "覆盖电商平台数"})
    # 产品数：profile.domesticEshopProductCount 或 product.ecShopItemCount。
    prod_n = _int(p.get("domesticEshopProductCount")) or _int(prod.get("ecShopItemCount"))
    if prod_n is not None:
        if prod_n and store_n:
            metrics.append({"label": "电商产品数", "value": str(prod_n), "hint": "电商在售商品总量", "delta": f"店均商品 {prod_n / store_n:.1f}"})
        else:
            metrics.append({"label": "电商产品数", "value": str(prod_n), "hint": "电商在售商品总量"})
    # 店铺平均评分
    avg_rate = prod.get("ecShopAvgRates")
    if avg_rate is not None:
        metrics.append({"label": "店铺平均评分", "value": _text(avg_rate), "hint": "电商店铺平均评分"})
    # 店铺明细数
    if isinstance(st, dict):
        shop_detail_n = _int(st.get("eshopListCount")) or (len(st.get("eshopList") or []) if isinstance(st.get("eshopList"), list) else None)
        if shop_detail_n is not None:
            metrics.append({"label": "店铺明细", "value": str(shop_detail_n), "hint": "电商店铺明细条数"})
    return [m for m in metrics if m.get("value") not in ("", None, "-")]


def build_abstract(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> str:
    name = subject.get("enterprise") or subject.get("match_raw") or "目标企业"
    parts = [f"本报告以“{name}”为分析对象，基于电商平台公开数据，系统呈现企业国内外网店概况、电商产品画像与电商店铺信息。"]
    if metrics:
        kv = "、".join(f"{m['label']} {m['value']}" for m in metrics[:5])
        parts.append(f"关键指标包括：{kv}。")
    parts.append("报告围绕网店规模、平台覆盖与产品/店铺结构给出结构化解读，便于电商运营、渠道管理与竞品分析决策参考。")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Dry-run sample
# --------------------------------------------------------------------------- #

def build_dry_run_payload(raw: str, keyword_type: str) -> Dict[str, Any]:
    try:
        sample = load_json_file(SAMPLE_PATH)
    except Exception:
        sample = {}
    sample = sample if isinstance(sample, dict) else {}
    subject = sample.get("subject") or {"enterprise": raw, "matchKeyword": raw, "keywordType": keyword_type, "match_raw": raw}
    subject = {**subject, "match_raw": raw, "keywordType": keyword_type}
    core = sample.get("core_analysis") or {}
    metrics = sample.get("metrics") or []
    return _assemble(subject, core, metrics, dry_run=True)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def _assemble(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
    abstract = build_abstract(subject, core, metrics)
    records = build_records(core)
    insights = build_insights(subject, core, metrics)
    # Quality gate: count populated core-analysis sections.
    ca = core if isinstance(core, dict) else {}
    secs = ca.get("sections", [])
    if secs:
        total_secs = len(secs)
        populated = sum(1 for s in secs if isinstance(s, dict) and ca.get(s.get("key")) not in (None, "", [], {}))
    else:
        total_secs = max(1, len([k for k in ca if k != "sections"]))
        populated = sum(1 for k in ca if k != "sections" and ca.get(k) not in (None, "", [], {}))
    quality_report = {
        "total_sections": total_secs,
        "populated_sections": populated,
        "empty_sections": total_secs - populated,
        "coverage_pct": round(populated / max(1, total_secs) * 100),
    }
    if populated == 0:
        import sys
        print("⚠️ 质量门禁警告: 所有核心分析维度均无数据", file=sys.stderr)
    title = f"{subject.get('enterprise') or '目标企业'} 网店大数据报告"
    return {
        "report_type": REPORT_TYPE,
        "title": title,
        "banner": REPORT_BANNER,
        "subject": dict(subject),
        "abstract": abstract,
        "summary": abstract,
        "executive_summary": [item["interpretation"] for item in insights][:5] or [abstract[:120]],
        "metrics": list(metrics),
        "caliber": build_caliber(subject),
        "core_analysis": dict(core),
        "representative_records": records,
        "insights": insights,
        "data_source": {
            "mcp_server": "estore-mcp-server",
            "products": [
                {"name": "国内外网店概况", "product_id": "66d5b7df537c3f61d646c327"},
                {"name": "电商产品画像", "product_id": "66c33eff3c0917a9a02feba8"},
                {"name": "电商店铺信息", "product_id": "66a34ccedbee527b7a831c98"},
            ],
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "dry_run": dry_run,
            "quality_report": quality_report,
        },
    }


def build_payload(raw: str, keyword_type: str) -> Dict[str, Any]:
    resolved = resolve_enterprise_name(raw)
    enterprise = resolved["enterprise"]
    mk_args: Dict[str, Any] = {"matchKeyword": enterprise, "keywordType": keyword_type}

    profile = _safe_call(T_PROFILE, mk_args)
    product = _safe_call(T_PRODUCT, mk_args)
    store = _safe_call(T_STORE, mk_args)

    subject = build_subject(raw, resolved, keyword_type)
    core = build_core_analysis(profile, product, store)
    metrics = build_metrics(profile, product, store)
    _derive_core_metrics(metrics, core if isinstance(core, dict) else {})
    # --- Enterprise profile enrichment (from fuzzy_search) ---
    _enrich_metrics_with_profile(metrics, resolved.get("record") if isinstance(resolved, dict) else None)
    return _assemble(subject, core, metrics, dry_run=False)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Compose an e-store big-data report via the estore MCP.")
    parser.add_argument("--enterprise", required=True, help="企业全称或关键词（关键词将自动模糊补全）")
    parser.add_argument("--keyword-type", default="name", help="主体类型：name/nameId/regNumber/socialCreditCode")
    parser.add_argument("--dry-run", action="store_true", help="不调用真实 MCP，使用样例数据组装报告骨架")
    parser.add_argument("--output", help="输出 JSON 路径；省略则打印到 stdout")
    parser.add_argument("--report-output", help="同时输出 HTML 报告（.html）与 Markdown 报告（.md）")
    parser.add_argument("--pdf-output", help="额外输出 PDF 报告（.pdf）；需要 Playwright + Chromium")
    args = parser.parse_args()

    if args.dry_run:
        payload = build_dry_run_payload(args.enterprise, args.keyword_type)
    else:
        payload = build_payload(args.enterprise, args.keyword_type)

    if args.output:
        out = pathlib.Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json_dumps(payload, pretty=True), encoding="utf-8")
        print_json({"ok": True, "json": str(out), "dry_run": args.dry_run})
    else:
        print_json(payload)

    if args.report_output:
        base_out = pathlib.Path(args.report_output).expanduser()
        base_out.parent.mkdir(parents=True, exist_ok=True)
        html_path = base_out.with_suffix(".html") if base_out.suffix.lower() not in (".html", ".htm") else base_out
        md_path = html_path.with_suffix(".md")
        html_path.write_text(render_html(payload), encoding="utf-8")
        md_path.write_text(render_markdown(payload), encoding="utf-8")
        if args.pdf_output:
            pdf_path = pathlib.Path(args.pdf_output).expanduser()
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            html_to_pdf(render_html(payload), str(pdf_path))
        print_json({"ok": True, "html": str(html_path), "markdown": str(md_path), "pdf": str(pdf_path) if args.pdf_output else None, "dry_run": args.dry_run})


if __name__ == "__main__":
    main()
