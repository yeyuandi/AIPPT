# -*- coding: utf-8 -*-
"""LLM 输出解析：Markdown 围栏与 JSON 大纲。"""
import json
import re

from aippt.domain.models import DeckOutline


def strip_fence(raw: str, lang: str) -> str:
    """
    去掉 ```lang … ``` 围栏（容错模型多余 Markdown）。

    @param raw - 模型原始字符串
    @param lang - 围栏语言标记（json / html）
    @returns 去围栏后的正文
    """
    pat = re.compile(rf"^\s*```{lang}\s*", re.I)
    cleaned = pat.sub("", raw.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def parse_outline_json(text: str) -> DeckOutline:
    """
    将模型输出解析为 DeckOutline。

    @param text - LLM 原始字符串
    @returns 校验通过的 DeckOutline 实例
    """
    trimmed = strip_fence(text, "json")
    data = json.loads(trimmed)
    return DeckOutline.model_validate(data)
