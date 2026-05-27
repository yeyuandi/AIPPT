# -*- coding: utf-8 -*-
"""
DuckDuckGo 搜索工具封装（``duckduckgo_search.DDGS``）。

依赖：``pip install ddgs``（旧包名 ``duckduckgo-search`` 仍可作为回退）。

本地测试::

    python -m aippt.search.duckduckgo_tools --list-params
    python -m aippt.search.duckduckgo_tools text -k "大语言模型" -n 5 --region cn-zh
    python -m aippt.search.duckduckgo_tools news -k "人工智能" -n 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# 参数目录（与 duckduckgo_search DDGS / text / images / news / videos 对齐）
# ---------------------------------------------------------------------------

class DdgsParamSpec(TypedDict):
    """单条参数说明。"""

    group: str
    name: str
    type_hint: str
    default: str
    description: str


DDGS_PARAMETER_CATALOG: list[DdgsParamSpec] = [
    {
        "group": "DDGS.__init__",
        "name": "headers",
        "type_hint": "dict | None",
        "default": "None",
        "description": "HTTP 客户端自定义请求头。",
    },
    {
        "group": "DDGS.__init__",
        "name": "proxy",
        "type_hint": "str | None",
        "default": "None",
        "description": "代理 URL，支持 http/https/socks5；可用环境变量 DDGS_PROXY；别名 tb = Tor socks5://127.0.0.1:9150。",
    },
    {
        "group": "DDGS.__init__",
        "name": "timeout",
        "type_hint": "int",
        "default": "10",
        "description": "HTTP 请求超时（秒）。",
    },
    {
        "group": "DDGS.__init__",
        "name": "verify",
        "type_hint": "bool",
        "default": "True",
        "description": "是否校验 SSL 证书。",
    },
    {
        "group": "DDGS.text",
        "name": "keywords",
        "type_hint": "str",
        "default": "（必填）",
        "description": "检索关键词；支持 DuckDuckGo 运算符（filetype:、site:、intitle: 等）。",
    },
    {
        "group": "DDGS.text",
        "name": "region",
        "type_hint": "str | None",
        "default": "None",
        "description": "区域，如 cn-zh、us-en、wt-wt（无区域）。",
    },
    {
        "group": "DDGS.text",
        "name": "safesearch",
        "type_hint": "str",
        "default": "moderate",
        "description": "安全搜索：on / moderate / off。",
    },
    {
        "group": "DDGS.text",
        "name": "timelimit",
        "type_hint": "str | None",
        "default": "None",
        "description": "时间范围：d（天）、w（周）、m（月）、y（年）。",
    },
    {
        "group": "DDGS.text",
        "name": "backend",
        "type_hint": "str",
        "default": "auto",
        "description": "后端：auto、html、lite、bing 等。",
    },
    {
        "group": "DDGS.text",
        "name": "max_results",
        "type_hint": "int | None",
        "default": "None",
        "description": "最大结果条数。",
    },
    {
        "group": "DDGS.images",
        "name": "keywords",
        "type_hint": "str",
        "default": "（必填）",
        "description": "图片检索关键词。",
    },
    {
        "group": "DDGS.images",
        "name": "region",
        "type_hint": "str",
        "default": "us-en",
        "description": "区域代码。",
    },
    {
        "group": "DDGS.images",
        "name": "safesearch",
        "type_hint": "str",
        "default": "moderate",
        "description": "on / moderate / off。",
    },
    {
        "group": "DDGS.images",
        "name": "timelimit",
        "type_hint": "str | None",
        "default": "None",
        "description": "Day / Week / Month / Year。",
    },
    {
        "group": "DDGS.images",
        "name": "size",
        "type_hint": "str | None",
        "default": "None",
        "description": "Small / Medium / Large / Wallpaper。",
    },
    {
        "group": "DDGS.images",
        "name": "color",
        "type_hint": "str | None",
        "default": "None",
        "description": "Monochrome、Red、Blue 等。",
    },
    {
        "group": "DDGS.images",
        "name": "type_image",
        "type_hint": "str | None",
        "default": "None",
        "description": "photo / clipart / gif / transparent / line。",
    },
    {
        "group": "DDGS.images",
        "name": "layout",
        "type_hint": "str | None",
        "default": "None",
        "description": "Square / Tall / Wide。",
    },
    {
        "group": "DDGS.images",
        "name": "license_image",
        "type_hint": "str | None",
        "default": "None",
        "description": "Public / Share / Modify 等版权筛选。",
    },
    {
        "group": "DDGS.images",
        "name": "max_results",
        "type_hint": "int | None",
        "default": "None",
        "description": "最大结果条数。",
    },
    {
        "group": "DDGS.videos",
        "name": "keywords",
        "type_hint": "str",
        "default": "（必填）",
        "description": "视频检索关键词。",
    },
    {
        "group": "DDGS.videos",
        "name": "region",
        "type_hint": "str",
        "default": "us-en",
        "description": "区域代码。",
    },
    {
        "group": "DDGS.videos",
        "name": "safesearch",
        "type_hint": "str",
        "default": "moderate",
        "description": "on / moderate / off。",
    },
    {
        "group": "DDGS.videos",
        "name": "timelimit",
        "type_hint": "str | None",
        "default": "None",
        "description": "d / w / m。",
    },
    {
        "group": "DDGS.videos",
        "name": "resolution",
        "type_hint": "str | None",
        "default": "None",
        "description": "high / standart。",
    },
    {
        "group": "DDGS.videos",
        "name": "duration",
        "type_hint": "str | None",
        "default": "None",
        "description": "short / medium / long。",
    },
    {
        "group": "DDGS.videos",
        "name": "license_videos",
        "type_hint": "str | None",
        "default": "None",
        "description": "creativeCommon / youtube。",
    },
    {
        "group": "DDGS.videos",
        "name": "max_results",
        "type_hint": "int | None",
        "default": "None",
        "description": "最大结果条数。",
    },
    {
        "group": "DDGS.news",
        "name": "keywords",
        "type_hint": "str",
        "default": "（必填）",
        "description": "新闻检索关键词。",
    },
    {
        "group": "DDGS.news",
        "name": "region",
        "type_hint": "str",
        "default": "us-en",
        "description": "区域代码。",
    },
    {
        "group": "DDGS.news",
        "name": "safesearch",
        "type_hint": "str",
        "default": "moderate",
        "description": "on / moderate / off。",
    },
    {
        "group": "DDGS.news",
        "name": "timelimit",
        "type_hint": "str | None",
        "default": "None",
        "description": "d / w / m。",
    },
    {
        "group": "DDGS.news",
        "name": "max_results",
        "type_hint": "int | None",
        "default": "None",
        "description": "最大结果条数。",
    },
    {
        "group": "DDGS.news",
        "name": "backend",
        "type_hint": "str",
        "default": "duckduckgo,bing",
        "description": "新闻后端，逗号分隔；避免 auto（会并行请求 Yahoo 易超时）。",
    },
    {
        "group": "DDGS.news",
        "name": "fallback_text",
        "type_hint": "bool",
        "default": "True",
        "description": "专用新闻后端无结果时，回退为 text 检索并映射为新闻字段。",
    },
]


def format_parameter_catalog_text() -> str:
    """
    将 ``DDGS_PARAMETER_CATALOG`` 格式化为可读文本。

    @returns 多行说明
    """
    lines: list[str] = ["duckduckgo-search / DDGS 参数一览", "=" * 72, ""]
    current = ""
    for spec in DDGS_PARAMETER_CATALOG:
        if spec["group"] != current:
            current = spec["group"]
            lines.append(f"[{current}]")
        lines.append(f"  {spec['name']}")
        lines.append(f"    类型: {spec['type_hint']}")
        lines.append(f"    默认: {spec['default']}")
        lines.append(f"    说明: {spec['description']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _load_ddgs_class() -> tuple[type, str]:
    """
    导入 ``DDGS`` 类（``ddgs`` 优先，``duckduckgo_search`` 回退）。

    @returns (DDGS 类, 包名)
    @raises ImportError - 均未安装
    """
    try:
        from ddgs import DDGS

        return DDGS, "ddgs"
    except ImportError:
        from duckduckgo_search import DDGS

        return DDGS, "duckduckgo_search"


def _resolve_proxy(proxy: Optional[str]) -> Optional[str]:
    """
    解析代理：显式参数优先，否则 ``DDGS_PROXY`` 环境变量。

    @param proxy - CLI / 构造参数
    @returns 代理 URL 或 None
    """
    if proxy:
        return proxy
    return os.environ.get("DDGS_PROXY") or None


def _format_search_error(err: BaseException, *, proxy: Optional[str]) -> str:
    """
    将检索异常格式化为可读提示（含代理/超时排查）。

    @param err - 原始异常
    @param proxy - 当前是否配置了代理
    @returns 多行说明
    """
    msg = str(err).strip() or err.__class__.__name__
    lines = [f"检索失败: {msg}"]
    lowered = msg.lower()
    proxy_refused = (
        "10061" in msg
        or "connection refused" in lowered
        or "积极拒绝" in msg
        or "tunnel error" in lowered
    )
    if proxy_refused and proxy:
        lines.append("")
        lines.append(f"代理 {proxy} 无法连接（端口未监听或地址错误）。")
        lines.append("建议：")
        lines.append("  1. 确认 Clash / V2Ray 等已启动，并查看「本地 HTTP 端口」")
        lines.append("  2. 去掉 --proxy 与 DDGS_PROXY 后重试（若网络可直连）")
        lines.append("  3. 换正确端口，例如 --proxy http://127.0.0.1:7897")
    elif "timeout" in lowered or "timed out" in lowered:
        lines.append("")
        lines.append("可能原因：无法直连 DuckDuckGo / 检索后端（常见于未开代理或防火墙拦截）。")
        if not proxy:
            lines.append("建议：配置代理后重试，例如：")
            lines.append('  set DDGS_PROXY=http://127.0.0.1:7890')
            lines.append('  python -m aippt.search.duckduckgo_tools news -k "关键词" --proxy http://127.0.0.1:7890')
        else:
            lines.append(f"当前已配置代理: {proxy}")
            lines.append("建议：确认代理可用，或增大 --timeout（如 30）。")
    return "\n".join(lines)


def _normalize_news_region(region: str) -> str:
    """
    新闻后端对 ``wt-wt`` 等区域支持不佳，映射为可用代码。

    @param region - 原始区域
    @returns 规范化后的区域
    """
    if region == "wt-wt":
        return "cn-zh"
    return region


def _map_text_results_as_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    将 text 检索结果映射为 news 字段结构。

    @param items - text 结果
    @returns 含 title / url / body 等字段的列表
    """
    mapped: list[dict[str, Any]] = []
    for item in items:
        mapped.append(
            {
                "title": item.get("title", ""),
                "url": item.get("href") or item.get("url", ""),
                "body": item.get("body", ""),
                "date": item.get("date", ""),
                "source": item.get("source", ""),
                "image": item.get("image", ""),
            }
        )
    return mapped


