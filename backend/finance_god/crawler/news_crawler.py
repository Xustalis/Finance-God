"""A股行业资讯爬虫。

数据源（公开 JSON API，无需登录）：
- 东方财富 np-listapi：财经要闻（实时滚动）
- 东方财富 reportapi：行业研报 & 个股研报（券商专业分析）
- 同花顺 dq API：热股动态（辅助行业关联）
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from .models import IndustryNews

_LOGGER = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")

# ─── 端点 ───────────────────────────────────────────────────────────────
_EASTMONEY_NEWS_URL = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
_EASTMONEY_REPORT_URL = "https://reportapi.eastmoney.com/report/list"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}
_TRACKING_QUERY_KEYS = frozenset(
    {"from", "spm", "source", "src", "track", "tracking_id"}
)


class NewsSourcesUnavailable(RuntimeError):
    """All configured public-news sources failed."""

# 东方财富行业板块代码映射
SECTOR_CODES: dict[str, str] = {
    "银行": "BK0475",
    "医药生物": "BK0465",
    "电子": "BK0448",
    "计算机": "BK0447",
    "食品饮料": "BK0438",
    "电力设备": "BK0481",
    "汽车": "BK0481",
    "房地产": "BK0451",
    "有色金属": "BK0478",
    "机械设备": "BK0459",
    "通信": "BK0446",
    "传媒": "BK0444",
    "国防军工": "BK0471",
    "石油石化": "BK0473",
    "农林牧渔": "BK0437",
}


# ─── 主入口 ─────────────────────────────────────────────────────────────


async def fetch_industry_news(
    *,
    sector: str = "",
    limit: int = 30,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[IndustryNews]:
    """从东方财富获取行业资讯（要闻 + 行业研报）。

    Args:
        sector: 行业板块名称（为空则获取综合）
        limit: 返回条数上限
        timeout: 请求超时(秒)

    Returns:
        IndustryNews 列表，按时间倒序
    """
    news_list: list[IndustryNews] = []

    # 并发获取多个数据源
    import asyncio

    tasks = [
        _fetch_general_news(
            limit=min(limit, 20), timeout=timeout, transport=transport
        ),
        _fetch_industry_reports(
            sector=sector,
            limit=min(limit, 15),
            timeout=timeout,
            transport=transport,
        ),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    failures: list[str] = []
    completed_sources = 0
    for result in results:
        if isinstance(result, list):
            completed_sources += 1
            news_list.extend(result)
        elif isinstance(result, Exception):
            _LOGGER.warning("数据源获取异常: %s", result)
            failures.append(f"{type(result).__name__}: {result}")

    if completed_sources == 0:
        detail = "; ".join(failures) or "no crawler source completed"
        raise NewsSourcesUnavailable(f"all public-news sources failed: {detail}")

    # 规范 URL + 标题作为身份，避免追踪参数和空白差异制造重复。
    seen_items: set[tuple[str, str]] = set()
    unique_news: list[IndustryNews] = []
    for item in news_list:
        identity = news_identity(url=item.url, title=item.title)
        if identity in seen_items:
            continue
        seen_items.add(identity)
        unique_news.append(item)

    unique_news.sort(
        key=lambda x: x.publish_time or datetime.min.replace(tzinfo=_CST),
        reverse=True,
    )
    return unique_news[:limit]


# ─── 东方财富财经要闻 ────────────────────────────────────────────────────


async def _fetch_general_news(
    *,
    limit: int = 20,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[IndustryNews]:
    """获取东方财富综合财经要闻。"""
    params = {
        "client": "web",
        "biz": "web_news_col",
        "column": "350",  # 财经要闻栏目
        "order": "1",
        "needInteractData": "0",
        "page_index": "1",
        "page_size": str(min(limit, 50)),
        "req_trace": "1",
    }

    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=timeout, transport=transport
    ) as client:
        resp = await client.get(_EASTMONEY_NEWS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    news_list: list[IndustryNews] = []
    items = data.get("data", {}).get("list", []) if data.get("data") else []

    for item in items[:limit]:
        publish_time = _parse_time(item.get("showTime", ""))
        # API 返回字段: summary 或 digest
        summary = (
            item.get("summary", "")
            or item.get("digest", "")
            or ""
        ).strip()
        media = item.get("mediaName", "")
        source_label = f"东方财富/{media}" if media else "东方财富"

        news_list.append(
            IndustryNews(
                title=item.get("title", "").strip(),
                summary=summary,
                source=source_label,
                url=item.get("url", "")
                or item.get("uniqueUrl", ""),
                publish_time=publish_time,
                sector="综合",
                tags=[media] if media else [],
            )
        )

    return news_list


# ─── 东方财富行业研报 ────────────────────────────────────────────────────


async def _fetch_industry_reports(
    *,
    sector: str = "",
    limit: int = 15,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[IndustryNews]:
    """获取东方财富行业研报（券商分析师研究报告）。

    包括行业研报 (qType=1) 和个股研报 (qType=0) 两类。
    """
    today = datetime.now(tz=_CST)
    begin_date = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    news_list: list[IndustryNews] = []

    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=timeout, transport=transport
    ) as client:
            # 行业研报
            params_industry = {
                "industryCode": "*",
                "pageSize": str(min(limit, 20)),
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": begin_date,
                "endTime": end_date,
                "pageNo": "1",
                "fields": "",
                "qType": "1",
            }
            resp1 = await client.get(
                _EASTMONEY_REPORT_URL, params=params_industry
            )
            resp1.raise_for_status()
            data1 = resp1.json()

            for item in (data1.get("data") or [])[:limit]:
                news_list.append(_report_to_news(item, report_type="行业研报"))

            # 个股研报（补充）
            params_stock = {**params_industry, "qType": "0", "pageSize": "10"}
            resp2 = await client.get(
                _EASTMONEY_REPORT_URL, params=params_stock
            )
            resp2.raise_for_status()
            data2 = resp2.json()

            for item in (data2.get("data") or [])[:8]:
                news_list.append(_report_to_news(item, report_type="个股研报"))

    return news_list


def _report_to_news(item: dict[str, Any], *, report_type: str) -> IndustryNews:
    """将研报数据转换为统一 IndustryNews 模型。"""
    org = item.get("orgSName", "")
    industry = item.get("industryName", "") or item.get("indvInduName", "")
    stock_name = item.get("stockName", "")
    rating = item.get("emRatingName", "")
    info_code = item.get("infoCode", "")

    # 构建摘要
    summary_parts: list[str] = []
    if org:
        summary_parts.append(f"机构: {org}")
    if rating:
        summary_parts.append(f"评级: {rating}")
    if stock_name:
        summary_parts.append(f"标的: {stock_name}")
    if industry:
        summary_parts.append(f"行业: {industry}")
    summary = " | ".join(summary_parts)

    # 构建链接
    url = f"https://data.eastmoney.com/report/info/{info_code}.html" if info_code else ""

    publish_time = _parse_time(
        (item.get("publishDate") or "")[:19]
    )

    tags = [t for t in [report_type, industry, org] if t]

    return IndustryNews(
        title=item.get("title", "").strip(),
        summary=summary,
        source=f"东方财富研报/{org}" if org else "东方财富研报",
        url=url,
        publish_time=publish_time,
        sector=industry or "综合",
        tags=tags[:5],
    )


# ─── 工具函数 ────────────────────────────────────────────────────────────


def _parse_time(time_str: str) -> datetime | None:
    """解析各种时间格式。"""
    if not time_str:
        return None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%m月%d日 %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt.replace(tzinfo=_CST)
        except ValueError:
            continue
    return None


def _extract_tags(item: dict[str, Any]) -> list[str]:
    """从东方财富资讯条目中提取标签。"""
    tags: list[str] = []
    if item.get("columns"):
        for col in item["columns"]:
            if col.get("column_name"):
                tags.append(col["column_name"])
    return tags[:5]


def _normalize_title(title: str) -> str:
    """Normalize whitespace/case for deterministic duplicate identity."""

    return re.sub(r"\s+", " ", title).strip().casefold()


def _normalize_url(url: str) -> str:
    """Return a stable URL identity without fragments or tracking parameters."""

    raw = url.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            urlencode(sorted(filtered_query)),
            "",
        )
    )


def news_identity(*, url: str, title: str) -> tuple[str, str]:
    """Return the normalized identity shared by deduplication and public IDs."""

    return (_normalize_url(url), _normalize_title(title))


def news_item_id(*, url: str, title: str) -> str:
    """Build a stable public identifier from the crawler deduplication key."""

    normalized_url, normalized_title = news_identity(url=url, title=title)
    value = f"{normalized_url}\n{normalized_title}"
    return sha256(value.encode("utf-8")).hexdigest()
