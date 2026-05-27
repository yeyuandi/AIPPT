# -*- coding: utf-8 -*-
"""
LangChain 社区 DuckDuckGo 搜索工具封装。

两个可用工具：

- ``DuckDuckGoSearchRun``     — 返回摘要拼接字符串，适合直接给 LLM 阅读
- ``DuckDuckGoSearchResults`` — 返回结构化列表，每项含 title / link / snippet

常用构造参数（DuckDuckGoSearchResults）：

+------------------+--------------------------------------------------------------+
| 参数             | 说明                                                         |
+==================+==============================================================+
| num_results      | 返回条数（别名，内部字段名为 max_results，默认 4）           |
| output_format    | "list" → list[dict] / "json" → JSON 字符串 / "string"（默认）|
| backend          | "text"（网页，默认）/ "news" / "images"                     |
| keys_to_include  | 只保留指定字段，如 ["title","link"]；None 表示全部           |
| api_wrapper      | DuckDuckGoSearchAPIWrapper 实例，可自定义 region / safesearch |
+------------------+--------------------------------------------------------------+

本地测试::

    python -m aippt.search.langchain_ddg_tools
    python -m aippt.search.langchain_ddg_tools "LlamaIndex介绍"
    python -m aippt.search.langchain_ddg_tools "人工智能" --mode run
    python -m aippt.search.langchain_ddg_tools "人工智能" --mode results
    python -m aippt.search.langchain_ddg_tools "人工智能" --mode results -n 5 --backend news
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from langchain_community.tools import DuckDuckGoSearchResults, DuckDuckGoSearchRun
from langchain_community.utilities.duckduckgo_search import DuckDuckGoSearchAPIWrapper


def build_run_tool(*, region: str = "cn-zh") -> DuckDuckGoSearchRun:
    """
    创建 DuckDuckGoSearchRun 实例（返回摘要字符串）。

    @param region - 检索区域，如 cn-zh
    @returns 工具实例
    """
    return DuckDuckGoSearchRun(
        api_wrapper=DuckDuckGoSearchAPIWrapper(region=region)
    )


def build_results_tool(
    *,
    region: str = "cn-zh",
    num_results: int = 5,
    backend: str = "text",
    output_format: str = "list",
) -> DuckDuckGoSearchResults:
    """
    创建 DuckDuckGoSearchResults 实例（返回结构化结果）。

    @param region       - 检索区域
    @param num_results  - 返回条数
    @param backend      - text / news / images
    @param output_format - list / json / string
    @returns 工具实例
    """
    return DuckDuckGoSearchResults(
        num_results=num_results,
        output_format=output_format,
        api_wrapper=DuckDuckGoSearchAPIWrapper(region=region),
        backend=backend,
    )


def run_search(query: str, **kwargs: Any) -> str:
    """
    便捷：DuckDuckGoSearchRun 检索，返回摘要字符串。

    @param query  - 检索词
    @param kwargs - 透传给 build_run_tool
    @returns 摘要拼接字符串
    """
    return build_run_tool(**kwargs).run(query)


def run_search_results(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    """
    便捷：DuckDuckGoSearchResults 检索，返回结构化列表。

    @param query  - 检索词
    @param kwargs - 透传给 build_results_tool
    @returns list[dict]，每项含 title / link / snippet 等字段
    """
    return build_results_tool(**kwargs).run(query)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LangChain DuckDuckGo 搜索工具")
    p.add_argument("query", nargs="?", default="今天人工智能领域有什么新突破？", help="检索词")
    p.add_argument(
        "--mode", choices=("run", "results", "both"), default="both",
        help="run=摘要字符串  results=结构化列表  both=两者都执行（默认）",
    )
    p.add_argument("-n", "--num-results", type=int, default=5, help="结果条数（Results 模式）")
    p.add_argument("--region", default="cn-zh", help="区域，如 cn-zh / wt-wt")
    p.add_argument(
        "--backend", choices=("text", "news", "images"), default="text",
        help="检索类型（Results 模式）",
    )
    p.add_argument(
        "--output-format", choices=("list", "json", "string"), default="list",
        help="结构化结果格式（Results 模式）",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = _build_parser().parse_args(argv)

    try:
        if args.mode in ("run", "both"):
            print("=== DuckDuckGoSearchRun ===")
            result = run_search(args.query, region=args.region)
            print(result)

        if args.mode in ("results", "both"):
            print("\n=== DuckDuckGoSearchResults ===")
            rows = run_search_results(
                args.query,
                region=args.region,
                num_results=args.num_results,
                backend=args.backend,
                output_format=args.output_format,
            )
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            print(f"\n共 {len(rows)} 条。", file=sys.stderr)

    except ImportError as err:
        print("缺少依赖，请执行: pip install langchain-community ddgs", file=sys.stderr)
        print(str(err), file=sys.stderr)
        raise SystemExit(2)
    except Exception as err:
        print(f"检索失败: {err}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