def _is_retriable_news_error(err: BaseException) -> bool:
    """
    判断新闻后端错误是否可尝试下一后端或 text 回退。

    @param err - 异常
    @returns 是否可继续
    """
    msg = str(err).lower()
    if "no results found" in msg:
        return True
    if "timeout" in msg or "timed out" in msg:
        return True
    if "connecterror" in msg or "connect error" in msg:
        return True
    return False


def _resolve_news_backends(backend: str) -> list[str]:
    """
    解析新闻后端列表；``auto`` 会并行请求 Yahoo，改为顺序尝试 DuckDuckGo / Bing。

    @param backend - 后端配置
    @returns 后端名称列表
    """
    normalized = backend.strip().lower()
    if normalized in ("auto", "all", ""):
        return ["duckduckgo", "bing"]
    return [part.strip() for part in backend.split(",") if part.strip()]


@dataclass
class DuckDuckGoClientOptions:
    """
    ``DDGS`` 客户端构造选项。

    @ivar proxy - HTTP(S)/SOCKS 代理
    @ivar timeout - 超时秒数
    @ivar verify - SSL 校验
    @ivar headers - 自定义请求头
    """

    proxy: Optional[str] = None
    timeout: int = 10
    verify: bool = True
    headers: Optional[dict[str, str]] = None


