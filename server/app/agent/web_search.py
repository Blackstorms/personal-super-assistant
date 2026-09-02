"""
联网搜索（对齐 DeerFlow web_search 边界，自写实现）。

优先：配置了 PSA_WEB_SEARCH_API_KEY 时走 Syncotech 等 HTTP 搜索 API；
否则免 Key 级联 DuckDuckGo → Bing；亦可 Tavily。
默认不走系统代理（PSA_WEB_SEARCH_TRUST_ENV=1 可恢复）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5
DEFAULT_REGION = "wt-wt"
DEFAULT_SAFESEARCH = "moderate"
DEFAULT_BACKEND = "duckduckgo"

DEFAULT_API_URL = "https://ogw.syncotechai.com/websearch/search"

# 单后端超时 / 整次搜索总超时
BACKEND_TIMEOUT_SEC = float(os.environ.get("PSA_WEB_SEARCH_BACKEND_TIMEOUT", "6"))
API_TIMEOUT_SEC = float(os.environ.get("PSA_WEB_SEARCH_API_TIMEOUT", "20"))
SEARCH_TIMEOUT_SEC = float(os.environ.get("PSA_WEB_SEARCH_TIMEOUT", "25"))
TRUST_ENV = (os.environ.get("PSA_WEB_SEARCH_TRUST_ENV") or "").strip() in {"1", "true", "yes"}

WEB_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "检索公开网页，获取时事、新闻、事实与链接。"
            "问题时效性强，或本地知识/文件不足时使用。"
            "返回每条结果的标题、url 与摘要。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词；尽量具体以便命中",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"最多返回条数（默认 {DEFAULT_MAX_RESULTS}，上限 10）",
                },
            },
            "required": ["query"],
        },
    },
}


def _api_key() -> str:
    return (os.environ.get("PSA_WEB_SEARCH_API_KEY") or "").strip()


def _api_url() -> str:
    return (os.environ.get("PSA_WEB_SEARCH_API_URL") or DEFAULT_API_URL).strip() or DEFAULT_API_URL


def resolve_provider() -> str:
    raw = (os.environ.get("PSA_WEB_SEARCH_PROVIDER") or "auto").strip().lower()
    if raw in {"ddg", "duckduckgo"}:
        return "ddg"
    if raw in {"bing"}:
        return "bing"
    if raw in {"api", "syncotech", "ogw"}:
        return "api"
    if raw == "tavily":
        return "tavily"
    if _api_key():
        return "api"
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    return "auto"


def _normalize_max_results(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_MAX_RESULTS
    return max(1, min(n, 10))


def _http_timeout(seconds: float | None = None) -> httpx.Timeout:
    sec = seconds if seconds is not None else BACKEND_TIMEOUT_SEC
    connect = min(4.0, sec)
    return httpx.Timeout(sec, connect=connect)


def _http_client(timeout: httpx.Timeout | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=timeout or _http_timeout(),
        follow_redirects=True,
        trust_env=TRUST_ENV,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )


def _ddg_via_library(query: str, max_results: int) -> list[dict[str, str]] | None:
    try:
        from ddgs import DDGS
    except ImportError:
        return None

    region = os.environ.get("PSA_WEB_SEARCH_REGION") or DEFAULT_REGION
    safesearch = os.environ.get("PSA_WEB_SEARCH_SAFESEARCH") or DEFAULT_SAFESEARCH
    backend = os.environ.get("PSA_WEB_SEARCH_BACKEND") or DEFAULT_BACKEND
    timeout = max(3, int(BACKEND_TIMEOUT_SEC))

    # ddgs 会读代理环境变量；与 httpx 对齐，默认屏蔽坏代理
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    saved = {k: os.environ.pop(k) for k in proxy_keys if k in os.environ} if not TRUST_ENV else {}
    try:
        ddgs = DDGS(timeout=timeout)
        raw = ddgs.text(
            query,
            region=region,
            safesearch=safesearch,
            max_results=max_results,
            backend=backend,
        )
    finally:
        os.environ.update(saved)

    out: list[dict[str, str]] = []
    for r in raw or []:
        out.append(
            {
                "title": str(r.get("title") or ""),
                "url": str(r.get("href") or r.get("link") or ""),
                "content": str(r.get("body") or r.get("snippet") or ""),
            }
        )
    return out


def _unwrap_ddg_href(href: str) -> str:
    """DuckDuckGo 结果常包一层 /l/?uddg= 跳转链接。"""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    return href


_TAG_RE = re.compile(r"<[^>]+>")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+rel="nofollow"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<td[^>]*class="result-snippet"[^>]*>(?P<snippet>.*?)</td>)?',
    re.I | re.S,
)
_DDG_LITE_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*class="[^"]*result-link[^"]*"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(?P<snippet>.*?)</td>)?',
    re.I | re.S,
)
_BING_ALGO_RE = re.compile(
    r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>'
    r'.*?<h2[^>]*>\s*<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<p[^>]*>(?P<snippet>.*?)</p>)?',
    re.I | re.S,
)


def _strip_html(text: str) -> str:
    return unescape(_TAG_RE.sub("", text or "")).strip()


def _ddg_html_search(query: str, max_results: int) -> list[dict[str, str]]:
    """DuckDuckGo HTML / lite 双入口。"""
    urls = (
        "https://html.duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    )
    last_err: Exception | None = None
    with _http_client() as client:
        for url in urls:
            try:
                resp = client.get(url, params={"q": query})
                resp.raise_for_status()
                html = resp.text
                pattern = _DDG_LITE_RE if "lite.duckduckgo" in url else _DDG_RESULT_RE
                out: list[dict[str, str]] = []
                for m in pattern.finditer(html):
                    link = _unwrap_ddg_href(m.group("href"))
                    title = _strip_html(m.group("title"))
                    snippet = _strip_html(m.group("snippet") or "")
                    if not link or not title:
                        continue
                    if "duckduckgo.com" in urlparse(link).netloc:
                        continue
                    out.append({"title": title, "url": link, "content": snippet})
                    if len(out) >= max_results:
                        break
                if out:
                    return out
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.info("ddg html %s failed: %s", url, e)
    if last_err:
        raise last_err
    return []


def _bing_html_search(query: str, max_results: int) -> list[dict[str, str]]:
    """Bing 网页结果解析（国内可达性通常优于 DDG）。"""
    with _http_client() as client:
        resp = client.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-CN", "mkt": "zh-CN"},
        )
        resp.raise_for_status()
        html = resp.text

    out: list[dict[str, str]] = []
    for m in _BING_ALGO_RE.finditer(html):
        link = m.group("href")
        title = _strip_html(m.group("title"))
        snippet = _strip_html(m.group("snippet") or "")
        if not link or not title or link.startswith("javascript:"):
            continue
        out.append({"title": title, "url": link, "content": snippet})
        if len(out) >= max_results:
            break
    if not out:
        # 宽松兜底：抓取结果区标题链接
        loose = re.findall(
            r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.I | re.S,
        )
        for href, title_html in loose:
            if "bing.com" in href or "microsoft.com" in href:
                continue
            title = _strip_html(title_html)
            if not title:
                continue
            out.append({"title": title, "url": href, "content": ""})
            if len(out) >= max_results:
                break
    return out


def _tavily_search(query: str, max_results: int) -> list[dict[str, str]]:
    api_key = os.environ.get("TAVILY_API_KEY") or ""
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required when PSA_WEB_SEARCH_PROVIDER=tavily")

    with _http_client(_http_timeout(BACKEND_TIMEOUT_SEC + 2)) as client:
        resp = client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    out: list[dict[str, str]] = []
    for r in data.get("results") or []:
        out.append(
            {
                "title": str(r.get("title") or ""),
                "url": str(r.get("url") or ""),
                "content": str(r.get("content") or r.get("snippet") or ""),
            }
        )
    return out


def _api_search(query: str, max_results: int) -> list[dict[str, str]]:
    """Syncotech / 兼容 HTTP 搜索 API：POST JSON 数组，字段 queyContext（接口拼写）。"""
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("PSA_WEB_SEARCH_API_KEY is required for API web search")

    url = _api_url()
    # 接口约定字段名为 queyContext（非 queryContext）
    payload = [{"queyContext": query}]
    with _http_client(_http_timeout(API_TIMEOUT_SEC)) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()

    if isinstance(body, dict) and body.get("code") not in (0, "0", None):
        raise RuntimeError(f"search api error code={body.get('code')} msg={body.get('msg')}")

    data = body.get("data") if isinstance(body, dict) else body
    pages: list[Any] = []
    if isinstance(data, dict):
        pages = data.get("webPageList") or data.get("results") or data.get("items") or []
    elif isinstance(data, list):
        pages = data

    out: list[dict[str, str]] = []
    for r in pages:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "")
        link = str(r.get("url") or r.get("link") or "")
        content = str(
            r.get("content")
            or r.get("markDownContent")
            or r.get("snippet")
            or r.get("summary")
            or ""
        )
        if not title and not link and not content:
            continue
        # 附带站点与时间，便于模型引用
        host = str(r.get("hostname") or r.get("siteName") or "")
        published = str(r.get("publishedDate") or "")
        meta_bits = [x for x in (host, published) if x]
        if meta_bits and content:
            content = f"[{' · '.join(meta_bits)}]\n{content}"
        out.append({"title": title or link, "url": link, "content": content[:4000]})
        if len(out) >= max_results:
            break
    return out


def _try_backend(name: str, fn, query: str, max_results: int) -> list[dict[str, str]]:
    try:
        rows = fn(query, max_results)
        if rows:
            logger.info("web_search ok via %s (%d hits)", name, len(rows))
            return rows
        logger.info("web_search %s returned empty", name)
    except Exception as e:  # noqa: BLE001
        logger.warning("web_search backend %s failed: %s", name, e)
    return []


def _ddg_search(query: str, max_results: int) -> list[dict[str, str]]:
    rows = _try_backend("ddgs", lambda q, n: _ddg_via_library(q, n) or [], query, max_results)
    if rows:
        return rows
    return _try_backend("ddg-html", _ddg_html_search, query, max_results)


def _run_search(provider: str, query: str, max_results: int) -> tuple[list[dict[str, str]], str]:
    """返回 (results, used_provider)。"""
    if provider == "api":
        return _api_search(query, max_results), "api"
    if provider == "tavily":
        return _tavily_search(query, max_results), "tavily"
    if provider == "bing":
        rows = _bing_html_search(query, max_results)
        return rows, "bing"
    if provider == "ddg":
        rows = _ddg_search(query, max_results)
        return rows, "ddg"

    # auto：API Key → Tavily → Bing → DDG
    # 国内 DDG 常超时/被拦，Bing 靠前以免吃掉整次 SEARCH_TIMEOUT
    if _api_key():
        rows = _try_backend("api", _api_search, query, max_results)
        if rows:
            return rows, "api"

    if os.environ.get("TAVILY_API_KEY"):
        rows = _try_backend("tavily", _tavily_search, query, max_results)
        if rows:
            return rows, "tavily"

    rows = _try_backend("bing", _bing_html_search, query, max_results)
    if rows:
        return rows, "bing"

    rows = _ddg_search(query, max_results)
    if rows:
        return rows, "ddg"

    raise RuntimeError(
        "all search backends failed. "
        "Configure search API key in Settings or set PSA_WEB_SEARCH_API_KEY / TAVILY_API_KEY."
    )


async def handle_web_search(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """执行联网搜索，返回统一结构（供 tool_router 序列化）。"""
    args = arguments or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required", "query": "", "results": [], "total_results": 0}

    max_results = _normalize_max_results(args.get("max_results") or DEFAULT_MAX_RESULTS)
    provider = resolve_provider()

    try:
        results, used = await asyncio.wait_for(
            asyncio.to_thread(_run_search, provider, query, max_results),
            timeout=SEARCH_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.warning("web_search timed out (provider=%s, %.0fs)", provider, SEARCH_TIMEOUT_SEC)
        return {
            "error": (
                f"search timed out after {SEARCH_TIMEOUT_SEC:.0f}s; "
                "configure search API in Settings, or check network/proxy"
            ),
            "provider": provider,
            "query": query,
            "results": [],
            "total_results": 0,
            "hint": f"https://www.bing.com/search?q={quote(query)}",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("web_search failed (%s): %s", provider, e)
        return {
            "error": str(e),
            "provider": provider,
            "query": query,
            "results": [],
            "total_results": 0,
            "hint": f"https://www.bing.com/search?q={quote(query)}",
        }

    if not results:
        return {
            "error": "No results found",
            "provider": provider,
            "query": query,
            "results": [],
            "total_results": 0,
            "hint": f"https://www.bing.com/search?q={quote(query)}",
        }

    return {
        "provider": used,
        "query": query,
        "total_results": len(results),
        "results": results,
    }
