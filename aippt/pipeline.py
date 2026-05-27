# -*- coding: utf-8 -*-
"""兼容：主流水线已迁至 ``aippt.cli.pipeline``。"""
from aippt.cli.pipeline import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
