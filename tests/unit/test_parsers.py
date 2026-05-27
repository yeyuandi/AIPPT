# -*- coding: utf-8 -*-
"""解析器单元测试（不调用真实 LLM）。"""
from aippt.domain import DeckOutline
from aippt.parsers import parse_outline_json, strip_fence


def test_strip_fence_json():
    """应去掉 json 围栏。"""
    raw = '```json\n{"slides": [{"title": "A", "summary": "", "bullets": []}]}\n```'
    assert "slides" in strip_fence(raw, "json")


def test_parse_outline_json():
    """应解析为 DeckOutline。"""
    payload = '{"slides": [{"title": "封面", "summary": "s", "bullets": ["b"]}]}'
    deck = parse_outline_json(payload)
    assert isinstance(deck, DeckOutline)
    assert deck.slides[0].title == "封面"
