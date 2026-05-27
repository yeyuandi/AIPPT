# -*- coding: utf-8 -*-
"""Pydantic 领域模型：大纲 JSON 与流水线中间数据结构。"""
from typing import List

from pydantic import BaseModel, Field, field_validator


class SlideOutline(BaseModel):
    """单页幻灯片的大纲（由 LLM 第一步生成）。"""

    title: str = Field(description="本页主标题，简短有力")
    summary: str = Field(default="", description="本页要讲的内容概要（60～120 字为宜），来自对原文的提炼")
    bullets: List[str] = Field(default_factory=list, description="要点列表")
    html_file: str = Field(default="", description="对应单页 HTML 文件名，如 slide_000.html")
    pptx_file: str = Field(default="", description="对应单页 pptx 文件名，如 slide_000.pptx")

    @field_validator("summary", mode="before")
    @classmethod
    def _coerce_summary(cls, value: object) -> str:
        """
        将 JSON null 或缺失外的异常值规范化为字符串。

        @param value - 原始输入
        @returns 去首尾空白后的概要文本，null 视为空串
        """
        if value is None:
            return ""
        return str(value).strip()


class DeckOutline(BaseModel):
    """整套幻灯片大纲（JSON 根对象）。"""

    slides: List[SlideOutline] = Field(description="按播放顺序排列的幻灯片")


def assign_slide_output_filenames(deck: DeckOutline, *, name_prefix: str = "slide") -> None:
    """
    按播放顺序为每页填入将生成的 HTML / pptx 文件名。

    @param deck - 已定稿页数的大纲
    @param name_prefix - 文件名前缀，默认 ``slide``
    @returns None（就地修改）
    """
    for idx, slide in enumerate(deck.slides):
        stem = f"{name_prefix}_{idx:03d}"
        slide.html_file = f"{stem}.html"
        slide.pptx_file = f"{stem}.pptx"


def format_deck_outline_plain(deck: DeckOutline) -> str:
    """
    将整套大纲格式化为便于阅读的纯文本。

    @param deck - 已定稿的大纲对象
    @returns 多段 UTF-8 文本
    """
    chunks: list[str] = []
    for idx, slide in enumerate(deck.slides, start=1):
        lines = [
            f"【第 {idx} 页】{slide.title.strip()}",
            f"概要：{slide.summary.strip()}" if slide.summary.strip() else "概要：（空）",
        ]
        if slide.html_file.strip() or slide.pptx_file.strip():
            lines.append(f"产出文件：{slide.html_file.strip()} | {slide.pptx_file.strip()}")
        if slide.bullets:
            for b in slide.bullets:
                lines.append(f"  - {b}")
        else:
            lines.append("  （无要点）")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks).strip() + "\n"


def deck_outline_to_json(deck: DeckOutline, *, indent: int = 2) -> str:
    """
    序列化为 JSON 字符串。

    @param deck - 大纲对象
    @param indent - JSON 缩进；0 表示压缩为一行
    @returns JSON 文本
    """
    return deck.model_dump_json(indent=indent if indent > 0 else None, ensure_ascii=False)
