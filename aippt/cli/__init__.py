# -*- coding: utf-8 -*-
"""命令行入口（``python -m aippt`` / ``python -m aippt.example_invoke``）。"""
from .pipeline import main as pipeline_main

__all__ = ["pipeline_main"]
