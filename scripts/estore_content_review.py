#!/usr/bin/env python3
"""Offline content review for an existing estore report.

Pure ``apply_content_review(report)`` separates platforms from channel types,
keeps different product universes apart, formats ratios without losing the
upstream precision, and replaces unsupported marketing claims with evidence
limits. It never calls the MCP.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from typing import Any, Dict, List, Mapping, Optional

_PLATFORM_ALIASES = {
    "天猫": "天猫", "tmall": "天猫",
    "淘宝": "淘宝", "taobao": "淘宝",
    "京东": "京东", "jd": "京东", "jd.com": "京东",
    "苏宁": "苏宁", "suning": "苏宁",
    "1688": "1688", "阿里巴巴": "1688",
    "拼多多": "拼多多", "pinduoduo": "拼多多",
    "抖音": "抖音", "douyin": "抖音", "抖音小店": "抖音",
    "快手": "快手", "kuaishou": "快手",
    "唯品会": "唯品会", "vip": "唯品会",
    "小红书": "小红书", "xiaohongshu": "小红书",
    "当当": "当当", "dangdang": "当当",
    "国美": "国美", "gome": "国美",
    "亚马逊": "亚马逊", "amazon": "亚马逊",
    "ebay": "eBay", "shopee": "Shopee", "lazada": "Lazada",
    "tiktok shop": "TikTok Shop",
}
# Not an e-commerce platform: a store format or traffic channel.
_NON_PLATFORM = {
    "直播店": "直播店（渠道类型）", "直播": "直播（渠道类型）",
    "短视频": "短视频（渠道类型）", "社交电商": "社交电商（渠道类型）",
    "私域": "私域（渠道类型）", "线下": "线下（渠道类型）",
}
_HOST_PLATFORM = [
    (("jd.com", "jd.hk"), "京东"),
    (("tmall.com", "tmall.hk"), "天猫"),
    (("taobao.com",), "淘宝"),
    (("suning.com",), "苏宁"),
    (("1688.com",), "1688"),
    (("jinritemai.com", "douyin.com"), "抖音"),
    (("kuaishou.com",), "快手"),
    (("pinduoduo.com", "yangkeduo.com"), "拼多多"),
    (("vip.com",), "唯品会"),
    (("gome.com.cn",), "国美"),
    (("xiaohongshu.com", "xhslink.com"), "小红书"),
]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _split(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [_text(v) for v in value if _text(v)]
    text = _text(value)
    if not text or text in {"-", "—"}:
        return []
    return [p.strip() for p in re.split(r"[、,，;；]", text) if p.strip() and p.strip() not in {"-", "—"}]


def _dedupe(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _platform(raw: str) -> Optional[str]:
    key = _text(raw).casefold()
    if not key:
        return None
    if key in {k.casefold() for k in _NON_PLATFORM}:
        for k, v in _NON_PLATFORM.items():
            if key == k.casefold():
                return v
        return None
    if key in _PLATFORM_ALIASES:
        return _PLATFORM_ALIASES[key]
    for k, v in _PLATFORM_ALIASES.items():
        if key == k.casefold():
            return v
    return _text(raw)


def _is_non_platform(name: str) -> bool:
    return "渠道类型" in name


def _platform_from_url(url: str) -> str:
    text = _text(url)
    if not text or text == "-":
        return "待核实"
    parsed = urlsplit(text if "://" in text or text.startswith("//") else "//" + text)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "待核实"
    for domains, name in _HOST_PLATFORM:
        for domain in domains:
            base = domain.lower().rstrip(".")
            if host == base or host.endswith("." + base):
                return name
    return "待核实"


def _ratio_text(raw: Any) -> str:
    text = _text(raw)
    if not text or text in {"-", "—"}:
        return "-"
    if "%" in text:
        return text
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if number != 0 and abs(number) <= 1:
        number *= 100
    return f"{format(number.normalize(), 'f')}%"


def _score_text(raw: Any) -> str:
    text = _text(raw)
    if not text or text in {"-", "—"}:
        return "-"
    try:
        return f"{float(text):.2f}"
    except (TypeError, ValueError):
        return text


def _amount_text(raw: Any) -> str:
    text = _text(raw)
    if not text or text in {"-", "—"}:
        return "-"
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if number == number.to_integral():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _int(value: Any) -> Optional[int]:
    text = _text(value)
    if not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def _same_number(left: Any, right: Any) -> bool:
    def _number(value: Any) -> Optional[Decimal]:
        text = _text(value).replace(",", "")
        if text.endswith(" 个"):
            text = text[:-2]
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    a, b = _number(left), _number(right)
    return a is not None and b is not None and a == b


def _clean_categories(text: str) -> tuple[str, List[str]]:
    """Drop price-like tokens that upstream put in the category list."""
    items = _split(text)
    cleaned: List[str] = []
    removed: List[str] = []
    for item in items:
        token = item.replace("…", "").strip()
        if not token:
            continue
        compact = token.replace(",", "").replace("，", "")
        if re.fullmatch(r"\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*元?", compact) or \
           re.fullmatch(r"\d+(?:\.\d+)?\s*元", compact) or \
           re.fullmatch(r"\d{4,}", compact):
            removed.append(token)
            continue
        cleaned.append(token)
    if text.rstrip().endswith("…") and cleaned:
        cleaned[-1] = cleaned[-1] + "…"
    return "、".join(cleaned), removed


def _fix_caliber(report: Dict[str, Any]) -> None:
    caliber = report.get("caliber")
    if isinstance(caliber, dict):
        caliber["match_type"] = "网店维度按企业名称匹配；支持企业名称、注册号、统一社会信用代码和企业 ID"
        limit = _text(caliber.get("limit"))
        extra = [
            "销售额、评分与好评率均为上游原值，币种、单位与满分制未声明；0 表示上游返回 0，不等于缺失",
            "店铺平台由上游平台字段与店铺链接域名交叉核对，链接域名无法识别时标注“待核实”",
        ]
        for sentence in extra:
            if sentence not in limit:
                limit = (limit.rstrip("。") + "。" + sentence).lstrip("。")
        caliber["limit"] = limit


def _fix_profile(core: Dict[str, Any]) -> tuple[List[str], List[str], bool]:
    profile = core.get("profile_overview")
    if not isinstance(profile, dict):
        return [], [], False
    raw_platform_text = _text(profile.get("覆盖平台"))
    no_platform_text = "无（上游仅返回渠道类型）"
    has_platform_field = raw_platform_text not in ("", "-", "—")
    raw_platforms = [] if raw_platform_text == no_platform_text else _split(raw_platform_text)
    platforms, channels = [], []
    for item in raw_platforms:
        canonical = _platform(item) or item
        if _is_non_platform(canonical):
            channels.append(canonical)
        else:
            platforms.append(canonical)
    for item in _split(profile.get("其他渠道类型")):
        canonical = _platform(item) or item
        if _is_non_platform(canonical):
            channels.append(canonical)
    platforms = _dedupe(platforms)
    channels = _dedupe(channels)
    if platforms:
        profile["覆盖平台"] = "、".join(platforms)
    elif has_platform_field:
        # Upstream returned only channel types (e.g. 直播店); do not let them
        # remain under the platform field or imply a platform count.
        profile["覆盖平台"] = no_platform_text
    if channels:
        profile["其他渠道类型"] = "、".join(channels)
    if has_platform_field:
        profile["覆盖平台数"] = str(len(platforms))
    if profile.get("主要商品类目"):
        cleaned, removed = _clean_categories(_text(profile.get("主要商品类目")))
        profile["主要商品类目"] = cleaned
        if removed:
            profile["类目口径"] = "上游商品清单混入疑似价格值：" + "、".join(removed) + "；已从类目展示中剔除，类目总数仍按上游清单条数"
    if "商品类目数" in profile:
        profile["网店概况商品类目数"] = profile.pop("商品类目数")
    return platforms, channels, has_platform_field


def _fix_product(core: Dict[str, Any]) -> None:
    product = core.get("product_overview")
    if not isinstance(product, dict):
        return
    rename = {
        "电商店铺数": "产品画像店铺数",
        "在售商品数": "产品画像在售商品数",
        "商品类目数": "产品画像商品类目数",
        "店铺平均评分": "产品画像店铺平均评分",
    }
    for old, new in rename.items():
        if old in product:
            product[new] = product.pop(old)


def _fix_platform_section(core: Dict[str, Any], platforms: List[str], channels: List[str],
                          has_platform_field: bool) -> None:
    if has_platform_field:
        core["platform_dist"] = [{"平台": name, "覆盖状态": "有"} for name in platforms]
    else:
        # No profile platform list was returned. A non-empty platform_dist in
        # that case comes from the product profile's ecSources fallback, which
        # is a source field, not verified platform coverage.
        core["platform_dist"] = []
    sections = core.get("sections")
    if not isinstance(sections, list):
        return
    for section in sections:
        if isinstance(section, dict) and section.get("key") == "platform_dist":
            if not has_platform_field:
                section["note"] = ("上游网店概况未返回平台清单；产品画像的电商来源平台字段不等同于平台覆盖，"
                                   "不据此计算平台数、店铺数或集中度")
                section["columns"] = [("平台", "平台"), ("覆盖状态", "覆盖状态")]
                section.pop("chart", None)
                continue
            section["title"] = "电商平台覆盖"
            section["kind"] = "table"
            section["note"] = "仅表示上游平台清单中出现该平台，不代表店铺数、销量份额或集中度"
            if channels:
                section["note"] += f"；{ '、'.join(channels) } 属渠道类型，不计入平台数"
            section["columns"] = [("平台", "平台"), ("覆盖状态", "覆盖状态")]
            section.pop("chart", None)


def _fix_store_rows(core: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = core.get("store_table")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reviewed = dict(row)
        url = _text(reviewed.get("链接"))
        inferred = _platform_from_url(url)
        reviewed["平台（链接推断）"] = inferred
        for key, formatter in (("好评率", _ratio_text), ("综合评分", _score_text), ("销售额", _amount_text)):
            if key in reviewed:
                raw = reviewed[key]
                if formatter is _score_text and _text(raw) not in ("", "-", "—"):
                    reviewed["综合评分原始值"] = raw
                reviewed[key] = formatter(raw)
        out.append(reviewed)
    core["store_table"] = out
    sections = core.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict) and section.get("key") == "store_table":
                section["columns"] = [
                    ("店铺名称", "店铺名称"), ("所属企业", "所属企业"), ("关联性质", "关联性质"),
                    ("链接", "链接"), ("平台（链接推断）", "平台（链接推断）"), ("开店时间", "开店时间"),
                    ("状态", "状态"), ("销售额", "销售额"), ("粉丝数", "粉丝数"),
                    ("好评率", "好评率"), ("综合评分", "综合评分"),
                ]
                section["note"] = (
                    f"当前响应展示 {len(out)} 家关联网店；仅为本次返回记录，不代表全部店铺或平台覆盖，"
                    "关联不等于查询主体自营。平台由链接域名推断，待核实表示无法从域名确认；"
                    "销售额为上游原值（币种/单位未声明），0 表示返回 0"
                )
    return out


def _fix_records(report: Dict[str, Any], stores: List[Dict[str, Any]]) -> None:
    records = report.get("representative_records")
    if not isinstance(records, list):
        return
    by_name: Dict[tuple, Dict[str, Any]] = {}
    for row in stores:
        by_name[(_text(row.get("店铺名称")), _text(row.get("链接")))] = row
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        match = by_name.get((_text(record.get("店铺名称")), _text(record.get("链接"))))
        if not match and index < len(stores) and _text(stores[index].get("店铺名称")) == _text(record.get("店铺名称")):
            match = stores[index]
        if match:
            record["平台（链接推断）"] = match.get("平台（链接推断）")
        else:
            record["平台（链接推断）"] = _platform_from_url(_text(record.get("链接")))


def _fix_metrics(report: Dict[str, Any], core: Dict[str, Any], platforms: List[str],
                 has_platform_field: bool) -> None:
    metrics = [m for m in (report.get("metrics") or []) if isinstance(m, dict)]
    profile = core.get("profile_overview") if isinstance(core.get("profile_overview"), dict) else {}
    product_kv = core.get("product_overview") if isinstance(core.get("product_overview"), dict) else {}
    profile_product = _text(profile.get("国内网店商品数"))
    product_item = _text(product_kv.get("产品画像在售商品数") or product_kv.get("在售商品数"))
    product_provenance = ""
    out: List[Dict[str, Any]] = []
    seen = set()
    for metric in metrics:
        label = _text(metric.get("label"))
        product_source = ""
        if label == "电商平台数":
            continue  # exact duplicate of 覆盖平台
        if label == "覆盖平台":
            if has_platform_field:
                # The upstream profile platform list was returned; after
                # separating channel types the count can legitimately be 0.
                metric["value"] = f"{len(platforms)} 个"
                metric["hint"] = "已识别的国内网店概况电商平台数，不含直播店等渠道类型"
            else:
                # No profile platform field: the source metric may come from
                # the overseas platform list. Preserve that upstream coverage
                # instead of overwriting it with 0.
                metric["hint"] = ("上游平台清单（海外平台清单）返回的平台数；网店概况未列出逐项平台名称，"
                                  "产品画像来源平台和链接推断未计入")
        if label in {"电商产品数", "网店概况商品数", "产品画像在售商品数"}:
            value = _text(metric.get("value"))
            metric.pop("delta", None)
            if profile_product and _same_number(profile_product, value):
                metric["label"] = "网店概况商品数"
                metric["hint"] = "国内网店概况返回的商品数；与产品画像在售商品数分属不同产品，不互相相除"
                product_source = "profile"
            elif product_item and _same_number(product_item, value):
                metric["label"] = "产品画像在售商品数"
                metric["hint"] = "产品画像返回的在售商品数；与网店概况商品数、网店概况店铺数分属不同产品口径，不相除"
                product_source = "product"
            else:
                metric["hint"] = "上游返回的商品数；报告未提供可核对的来源字段，未与店铺数相除"
                product_source = "unknown"
        if label == "商品类目数":
            metric["label"] = "网店概况商品类目数"
            metric["hint"] = "国内外网店概况商品清单条数（已剔除疑似价格值）"
        if label == "店铺平均评分":
            metric["hint"] = "产品画像返回的店铺平均评分；满分制与统计口径未说明"
        if metric["label"] in seen:
            continue
        seen.add(metric["label"])
        out.append(metric)
        if product_source:
            product_provenance = product_source

    # Same-source store density only: profile product count / profile domestic
    # store count. Product-profile item counts and profile store counts belong
    # to different tool universes and are never divided here.
    product = next((m for m in out if m.get("label") == "网店概况商品数"), None)
    domestic = next((m for m in out if m.get("label") == "国内网店数"), None)
    if product_provenance == "profile" and product and domestic:
        p = _int(product.get("value"))
        d = _int(domestic.get("value"))
        if p and d:
            product["delta"] = f"店均商品 {p / d:.1f}（网店概况同口径）"
    report["metrics"] = out


def _build_insights(report: Dict[str, Any], core: Dict[str, Any], stores: List[Dict[str, Any]],
                    platforms: List[str], channels: List[str]) -> List[Dict[str, Any]]:
    metrics = {m.get("label"): _text(m.get("value")) for m in (report.get("metrics") or []) if isinstance(m, dict)}
    insights: List[Dict[str, Any]] = []
    store_total = metrics.get("网店总数")
    domestic_total = metrics.get("国内网店数")
    if store_total:
        insights.append({
            "feature": "网店规模",
            "evidence": f"网店总数 {store_total}" + (f"（国内 {domestic_total}）" if domestic_total else "") + "。",
            "interpretation": "网店数量为上游画像字段，仅表示该产品覆盖的网店记录数；不代表实际经营门店、全渠道规模或销量。",
        })
    elif domestic_total:
        insights.append({
            "feature": "网店规模",
            "evidence": f"国内网店数 {domestic_total}（上游未返回网店总数，不能把国内数当作总数）。",
            "interpretation": "网店数量为上游画像字段，仅表示该产品覆盖的国内网店记录数；不代表实际经营门店、全渠道规模或销量。",
        })
    if platforms or channels:
        evidence = f"上游平台清单可识别 {len(platforms)} 个电商平台：" + ("、".join(platforms) if platforms else "无")
        if channels:
            evidence += f"；另有 {len(channels)} 个渠道类型：" + "、".join(channels) + "（不计入平台数）"
        insights.append({
            "feature": "平台覆盖",
            "evidence": evidence + "。",
            "interpretation": "该清单只表示上游出现过的平台，不代表各平台店铺数、销量份额或集中度；未计算 CR2/CR3。",
        })
    elif metrics.get("覆盖平台"):
        coverage = _text(metrics.get("覆盖平台"))
        match = re.match(r"\s*(\d+)", coverage)
        if match and int(match.group(1)) > 0:
            insights.append({
                "feature": "平台覆盖",
                "evidence": f"上游平台清单返回 {coverage}（报告未列出逐项平台名称；海外平台清单计数保留，"
                            "产品画像来源平台和链接推断未计入）。",
                "interpretation": "该计数只表示上游平台清单返回的平台数量，不代表各平台店铺数、销量份额或集中度；未计算 CR2/CR3。",
            })
    profile = core.get("profile_overview") if isinstance(core.get("profile_overview"), dict) else {}
    profile_product = _text(profile.get("国内网店商品数"))
    p_count = _int(metrics.get("网店概况商品数"))
    d_count = _int(domestic_total)
    if profile_product and _same_number(profile_product, p_count) and p_count and d_count:
        insights.append({
            "feature": "店均商品（网店概况口径）",
            "evidence": f"网店概况商品数 {p_count}、国内网店数 {d_count}，同口径店均约 {p_count / d_count:.1f} 件。",
            "interpretation": "该比值仅在国内网店概况的同一产品口径内成立；产品画像的在售商品数、网店总数是其他口径，不能相除。",
        })
    if stores:
        status: Dict[str, int] = {}
        for row in stores:
            state = _text(row.get("状态")) or "待核实"
            status[state] = status.get(state, 0) + 1
        status_text = "、".join(f"{k} {v} 家" for k, v in sorted(status.items(), key=lambda kv: -kv[1]))
        image_total = metrics.get("网店总数")
        if image_total and _int(image_total) != len(stores):
            scope = f"网店画像总数 {image_total} 家与关联网店样本 {len(stores)} 家来自不同产品，不能互推"
        elif image_total:
            scope = f"网店画像总数 {image_total} 家"
        else:
            scope = "上游未返回网店画像总数"
        insights.append({
            "feature": "关联网店状态（当前样本）",
            "evidence": f"当前返回 {len(stores)} 家中：{status_text}。",
            "interpretation": f"状态仅描述本次返回记录；{scope}，不能据此推算全量在营/停业比例。",
        })
    avg = metrics.get("店铺平均评分")
    if avg:
        insights.append({
            "feature": "店铺评分",
            "evidence": f"产品画像返回店铺平均评分 {avg}。",
            "interpretation": "评分为上游平台展示值，满分制与统计口径未说明；不证明商品质量、复购率或转化率。",
        })
    if not insights:
        insights.append({
            "feature": "数据完整性",
            "evidence": "部分维度未返回有效数据。",
            "interpretation": "建议核对匹配关键词是否为企业全称，或检查上游产品覆盖范围；不得把缺失解释为零。",
        })
    return insights


def _build_abstract(report: Dict[str, Any]) -> str:
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    name = _text(subject.get("enterprise")) or _text(subject.get("match_raw")) or "目标企业"
    metrics = [m for m in (report.get("metrics") or []) if isinstance(m, dict)]
    core = report.get("core_analysis") if isinstance(report.get("core_analysis"), dict) else {}
    data_source = report.get("data_source") if isinstance(report.get("data_source"), dict) else {}
    errors = [str(x) for x in (data_source.get("tool_errors") or []) if _text(x)]
    has_body = any(core.get(k) for k in ("profile_overview", "product_overview", "store_table"))
    coverage = next((_text(m.get("value")) for m in metrics if _text(m.get("label")) == "覆盖平台"), "")
    coverage_match = re.match(r"\s*(\d+)", coverage)
    if not has_body:
        if errors:
            return "本次查询未获得有效核心数据，且存在上游调用失败维度：" + "、".join(errors) + "。不据此生成业务规模或市场结论。"
        if coverage_match and int(coverage_match.group(1)) > 0:
            return (f"本报告以“{name}”为分析对象，仅获得上游平台清单计数：覆盖平台 {coverage}"
                    "（报告未列出逐项平台名称）；未返回网店概况、产品画像或关联网店明细，"
                    "不据此生成业务规模或市场结论。")
        return "本次查询未返回有效核心数据；报告仅记录查询边界，不生成业务规模或市场结论。"
    scopes: List[str] = []
    if core.get("profile_overview"):
        scopes.append("网店概况")
    if core.get("product_overview"):
        scopes.append("电商产品画像")
    if core.get("platform_dist"):
        scopes.append("平台覆盖")
    elif coverage_match and int(coverage_match.group(1)) > 0:
        scopes.append("网店概况平台清单计数")
    if core.get("store_table"):
        scopes.append("关联网店当前响应样本")
    scope_text = "、".join(scopes) or "查询边界"
    parts = [f"本报告以“{name}”为分析对象，基于电商平台公开数据，呈现{scope_text}；关联记录不等于查询主体自营店铺。"]
    if metrics:
        parts.append("关键指标包括：" + "、".join(f"{m.get('label')} {m.get('value')}" for m in metrics[:5]) + "。")
    parts.append("报告仅对返回字段作结构化展示；不同产品的商品数、店铺数口径不同，不可直接相除或互相补齐。")
    return "".join(parts)


def _dedupe(items: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in items:
        key = _text(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _has_review_body(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def _refresh_quality_report(report: Dict[str, Any]) -> None:
    """Recompute section-fill stats from the final sections and bodies.

    0 counts as populated; only None and empty containers/strings are empty.
    coverage_pct is section fill rate, never an accuracy claim.
    """
    core = report.get("core_analysis") if isinstance(report.get("core_analysis"), dict) else {}
    sections = core.get("sections") if isinstance(core.get("sections"), list) else []
    total = len([s for s in sections if isinstance(s, dict)])
    populated = 0
    for section in sections:
        if not isinstance(section, dict):
            continue
        key = section.get("key")
        if key and _has_review_body(core.get(key)):
            populated += 1
    data_source = report.get("data_source")
    if not isinstance(data_source, dict):
        data_source = {}
        report["data_source"] = data_source
    quality = data_source.get("quality_report")
    if not isinstance(quality, dict):
        quality = {}
        data_source["quality_report"] = quality
    quality.update({
        "total_sections": total,
        "populated_sections": populated,
        "empty_sections": total - populated,
        "coverage_pct": round(populated / total * 100) if total else 0,
    })


def apply_content_review(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a reviewed deep copy of a frozen estore report."""
    reviewed = copy.deepcopy(dict(report))
    subject = reviewed.get("subject") if isinstance(reviewed.get("subject"), dict) else {}
    data_source = reviewed.get("data_source") if isinstance(reviewed.get("data_source"), dict) else {}
    if subject.get("blocked_reason") or data_source.get("blocked_reason"):
        # The blocked branch never queried the products; keep its explicit
        # no-conclusion wording instead of replacing it with a data abstract.
        _refresh_quality_report(reviewed)
        return reviewed
    _fix_caliber(reviewed)
    core = reviewed.get("core_analysis") if isinstance(reviewed.get("core_analysis"), dict) else {}
    platforms, channels, has_platform_field = _fix_profile(core)
    _fix_product(core)
    _fix_platform_section(core, platforms, channels, has_platform_field)
    stores = _fix_store_rows(core)
    _fix_records(reviewed, stores)
    _fix_metrics(reviewed, core, platforms, has_platform_field)
    insights = _build_insights(reviewed, core, stores, platforms, channels)
    reviewed["insights"] = insights
    prefix = [x for x in (report.get("executive_summary") or []) if _text(x).startswith(("主体解析受阻", "数据缺口"))]
    reviewed["executive_summary"] = prefix + _dedupe([i.get("interpretation") for i in insights])[:5]
    reviewed["abstract"] = _build_abstract(reviewed)
    reviewed["summary"] = reviewed["abstract"]
    _refresh_quality_report(reviewed)
    return reviewed


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply offline content review to an estore report.json")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    input_path = pathlib.Path(args.input).expanduser().resolve()
    output_path = pathlib.Path(args.out_dir).expanduser()
    target = (output_path / "report.json").resolve()
    same = target == input_path
    if not same and target.exists():
        try:
            same = target.samefile(input_path)
        except OSError:
            same = False
    if same:
        raise SystemExit("拒绝写入：--out-dir 的 report.json 指向 --input，冻结源报告不可覆盖")
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from render_report import render_html, render_markdown

    source = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
    reviewed = apply_content_review(source)
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(reviewed, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(reviewed), encoding="utf-8")
    (out / "report.html").write_text(render_html(reviewed), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