class DuckDuckGoSearchTool:
    """
    DuckDuckGo 检索工具类：文本 / 图片 / 视频 / 新闻。
    """

    def __init__(self, options: DuckDuckGoClientOptions | None = None) -> None:
        """
        @param options - 客户端选项；None 为默认
        """
        opts = options or DuckDuckGoClientOptions()
        opts.proxy = _resolve_proxy(opts.proxy)
        self.options = opts
        self._ddgs_cls, self._ddgs_package = _load_ddgs_class()

    def _client(self):
        """@returns 新的 DDGS 实例（建议每次检索单独实例，避免限流）。"""
        opts = self.options
        kwargs: dict[str, Any] = {
            "timeout": opts.timeout,
            "verify": opts.verify,
        }
        if opts.proxy is not None:
            kwargs["proxy"] = opts.proxy
        if opts.headers is not None and self._ddgs_package == "duckduckgo_search":
            kwargs["headers"] = opts.headers
        return self._ddgs_cls(**kwargs)

    def search_text(
        self,
        keywords: str,
        *,
        region: str | None = None,
        safesearch: Literal["on", "moderate", "off"] = "moderate",
        timelimit: Literal["d", "w", "m", "y"] | None = None,
        backend: str = "auto",
        max_results: int | None = 10,
    ) -> list[dict[str, Any]]:
        """
        网页文本检索。

        @param keywords - 关键词
        @param region - 区域，如 cn-zh
        @param safesearch - 安全搜索级别
        @param timelimit - 时间范围
        @param backend - 检索后端
        @param max_results - 条数上限
        @returns 结果列表（title / href / body 等）
        """
        with self._client() as ddgs:
            return list(
                ddgs.text(
                    keywords,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    backend=backend,
                    max_results=max_results,
                )
            )

    def search_images(
        self,
        keywords: str,
        *,
        region: str = "wt-wt",
        safesearch: Literal["on", "moderate", "off"] = "moderate",
        timelimit: str | None = None,
        size: str | None = None,
        color: str | None = None,
        type_image: str | None = None,
        layout: str | None = None,
        license_image: str | None = None,
        max_results: int | None = 10,
    ) -> list[dict[str, Any]]:
        """
        图片检索。

        @param keywords - 关键词
        @returns 结果列表（title / image / thumbnail / url 等）
        """
        with self._client() as ddgs:
            return list(
                ddgs.images(
                    keywords,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    size=size,
                    color=color,
                    type_image=type_image,
                    layout=layout,
                    license_image=license_image,
                    max_results=max_results,
                )
            )

    def search_videos(
        self,
        keywords: str,
        *,
        region: str = "wt-wt",
        safesearch: Literal["on", "moderate", "off"] = "moderate",
        timelimit: str | None = None,
        resolution: str | None = None,
        duration: str | None = None,
        license_videos: str | None = None,
        max_results: int | None = 10,
    ) -> list[dict[str, Any]]:
        """
        视频检索。

        @param keywords - 关键词
        @returns 结果列表（title / content / embed_url 等）
        """
        with self._client() as ddgs:
            return list(
                ddgs.videos(
                    keywords,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    resolution=resolution,
                    duration=duration,
                    license_videos=license_videos,
                    max_results=max_results,
                )
            )

    def search_news(
        self,
        keywords: str,
        *,
        region: str = "wt-wt",
        safesearch: Literal["on", "moderate", "off"] = "moderate",
        timelimit: str | None = None,
        backend: str = "duckduckgo,bing",
        fallback_text: bool = True,
        max_results: int | None = 10,
    ) -> list[dict[str, Any]]:
        """
        新闻检索。

        @param keywords - 关键词
        @param backend - 新闻后端；默认顺序尝试 duckduckgo、bing，避免 auto 触发 Yahoo 超时
        @param fallback_text - 专用新闻后端无结果时，回退 text 检索
        @returns 结果列表（title / url / body / date 等）
        """
        news_region = _normalize_news_region(region)
        news_kwargs: dict[str, Any] = {
            "region": news_region,
            "safesearch": safesearch,
            "timelimit": timelimit,
            "max_results": max_results,
        }

        if self._ddgs_package == "duckduckgo_search":
            with self._client() as ddgs:
                return list(ddgs.news(keywords, **news_kwargs))

        last_err: BaseException | None = None
        for bk in _resolve_news_backends(backend):
            try:
                with self._client() as ddgs:
                    results = list(ddgs.news(keywords, backend=bk, **news_kwargs))
                if results:
                    return results
            except Exception as err:
                last_err = err
                if _is_retriable_news_error(err):
                    continue
                raise

        if fallback_text:
            text_query = keywords if "新闻" in keywords else f"{keywords} 新闻"
            text_region = region if region != "wt-wt" else news_region
            try:
                text_results = self.search_text(
                    text_query,
                    region=text_region,
                    safesearch=safesearch,
                    timelimit=timelimit if timelimit in ("d", "w", "m", "y") else None,
                    backend="auto",
                    max_results=max_results,
                )
                if text_results:
                    return _map_text_results_as_news(text_results)
            except Exception as err:
                if last_err is None:
                    last_err = err

        if last_err is not None:
            raise last_err
        return []


