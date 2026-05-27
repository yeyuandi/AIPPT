# -*- coding: utf-8 -*-
"""兼容：``python -m aippt.example_invoke`` 转发至 ``aippt.cli.example_invoke``。"""
from aippt.cli.example_invoke import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
