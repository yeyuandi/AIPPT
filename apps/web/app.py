# -*- coding: utf-8 -*-
"""
Flask 应用工厂：挂载向导蓝图与健康检查。
"""
from __future__ import annotations

import os
from pathlib import Path

import aippt.config  # noqa: F401 — 加载 `.env`，与 CLI 共用密钥配置

from flask import Flask, jsonify


def create_app(test_config: dict | None = None) -> Flask:
    """
    创建并配置 Flask 实例。

    @param test_config - 可选测试覆盖配置
    @returns 已注册路由的应用对象
    """
    base = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )

    app.config.setdefault(
        "SECRET_KEY",
        os.environ.get("FLASK_SECRET_KEY", "dev-only-change-FLASK_SECRET_KEY"),
    )
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("FLASK_MAX_UPLOAD_MB", "32")) * 1024 * 1024

    if test_config:
        app.config.update(test_config)

    from .wizard import bp as wizard_bp

    app.register_blueprint(wizard_bp)

    @app.route("/health")
    def health():
        """存活探针。"""
        return jsonify(ok=True, service="aippt-web")

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