def search_text(keywords: str, *, max_results: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
    """
    便捷：文本检索。

    @param keywords - 关键词
    @param max_results - 条数
    @param kwargs - 传给 ``search_text`` 的其它参数
    @returns 结果列表
    """
    return DuckDuckGoSearchTool().search_text(keywords, max_results=max_results, **kwargs)


def search_images(keywords: str, *, max_results: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
    """便捷：图片检索。"""
    return DuckDuckGoSearchTool().search_images(keywords, max_results=max_results, **kwargs)


def search_videos(keywords: str, *, max_results: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
    """便捷：视频检索。"""
    return DuckDuckGoSearchTool().search_videos(keywords, max_results=max_results, **kwargs)


def search_news(keywords: str, *, max_results: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
    """便捷：新闻检索。"""
    return DuckDuckGoSearchTool().search_news(keywords, max_results=max_results, **kwargs)


def _add_common_client_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--proxy", default=None, help="HTTP(S)/SOCKS 代理")
    p.add_argument("--timeout", type=int, default=10, help="HTTP 超时（秒）")
    p.add_argument("--no-verify-ssl", action="store_true", help="关闭 SSL 校验")


def _client_options_from_args(args: argparse.Namespace) -> DuckDuckGoClientOptions:
    return DuckDuckGoClientOptions(
        proxy=_resolve_proxy(args.proxy),
        timeout=args.timeout,
        verify=not args.no_verify_ssl,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="aippt DuckDuckGo 搜索工具")
    p.add_argument("--list-params", action="store_true", help="打印全部参数说明")
    sub = p.add_subparsers(dest="mode", metavar="MODE")

    pt = sub.add_parser("text", help="网页文本检索")
    pt.add_argument("-k", "--keywords", required=True, help="检索词")
    pt.add_argument("-n", "--max-results", type=int, default=5)
    pt.add_argument("--region", default=None, help="如 cn-zh、wt-wt")
    pt.add_argument("--safesearch", choices=("on", "moderate", "off"), default="moderate")
    pt.add_argument("--timelimit", choices=("d", "w", "m", "y"), default=None)
    pt.add_argument("--backend", default="auto")
    _add_common_client_args(pt)

    pi = sub.add_parser("images", help="图片检索")
    pi.add_argument("-k", "--keywords", required=True)
    pi.add_argument("-n", "--max-results", type=int, default=5)
    pi.add_argument("--region", default="wt-wt")
    pi.add_argument("--safesearch", choices=("on", "moderate", "off"), default="moderate")
    _add_common_client_args(pi)

    pv = sub.add_parser("videos", help="视频检索")
    pv.add_argument("-k", "--keywords", required=True)
    pv.add_argument("-n", "--max-results", type=int, default=5)
    pv.add_argument("--region", default="wt-wt")
    _add_common_client_args(pv)

    pn = sub.add_parser("news", help="新闻检索")
    pn.add_argument("-k", "--keywords", required=True)
    pn.add_argument("-n", "--max-results", type=int, default=5)
    pn.add_argument("--region", default="wt-wt")
    pn.add_argument("--timelimit", choices=("d", "w", "m"), default=None)
    pn.add_argument(
        "--backend",
        default="duckduckgo,bing",
        help="新闻后端（默认 duckduckgo,bing；勿用 auto 以免 Yahoo 超时）",
    )
    pn.add_argument(
        "--no-fallback-text",
        action="store_true",
        help="禁用 text 检索回退",
    )
    _add_common_client_args(pn)

    return p


def main(argv: list[str] | None = None) -> int:
    """
    CLI 入口。

    @param argv - 命令行；None 为 sys.argv[1:]
    @returns 退出码
    """
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)

    if args.list_params:
        print(format_parameter_catalog_text())
        return 0

    if not args.mode:
        print("请指定子命令：text / images / videos / news，或使用 --list-params", file=sys.stderr)
        return 2

    tool = DuckDuckGoSearchTool(_client_options_from_args(args))

    try:
        if args.mode == "text":
            results = tool.search_text(
                args.keywords,
                region=args.region,
                safesearch=args.safesearch,
                timelimit=args.timelimit,
                backend=args.backend,
                max_results=args.max_results,
            )
        elif args.mode == "images":
            results = tool.search_images(
                args.keywords,
                region=args.region,
                safesearch=args.safesearch,
                max_results=args.max_results,
            )
        elif args.mode == "videos":
            results = tool.search_videos(
                args.keywords,
                region=args.region,
                max_results=args.max_results,
            )
        elif args.mode == "news":
            results = tool.search_news(
                args.keywords,
                region=args.region,
                timelimit=args.timelimit,
                backend=args.backend,
                fallback_text=not args.no_fallback_text,
                max_results=args.max_results,
            )
        else:
            print(f"未知模式: {args.mode}", file=sys.stderr)
            return 2
    except ImportError as err:
        print(
            "未安装检索依赖。请执行: pip install ddgs",
            file=sys.stderr,
        )
        print(str(err), file=sys.stderr)
        return 2
    except Exception as err:
        print(_format_search_error(err, proxy=tool.options.proxy), file=sys.stderr)
        return 1

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n共 {len(results)} 条。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
