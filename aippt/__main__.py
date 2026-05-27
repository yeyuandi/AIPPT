# -*- coding: utf-8 -*-
"""允许使用 ``python -m aippt`` 启动流水线。"""
import sys

from aippt.cli.pipeline import main

raise SystemExit(main(sys.argv[1:]))
